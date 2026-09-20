"""质量指标计算（归属：P2）。对应 docs/api-spec.md §4.6，端点 19。

## 这个模块存在的理由

之前有**两套数字**：
- `GET /api/report/quality` 返回**写死的 mock**（`total=184` / `edge_count=267`…）
- `scripts/evaluate.py` 从数据库**真算**一遍

它们**一定会分叉** —— 报告页给评委看的漂亮数字，和验收时跑出来的数字，
只要有一处不一致，答辩现场就解释不清。**而它不会报错，只会悄悄不一致。**

所以把计算搬到这里（app 包内），让**端点与 CLI 都调同一个函数**。

## 三条设计原则

**① 只读。** 对所有表只做 SELECT，绝不写库。
评估工具污染被评估的数据是最没意义的错误。

**② 不重复实现环检测。** 环检测、理由完备率、稀疏性检查**复用**
`skills/xizhi-graph-infer/scripts/graph_infer.py` 的 `verify()` ——
那是已经实测通过的实现，**同一套算法写两遍必然会分叉**。

> ⚠️ **关于下面那段 `sys.path` 注入**（看起来是丑做法，说明一下为什么）：
>
> `graph_infer` 同时是**两个交付物**：
> ① **产品能力**（环校验是主创新点，端点要用）——
> ② **一个可独立复用的 skill**（`skills/xizhi-graph-infer/`，赛事鼓励的"复用产物"，
>   它必须**自包含**、脱离本仓库也能用）。
>
> 若复制成两份，就会有**漂移**风险：改了一边忘了另一边 → 两处结论不一致，**且不报错**。
> 所以选择**保持单一份源码**，代价是这里要做路径注入。
> 部署时由 `Dockerfile` 把 `skills/` 拷进镜像（`COPY skills/ /app/skills/`），
> 否则容器里 import 不到 —— **这个坑不写出来，下次一定有人踩**。

**③ 两个容易算错的指标，口径显式定义。**

**`grounded_rate`（接地率）的分母不含拒答轮次。**
拒答是**能力**不是缺陷 —— 把拒答算进分母会让"答不出来"看起来像"答错了"，
指标就失去意义。拒答次数单独用 `refuse_count` 报。

**`hallucination_rate`（幻觉率）= 1 − grounded_rate**，只在**真正给出回答的轮次**上计算。
配合上面的口径，拒答不会推高幻觉率。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Chapter,
    KnowledgePoint,
    KpPrerequisite,
    Material,
    QaSession,
    QaTurn,
    Section,
)


# ---------------------------------------------------------------------------
# graph_infer 的路径引导（见模块 docstring 第 ② 条）
# ---------------------------------------------------------------------------
def _graph_algo_dir() -> Path | None:
    """找到 `graph_infer.py` 所在目录。找不到返回 None（由调用处给出人话报错）。"""
    override = os.environ.get("XIZHI_GRAPH_ALGO_DIR")
    candidates = []
    if override:
        candidates.append(Path(override))
    # backend/app/quality.py -> parents[2] 是仓库根；容器里是 /app
    candidates.append(Path(__file__).resolve().parents[2] / "skills" / "xizhi-graph-infer" / "scripts")
    candidates.append(Path("/app/skills/xizhi-graph-infer/scripts"))
    for c in candidates:
        if (c / "graph_infer.py").is_file():
            return c
    return None


_ALGO_DIR = _graph_algo_dir()
if _ALGO_DIR is not None and str(_ALGO_DIR) not in sys.path:
    sys.path.insert(0, str(_ALGO_DIR))

try:
    from graph_infer import Graph, verify  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:  # pragma: no cover - 只在部署漏拷 skills/ 时触发
    raise ModuleNotFoundError(
        "找不到 `graph_infer`（依赖图算法）。它住在 `skills/xizhi-graph-infer/scripts/`。\n"
        f"  已尝试的目录：{_ALGO_DIR}\n"
        "\n"
        "  两种可能：\n"
        "    · 本地：仓库不完整（`skills/` 目录缺失）\n"
        "    · 容器：`Dockerfile` 里少了一行 `COPY skills/ /app/skills/`\n"
        "\n"
        "  可用环境变量 XIZHI_GRAPH_ALGO_DIR 直接指定目录。\n"
        "  （这条报错是刻意写长的 —— 默认的 ModuleNotFoundError 完全指不出真正原因。）"
    ) from exc


# 验收指标 → (报告里的取值路径, 期望值, 是不是比率)
#
# ⚠️ `kind` 必须显式标注，**不能靠"期望值 ≤ 1.0 就当比率"来猜** ——
#    环数期望是 0（≤ 1.0），但它是个**计数**，用百分比显示就变成「0.00%」，
#    读者会以为在说比率。（这个 bug 在自检时抓到了。）
#
# ⚠️ 路径必须是**完整路径**。第一版把 `knowledge_points.` 前缀漏了，
#    `_dig` 取不到值返回 None，于是**在满数据的库上也会误判 FAIL**。
#: label -> (值路径, 期望值, 类型, **样本量路径**)
#:
#: ⚠️ **第四项（样本量）是后加的，它比前三项都重要。**
#: 没有它，`structure_complete_rate` 在 0 个知识点时按定义等于 1.0
#: —— 报告会显示"五项验收全绿"，而实际上**什么都还没测**。
ACCEPTANCE: dict[str, tuple[str, float, str, str]] = {
    "A2-1 三级结构完整率": (
        "knowledge_points.structure_complete_rate", 1.0, "rate",
        "knowledge_points.total",
    ),
    "A2-3 溯源覆盖率": (
        "knowledge_points.grounding_rate", 1.0, "rate",
        "knowledge_points.total",
    ),
    "B1-2 依赖图环数": ("graph.cycle_count", 0.0, "count", "graph.edge_count"),
    "B1-5 边理由完备率": (
        "graph.reason_complete_rate", 1.0, "rate",
        "graph.edge_count",
    ),
    "幻觉率（0 = 全部基于材料）": (
        "qa.hallucination_rate", 0.0, "rate",
        "qa.turn_count",
    ),
}


class AcceptanceRow(NamedTuple):
    """一条验收指标的实测结果。

    用 `NamedTuple` 而非 dict / dataclass：**两种访问方式都要**
    —— CLI 与它的测试按元组解包（`label, expected, kind, actual, ok`），
    端点按字段名建响应模型（`row.passed`）。
    """

    label: str
    expected: float
    kind: str
    actual: float | None
    #: `None` = **样本为 0，无从判定**（不是"不达标"）。
    #:
    #: ⚠️ 不能把"没东西可测"和"测了但不达标"混成同一个值：
    #: 前者应该显示 N/A，后者才该标红。原先两者都表现成 `True`
    #: （分母为 0 的比率恒等于 1.0），评审看到"五项全绿"一追问数据量就露底。
    passed: bool | None


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> float:
    """占比。分母为 0 时返回 1.0。

    为什么返回 1.0 而不是 0.0：**没有数据 ≠ 有问题**。
    一个新库的"完备率"应该是 1.0（真空满足），否则每次初始化都会看到一片红，
    真出问题时反而看不出来。空库的异常由 `materials.total == 0` 单独提示。
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
# 汇总（★ 端点与 CLI 的唯一入口）
# ---------------------------------------------------------------------------


