#!/usr/bin/env python
"""质量报告数据源（归属：P2）。对应 docs/api-spec.md §4.6，端点 19。

## 这个脚本干什么

把「质量报告页」（`GET /api/report/quality`）从 mock 变成真数据：
**直接读数据库算出各项指标**，而不是写死一组漂亮数字。

```bash
# 人看的报告（默认）
backend/.venv/Scripts/python.exe scripts/evaluate.py

# 机器读的 JSON（接口/CI 用）
backend/.venv/Scripts/python.exe scripts/evaluate.py --json

# 严格模式：任一验收指标不达标就非零退出（CI 可用）
backend/.venv/Scripts/python.exe scripts/evaluate.py --strict
```

## 两条设计原则

**① 不重复实现环检测。** 依赖图的环检测、理由完备率、稀疏性检查**复用**
`skills/xizhi-graph-infer/scripts/graph_infer.py` 的 `verify()` ——
那是已经实测通过的实现，同一套算法写两遍必然会分叉。

**② 只读。** 本脚本对所有表只做 SELECT，绝不写库。
评估工具污染被评估的数据是最没意义的错误。

## 两个容易算错的指标（都刻意定义清楚了）

**`grounded_rate`（接地率）的分母不含拒答轮次。**
拒答是**能力**不是缺陷 —— 把拒答算进分母会让"答不出来"看起来像"答错了"，
指标就失去意义。拒答次数单独用 `refuse_count` 报。

**`hallucination_rate`（幻觉率）= 1 − grounded_rate**，只在**真正给出回答的轮次**上计算。
配合上面的口径，拒答不会推高幻觉率。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 路径引导：脚本在 scripts/ 下，而代码在 backend/ 与 skills/ 下
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
GRAPH_ALGO_DIR = REPO_ROOT / "skills" / "xizhi-graph-infer" / "scripts"

for p in (str(BACKEND), str(GRAPH_ALGO_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402, F401  确保所有模型被注册
from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.models import (  # noqa: E402
    Chapter,
    KnowledgePoint,
    KpPrerequisite,
    Material,
    QaSession,
    QaTurn,
    Section,
)
from graph_infer import Graph, verify  # noqa: E402

# 验收指标 → (报告里的取值路径, 期望值, 是不是比率)
#
# ⚠️ `kind` 必须显式标注，**不能靠"期望值 ≤ 1.0 就当比率"来猜** ——
#    环数期望是 0（≤ 1.0），但它是个**计数**，用百分比显示就变成「0.00%」，
#    读者会以为在说比率。（这个 bug 在自检时抓到了。）
#
# ⚠️ 路径必须是**完整路径**。第一版把 `knowledge_points.` 前缀漏了，
#    `_dig` 取不到值返回 None，于是**在满数据的库上也会误判 FAIL**。
ACCEPTANCE: dict[str, tuple[str, float, str]] = {
    "A2-1 三级结构完整率": ("knowledge_points.structure_complete_rate", 1.0, "rate"),
    "A2-3 溯源覆盖率": ("knowledge_points.grounding_rate", 1.0, "rate"),
    "B1-2 依赖图环数": ("graph.cycle_count", 0.0, "count"),
    "B1-5 边理由完备率": ("graph.reason_complete_rate", 1.0, "rate"),
    "幻觉率（0 = 全部基于材料）": ("qa.hallucination_rate", 0.0, "rate"),
}


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> float:
    """占比。分母为 0 时返回 1.0。

    为什么返回 1.0 而不是 0.0：**没有数据 ≠ 有问题**。
    一个新库的"完备率"应该是 1.0（真空满足），否则每次初始化都会看到一片红，
    真出问题时反而看不出来。空库的异常由 `material_count == 0` 单独提示。
    """
    return 1.0 if denominator == 0 else round(numerator / denominator, 4)


def _dig(data: dict[str, Any], dotted: str) -> Any:
    """按 `a.b.c` 取值，用于把指标名映射到嵌套结果。"""
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


# ---------------------------------------------------------------------------
# 各层指标
# ---------------------------------------------------------------------------


def materials_layer(session: Session) -> dict[str, Any]:
    total = session.scalar(select(func.count()).select_from(Material)) or 0
    by_status: dict[str, int] = {}
    for status in ("pending", "parsing", "done", "failed", "partial"):
        by_status[status] = (
            session.scalar(
                select(func.count()).select_from(Material).where(Material.status == status)
            )
            or 0
        )

    avg_quality = session.scalar(select(func.avg(Material.quality_score)))

    # 存疑处条数：数据库里只有 uncertain_notes 这个 JSON 字符串，
    # 没有单独的计数列 —— 所以在这里解析出来。（解析失败就跳过并计数，
    # 不因为一条脏数据让整个报告跑不出来。）
    uncertain_total = 0
    uncertain_unparsable = 0
    for raw in session.scalars(select(Material.uncertain_notes)).all():
        if not raw:
            continue
        try:
            notes = json.loads(raw)
        except (TypeError, ValueError):
            uncertain_unparsable += 1
            continue
        if isinstance(notes, list):
            uncertain_total += len(notes)

    return {
        "total": total,
        "done": by_status["done"],
        "failed": by_status["failed"],
        "parsing": by_status["parsing"],
        "partial": by_status["partial"],
        "avg_quality_score": round(float(avg_quality), 4) if avg_quality is not None else None,
        "uncertain_count": uncertain_total,
        "_uncertain_unparsable": uncertain_unparsable,
    }


def knowledge_points_layer(session: Session) -> dict[str, Any]:
    total = session.scalar(select(func.count()).select_from(KnowledgePoint)) or 0

    # --- 三级结构完整率（A2-1）---------------------------------------------
    # 判据：三个归属字段都非空，且 section 记录真实存在（章-节-知识点链完整）。
    # 复合外键已经在数据库层保证了这一点，这里**再算一遍**是为了让"100%"这个
    # 说法是可验证的，而不是"因为约束在所以肯定对"。
    orphan_chain = (
        session.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .outerjoin(Section, KnowledgePoint.section_id == Section.id)
            .outerjoin(Chapter, KnowledgePoint.chapter_id == Chapter.id)
            .where(
                (KnowledgePoint.section_id.is_(None))
                | (KnowledgePoint.chapter_id.is_(None))
                | (KnowledgePoint.material_id.is_(None))
                | (Section.id.is_(None))
                | (Chapter.id.is_(None))
            )
        )
        or 0
    )

    # --- 溯源覆盖率（A2-3）-------------------------------------------------
    no_source = (
        session.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(
                (KnowledgePoint.source_material_id.is_(None))
                | (KnowledgePoint.source_quote.is_(None))
                | (func.length(func.trim(KnowledgePoint.source_quote)) == 0)
            )
        )
        or 0
    )

    # --- 五要素完备率 ------------------------------------------------------
    # 名称 / 摘要 / 难度 / 类型 / 溯源，缺一不可
    missing_field = (
        session.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(
                (KnowledgePoint.name.is_(None))
                | (func.length(func.trim(KnowledgePoint.name)) == 0)
                | (KnowledgePoint.summary_md.is_(None))
                | (func.length(func.trim(KnowledgePoint.summary_md)) == 0)
                | (KnowledgePoint.difficulty.is_(None))
                | (KnowledgePoint.kp_type.is_(None))
                | (KnowledgePoint.source_quote.is_(None))
            )
        )
        or 0
    )

    needs_review = (
        session.scalar(
            select(func.count()).select_from(KnowledgePoint).where(KnowledgePoint.needs_review == 1)
        )
        or 0
    )

    return {
        "total": total,
        "structure_complete_rate": _rate(total - orphan_chain, total),
        "grounding_rate": _rate(total - no_source, total),
        "five_field_complete_rate": _rate(total - missing_field, total),
        "needs_review_count": needs_review,
        "_orphan_chain": orphan_chain,
        "_no_source": no_source,
        "_missing_field": missing_field,
    }


def graph_layer(session: Session, kp_name_by_id: dict[str, str]) -> dict[str, Any]:
    """图指标 —— **环检测等复用 `graph_infer.verify()`**，不重写。"""
    rows = session.execute(select(KpPrerequisite)).scalars().all()

    payload_edges = []
    for e in rows:
        payload_edges.append(
            {
                # ⚠️ 方向映射：DB 的 prereq_kp_id 是「前置」= Edge.src，
                #    kp_id 是「后置/依赖方」= Edge.dst。搞反了环检测会失效。
                "prereq_name": e.prereq_kp_id,
                "dependent_name": e.kp_id,
                "relation_type": e.relation_type,
                "reason": e.reason or "",
                "confidence": float(e.confidence) if e.confidence is not None else 0.0,
                "pruned": bool(e.pruned),
            }
        )

    graph = Graph.from_payload({"nodes": sorted(kp_name_by_id.keys()), "edges": payload_edges})
    result = verify(graph)

    conflict_count = sum(1 for e in rows if e.needs_review == 1)

    out = {
        "edge_count": result["edge_count"],
        "hard_edge_count": result["hard_edge_count"],
        "soft_edge_count": result["soft_edge_count"],
        "cycle_count": result["cycle_count"],
        "pruned_count": result["pruned_edge_count"],
        "conflict_count": conflict_count,
        "reason_complete_rate": result["reason_complete_rate"],
        "sparsity_ok": result["sparsity_ok"],
        "max_in_degree": result["max_in_degree"],
        "max_out_degree": result["max_out_degree"],
        "self_loop_count": len(result["self_loops"]),
        "isolated_node_count": len(result["isolated_nodes"]),
        # 人工抽检——需要人给判据，自动算不出来，没有样本就是 None（不编数字）
        "prerequisite_sampling_pass_rate": None,
    }
    if result["cycle_count"]:
        out["_nodes_in_cycle"] = result["nodes_in_cycle"]
    if result["missing_reason"]:
        out["_missing_reason"] = result["missing_reason"]
    if result["isolated_nodes"]:
        out["_isolated_nodes"] = result["isolated_nodes"]
    return out


def qa_layer(session: Session) -> dict[str, Any]:
    session_count = session.scalar(select(func.count()).select_from(QaSession)) or 0
    turn_count = session.scalar(select(func.count()).select_from(QaTurn)) or 0

    # 只在**导师轮次**上算接地率 —— 学生轮次没有"是否基于材料"的含义
    tutor_total = (
        session.scalar(select(func.count()).select_from(QaTurn).where(QaTurn.role == "tutor")) or 0
    )
    refuse_count = (
        session.scalar(
            select(func.count())
            .select_from(QaTurn)
            .where((QaTurn.role == "tutor") & (QaTurn.turn_type == "refuse"))
        )
        or 0
    )
    grounded = (
        session.scalar(
            select(func.count())
            .select_from(QaTurn)
            .where((QaTurn.role == "tutor") & (QaTurn.grounded == 1))
        )
        or 0
    )

    # ★ 分母排除拒答：拒答是能力不是缺陷，算进去会让指标失真
    answered = tutor_total - refuse_count
    grounded_rate = _rate(grounded, answered)

    return {
        "session_count": session_count,
        "turn_count": turn_count,
        "tutor_turn_count": tutor_total,
        "answered_turn_count": answered,
        "grounded_rate": grounded_rate,
        "hallucination_rate": round(1.0 - grounded_rate, 4),
        "refuse_count": refuse_count,
    }


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def collect() -> dict[str, Any]:
    _require_schema()
    with Session(engine) as session:
        kp_name_by_id = {
            kp_id: name
            for kp_id, name in session.execute(select(KnowledgePoint.id, KnowledgePoint.name)).all()
        }
        return {
            "materials": materials_layer(session),
            "knowledge_points": knowledge_points_layer(session),
            "graph": graph_layer(session, kp_name_by_id),
            "qa": qa_layer(session),
        }


# 期望存在的表。缺任一张就说明库还没初始化，这时算指标没有意义。
_REQUIRED_TABLES = ("materials", "knowledge_points", "kp_prerequisites", "qa_turns")


def _require_schema() -> None:
    """先确认库里有表，没表就给一句人话。

    **为什么值得单独写**：不加这一步，用户看到的是一屏 SQLAlchemy 堆栈，
    最后一行才是 `no such table`。而真实原因通常只是"忘了跑迁移"——
    让人从 40 行 traceback 里反推出这一点，是不必要的消耗。
    """
    from sqlalchemy import inspect

    existing = set(inspect(engine).get_table_names())
    missing = [t for t in _REQUIRED_TABLES if t not in existing]
    if not missing:
        return

    print(
        f"❌ 数据库里缺少表：{', '.join(missing)}\n"
        f"\n"
        f"   当前库：{settings.db_file}\n"
        f"   已有表：{sorted(existing) if existing else '（空库，一张表都没有）'}\n"
        f"\n"
        f"   多半是还没跑迁移。先执行：\n"
        f"       cd backend && .venv/Scripts/python.exe -m alembic upgrade head\n",
        file=sys.stderr,
    )
    raise SystemExit(2)


def check_acceptance(report: dict[str, Any]) -> list[tuple[str, float, str, Any, bool]]:
    """逐条对照验收指标。返回 (标签, 期望值, kind, 实际值, 是否通过)。"""
    rows = []
    for label, (path, expected, kind) in ACCEPTANCE.items():
        actual = _dig(report, path)
        if not isinstance(actual, (int, float)):
            # 取不到值 = 路径写错或报告结构变了。**不能当成通过**。
            ok = False
        else:
            ok = abs(float(actual) - float(expected)) < 1e-9
        rows.append((label, expected, kind, actual, ok))
    return rows


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def _pct(v: Any) -> str:
    return "—" if v is None else f"{float(v) * 100:.2f}%"


def _num(v: Any) -> str:
    return "—" if v is None else str(v)


def _dwidth(s: str) -> int:
    """字符串在终端里的**显示宽度**。

    中文是全角（占 2 列）而 `len()` 只算 1，直接用 `f"{s:<20}"` 补齐会让
    中英混排的行错位 —— 报告里到处是中文标签，不处理就一片歪。
    """
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def render(report: dict[str, Any], db_file: str) -> str:
    m, k, g, q = (
        report["materials"],
        report["knowledge_points"],
        report["graph"],
        report["qa"],
    )
    lines: list[str] = []
    add = lines.append

    add("=" * 64)
    add("析知 XiZhi · 质量报告")
    add("=" * 64)
    add(f"数据库：{db_file}")
    add("")

    add("【素材】")
    add(f"  总数 {m['total']}   完成 {m['done']}   部分完成 {m['partial']}")
    add(f"  解析中 {m['parsing']}   失败 {m['failed']}")
    add(f"  平均解析质量 {_num(m['avg_quality_score'])}    存疑处 {m['uncertain_count']} 条")
    add("")

    add("【知识点】")
    add(f"  总数 {k['total']}    待核实 {k['needs_review_count']}")
    add(f"  三级结构完整率   {_pct(k['structure_complete_rate'])}   ← A2-1 目标 100%")
    add(f"  溯源覆盖率       {_pct(k['grounding_rate'])}   ← A2-3 目标 100%")
    add(f"  五要素完备率     {_pct(k['five_field_complete_rate'])}")
    if k["_orphan_chain"]:
        add(f"    ⚠️ 归属链断裂 {k['_orphan_chain']} 条")
    if k["_no_source"]:
        add(f"    ⚠️ 缺溯源 {k['_no_source']} 条")
    if k["_missing_field"]:
        add(f"    ⚠️ 五要素缺失 {k['_missing_field']} 条")
    add("")

    add("【依赖图】")
    add(
        f"  节点 {k['total']}   边 {g['edge_count']}"
        f"（hard {g['hard_edge_count']} / soft {g['soft_edge_count']}）"
    )
    add(f"  环数             {g['cycle_count']}        ← B1-2 必须为 0")
    add(f"  边理由完备率     {_pct(g['reason_complete_rate'])}   ← B1-5 目标 100%")
    add(f"  已剪除边         {g['pruned_count']} 条")
    add(f"  结构-语义冲突    {g['conflict_count']} 条（已标 needs_review）")
    add(
        f"  入/出度上限      {g['max_in_degree']}/{g['max_out_degree']}"
        f"  稀疏性 {'OK' if g['sparsity_ok'] else '超标'}"
    )
    if g["isolated_node_count"]:
        add(
            f"  孤立节点         {g['isolated_node_count']} 个"
            f"（可能是地基知识点，也可能漏了边 —— 需人工判断）"
        )
    add(
        f"  人工抽检通过率   {_pct(g['prerequisite_sampling_pass_rate'])}（需要人工标注样本，暂缺）"
    )
    for key, hint in (
        ("_nodes_in_cycle", "成环涉及节点"),
        ("_missing_reason", "缺理由的边"),
        ("_isolated_nodes", "孤立节点"),
    ):
        if g.get(key):
            sample = g[key][:5]
            add(f"    ⚠️ {hint}（前 5 条）：{sample}")
    add("")

    add("【答疑】")
    add(f"  会话 {q['session_count']}   总轮次 {q['turn_count']}（导师 {q['tutor_turn_count']}）")
    add(
        f"  接地率           {_pct(q['grounded_rate'])}"
        f"（在 {q['answered_turn_count']} 个实际回答轮次上算）"
    )
    add(f"  幻觉率           {_pct(q['hallucination_rate'])}   ← 必须为 0")
    add(f"  越界拒答         {q['refuse_count']} 次（**拒答是能力不是缺陷**，不计入接地率分母）")
    add("")

    add("【验收指标】")
    rows = check_acceptance(report)
    width = max(_dwidth(label) for label, *_ in rows)
    for label, expected, kind, actual, ok in rows:
        mark = "PASS" if ok else "FAIL"
        # 显示格式由显式标注的 kind 决定，不靠数值大小猜（见 ACCEPTANCE 的注释）
        fmt = _pct if kind == "rate" else _num
        if kind == "rate":
            shown, exp = fmt(actual), _pct(expected)
        else:
            shown, exp = fmt(actual), _num(int(expected))
        add(f"  [{mark}] {label}{' ' * (width - _dwidth(label))}  期望 {exp:<9} 实际 {shown}")
    add("")

    if m["total"] == 0 and k["total"] == 0:
        add("⚠️ 库里还没有数据 —— 上面的比率按「真空满足」显示为 100%。")
        add("   等 P1 的解析产物入库后再跑一次，那时的数字才有意义。")
        add("")

    add("=" * 64)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="析知质量报告（只读，不改数据库）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--json", action="store_true", help="输出 JSON（接口/CI 用）")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="任一验收指标不达标则非零退出（CI 用）",
    )
    args = ap.parse_args(argv)

    report = collect()
    rows = check_acceptance(report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, str(settings.db_file)))

    if args.strict:
        failed = [label for label, _, _, _, ok in rows if not ok]
        if failed:
            print(f"\n❌ 验收指标未达标（{len(failed)} 项）：{failed}", file=sys.stderr)
            return 1
        print("\n✅ 全部验收指标达标", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
