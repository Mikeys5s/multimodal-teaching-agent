#!/usr/bin/env python
"""质量报告 CLI（归属：P2）。对应 docs/api-spec.md §4.6，端点 19。

## 这个脚本现在的定位：**薄 CLI**

指标的**计算已经搬进 `backend/app/quality.py`** —— 因为端点也要用，
而两套实现必然分叉（之前端点返回写死的 mock，和这里算出来的数字是两套）。

**现在的关系是：**

```
backend/app/quality.py::compute(db)     ← 唯一来源（端点与 CLI 都调它）
        ↑                      ↑
GET /api/report/quality      本脚本（CLI 包装 + 人类可读的渲染）
```

所以本文件只负责三件事：**开库 → 渲染成人看的文本 → 决定退出码**。

```bash
# 人看的报告（默认）
backend/.venv/Scripts/python.exe scripts/evaluate.py

# 机器读的 JSON（接口/CI 用）
backend/.venv/Scripts/python.exe scripts/evaluate.py --json

# 严格模式：任一验收指标不达标就非零退出（CI 可用）
backend/.venv/Scripts/python.exe scripts/evaluate.py --strict
```

## 一条不变的原则

**只读。** 对所有表只做 SELECT，绝不写库。
评估工具污染被评估的数据是最没意义的错误。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 路径引导：脚本在 scripts/ 下，而代码在 backend/ 下
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import inspect  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402, F401  确保所有模型被注册
from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.quality import check_acceptance, compute  # noqa: E402

# 期望存在的表。缺任一张就说明库还没初始化，这时算指标没有意义。
_REQUIRED_TABLES = ("materials", "knowledge_points", "kp_prerequisites", "qa_turns")


def _require_schema() -> None:
    """先确认库里有表，没表就给一句人话。

    **为什么值得单独写**：不加这一步，用户看到的是一屏 SQLAlchemy 堆栈，
    最后一行才是 `no such table`。而真实原因通常只是"忘了跑迁移"——
    让人从 40 行 traceback 里反推出这一点，是不必要的消耗。

    这一步只在 CLI 里做；**端点不需要** —— 端点跑在已迁移过的库上，
    而且"库没迁移"在那边应该表现为 500 + 明确错误，不是静默返回空报告。
    """
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


def collect() -> dict[str, Any]:
    """CLI 侧的取数入口：开一个 session，交给 `app.quality.compute()`。

    ⚠️ **这里不做任何计算** —— 计算全在 `app.quality`。
    本函数存在的唯一理由是端点已经有 session（`Depends(get_db)`），
    而 CLI 需要自己开一个。
    """
    _require_schema()
    with Session(engine) as session:
        return compute(session)


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def _pct(v: Any) -> str:
    return "—" if v is None else f"{float(v) * 100:.2f}%"


def _num(v: Any) -> str:
    return "—" if v is None else f"{float(v):.4f}"


def _dwidth(s: str) -> int:
    """按显示宽度算长度 —— 中文算 2。

    不做这个，中文标签的对齐会全乱（`len()` 把每个汉字算 1）。
    """
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


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
    add("数据来源：app/quality.py::compute()（与 GET /api/report/quality 同源）")
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
    add(f"  人工抽检通过率   {_pct(g['prerequisite_sampling_pass_rate'])}（需要人工标注样本，暂缺）")
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
    width = max(_dwidth(r.label) for r in rows)
    for r in rows:
        # ⚠️ **三态，不是二态。**（2026-09-20 改）
        #
        # `r.passed` 可以是 `None` = **样本为 0，无从判定**。
        # 原来写的是 `"PASS" if r.passed else "FAIL"` —— `None` 是 falsy，
        # **于是"没数据可判"被显示成"不达标"**，健康的图也让 `--strict` 返回 1。
        #
        # 这两件事必须分开：前者是缺数据，后者是真的不合格。
        mark = "N/A" if r.passed is None else ("PASS" if r.passed else "FAIL")
        # 显示格式由显式标注的 kind 决定，不靠数值大小猜（见 quality.ACCEPTANCE 的注释）
        if r.kind == "rate":
            shown, exp = _pct(r.actual), _pct(r.expected)
        else:
            shown, exp = _num(r.actual), _num(int(r.expected))
        pad = " " * (width - _dwidth(r.label))
        add(f"  [{mark}] {r.label}{pad}  期望 {exp:<9} 实际 {shown}")
    add("")

    if m["total"] == 0 and k["total"] == 0:
        add("⚠️ 库里还没有数据 —— 上面的比率按「真空满足」显示为 100%。")
        add("   等解析产物入库后再跑一次，那时的数字才有意义。")
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
        # 顺带把验收结论也带上（对象数组）—— 只给四段式数字的话，
        # 消费方还得自己知道"哪个该等于几"，那就是又一套口径。
        print(
            json.dumps(
                {**report, "acceptance": [r._asdict() for r in rows]},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render(report, str(settings.db_file)))

    if args.strict:
        # ⚠️ **判据必须是 `is False`，不能是 `not r.passed`**（2026-09-21 修）
        #
        # `r.passed` 有三种值：`True` / `False` / **`None`（样本为 0，无从判定）**。
        #
        #     `not None` → `True`   ← **"没数据可判"被算成了"不达标"**
        #
        # 后果：**一个健康的图也会让 `--strict` 返回 1**，
        # CI / 部署脚本会把"库里没数据"误报成"质量不合格"。
        #
        # 上面**显示**那段（`mark = "N/A" if r.passed is None else ...`）早就分开处理了，
        # **但退出码这处没同步改** —— 同一件事两处判据，改了一处忘另一处。
        # 症状就是"报告显示 N/A、退出码却说失败"，**两者自相矛盾**。
        failed = [r.label for r in rows if r.passed is False]
        na = [r.label for r in rows if r.passed is None]
        if na:
            print(f"\n⚠️ {len(na)} 项缺少样本、无法判定（**不计入失败**）：{na}", file=sys.stderr)
        if failed:
            print(f"\n❌ 验收指标未达标（{len(failed)} 项）：{failed}", file=sys.stderr)
            return 1
        print("\n✅ 全部可判定的验收指标达标", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