def compute(db: Session) -> dict[str, Any]:
    """算出四层指标。

    **这是唯一入口** —— `GET /api/report/quality` 与 `scripts/evaluate.py` 都调它。
    `db` 由调用方给（端点用请求的 session，CLI 自己开一个），
    这样端点不会为了一次统计另开一条连接。
    """
    kp_name_by_id = {
        kp_id: name
        for kp_id, name in db.execute(select(KnowledgePoint.id, KnowledgePoint.name)).all()
    }
    return {
        "materials": materials_layer(db),
        "knowledge_points": knowledge_points_layer(db),
        "graph": graph_layer(db, kp_name_by_id),
        "qa": qa_layer(db),
    }


def acceptance_sample_sizes(report: dict[str, Any]) -> dict[str, float | None]:
    """每条验收指标的**样本量** —— label -> sample_size。

    和 `check_acceptance` 并列而不是塞进 `AcceptanceRow`：
    那个 NamedTuple 的元数被 CLI 与测试的元组解包依赖，**不能加字段**。

    为什么要单独把样本量暴露出去：
    `structure_complete_rate` 这类比率**在样本为 0 时按定义等于 1.0**，
    只报 `passed=true` 会让评审以为"测过了、且合格"。
    **带上样本量，评审一眼就能看出"这条其实没有数据支撑"。**
    """
    out: dict[str, float | None] = {}
    for label, (_path, _expected, _kind, sample_path) in ACCEPTANCE.items():
        v = _dig(report, sample_path)
        out[label] = float(v) if isinstance(v, (int, float)) else None
    return out


def check_acceptance(report: dict[str, Any]) -> list[AcceptanceRow]:
    """逐条对照验收指标。返回结构化行（端点与 CLI 共用）。

    返回 `NamedTuple` 而不是 dict，是**刻意**的：
    它**既支持元组解包**（`for label, expected, kind, actual, ok in rows` ——
    已有的 CLI 与它的测试都是这么用的），**又支持具名访问**（`row.passed` ——
    端点要按字段建响应模型）。两种用法不必各自维护一套结构。
    """
    rows: list[AcceptanceRow] = []
    for label, (path, expected, kind, sample_path) in ACCEPTANCE.items():
        actual = _dig(report, path)
        sample = _dig(report, sample_path)

        if not isinstance(actual, (int, float)):
            # 取不到值 = 路径写错或报告结构变了。**不能当成通过**。
            passed: bool | None = False
        elif isinstance(sample, (int, float)) and float(sample) == 0:
            # ★ **样本为 0 → 无从判定，`None`。**
            #
            # 这里就是"真空满足"的入口：分母为 0 时比率恒等于期望值
            # （完整率 1.0、覆盖率 1.0、环数 0.0），于是**永远"全绿"**。
            # 但那是"没有数据"，不是"数据合格"。
            #
            # 判成 `False` 也不对 —— 那会把"还没测"说成"不达标"。
            # 只有 `None` 诚实：**这条现在无法判定**。
            passed = None
        else:
            passed = abs(float(actual) - float(expected)) < 1e-9
        rows.append(AcceptanceRow(label, expected, kind, actual, passed))
    return rows
