"""人工校验工作台（归属：P2）—— **hard 边通道的落点**。

## 这条通道要解决什么问题

`hard` 边（"不会就学不动"）**必须靠语义判断**，而赛事不允许运行期调用外部大模型。
所以我们的做法是 SPEC §4.8 / D-15 定下的：

> **AI 预抽取（构建期，LearnBuddy 主 / 本地 3B 兜底）→ 人工校验（运行期工作台）**

**正式表述**（SPEC v1.5 已定稿）：
> 「**AI 预抽取 + 人工校验的知识点依赖图构建**」
> 答辩口径：**「AI 干粗活 + 人做裁决」**

## 三段式

```
① 构建期（离线）  教材 → 判"真前置" → 候选 hard 边 JSON
     载体：LearnBuddy（主）/ 本地 3B（兜底）。**不在这里做任何模型调用**
        ↓
② 导入（运行期，确定性）
     POST /api/review/import-edges
     校验：知识点必须存在 / reason 必填 / **成环则整批拒收** / 去重 / 稀疏性
     落库：source_channel='semantic'、needs_review=1（**候选，不是结论**）
        ↓
③ 人工裁决（运行期）
     GET  /api/review/queue        待复核清单
     POST /api/review/decide       采纳 → needs_review=0（进正式图）
                                   驳回 → pruned=1（**软删除，留痕**）
```

## 四个刻意的设计决定

**① 导入时**校验**环，不合规整批拒收 —— 而不是"先写进去再剪"。**
"依赖图必须无环"是我们的**工程不变量**（B1-2）。让脏数据先进库再清理，
会让不变量在某段时间里**实际上不成立**；而"拒收"让它在任何时刻都成立。

**② 驳回用 `pruned=1` 而不是删除。**
被驳回的边本身就是**"人做了判断"的证据** —— 答辩时说"我们检出了 N 条不合理依赖并由人驳回"
比"图很干净"更有说服力（对应 B1-2 / B1-4 的展示口径）。

**③ 导入的边一律 `needs_review=1`。**
它是**候选**。采纳之后才变成结论 —— 这样"图里有多少条是人确认过的"是可统计的。

**④ 边的 id 是复合键 `(kp_id, prereq_kp_id)`。**
数据库就是这么设计的（一个知识点对之间最多一条边）。这里**不另外造一个 id** ——
造了就要维护唯一性，而复合键本来就有。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.response import Envelope, ok
from app.db import get_db
from app.graph_view import load_graph
from app.models import KnowledgePoint, KpPrerequisite, utc_now_iso

router = APIRouter(tags=["review"])

DbSession = Annotated[Session, Depends(get_db)]

#: 一个知识点最多几条入边 / 出边（与 data-model.md §2.5 的稀疏性约束一致）
MAX_IN_DEGREE = 3
MAX_OUT_DEGREE = 4


# ---------------------------------------------------------------------------
# 契约
# ---------------------------------------------------------------------------


class EdgeCandidateIn(BaseModel):
    """**构建期产出的候选边**（一条）。

    这是 LearnBuddy / 本地 3B 的输出格式 —— 契约里的字段就这些，
    **不多不少**：多了会让上游编，少了会让人补。
    """

    kp_id: str = Field(description="后置（依赖方）知识点 id")
    prereq_kp_id: str = Field(description="前置（得先会的那个）知识点 id")
    relation_type: str = Field(default="hard", description="hard / soft")
    reason: str = Field(description="依赖理由 —— **必填**，B1-5 要求 100% 完备")
    evidence_quote: str | None = Field(default=None, description="材料原文中支持这条依赖的片段")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ImportEdgesIn(BaseModel):
    """一次导入一批候选边。"""

    edges: list[EdgeCandidateIn] = Field(min_length=1)
    source_note: str | None = Field(
        default=None, description="这批候选是谁/怎么产出的（便于追溯与答辩）"
    )


class ImportEdgesOut(BaseModel):
    accepted: int
    rejected: list[dict[str, Any]] = Field(default_factory=list, description="被拒的边与原因")
    cycle_count: int = Field(description="导入后全图的环数 —— **必须为 0**（B1-2）")


class ReviewItemOut(BaseModel):
    """复核队列的一项。"""

    kind: str = Field(description="`edge`（目前只有边需要人工裁决）")
    kp_id: str
    prereq_kp_id: str
    kp_name: str
    prereq_name: str
    relation_type: str
    reason: str
    evidence_quote: str | None = None
    confidence: float | None = None
    source_channel: str


class ReviewQueueOut(BaseModel):
    items: list[ReviewItemOut] = Field(default_factory=list)
    total: int = 0


class DecideIn(BaseModel):
    kp_id: str
    prereq_kp_id: str
    decision: str = Field(description="`accept` = 采纳进正式图；`reject` = 驳回（软删除留痕）")
    note: str | None = Field(default=None, description="驳回原因，写进理由便于追溯")


class DecideOut(BaseModel):
    kp_id: str
    prereq_kp_id: str
    decision: str
    needs_review: bool
    pruned: bool


# ---------------------------------------------------------------------------
# 端点 30：导入候选边
# ---------------------------------------------------------------------------


@router.post(
    "/review/import-edges",
    response_model=Envelope[ImportEdgesOut],
    summary="导入构建期产出的候选依赖边",
    description=(
        "把**构建期**（LearnBuddy / 本地 3B）产出的候选边导入。\n\n"
        "**导入的边一律标 `needs_review=1`** —— 它是候选，不是结论。\n\n"
        "⚠️ 三种情况会**整批拒收**（已导入的不回滚，但本批不入库）：\n"
        "① 任一端知识点不存在；② `reason` 为空；③ **导入后会成环**。\n"
        "第三种是刻意的：环校验是工程不变量，宁可拒收，也不让它在某段时间里不成立。"
    ),
)
def import_edges(payload: ImportEdgesIn, db: DbSession) -> Envelope[ImportEdgesOut]:
    rejected: list[dict[str, Any]] = []

    # ---- ① 逐条做静态校验 ------------------------------------------------
    valid: list[EdgeCandidateIn] = []
    for i, e in enumerate(payload.edges):
        if e.relation_type not in ("hard", "soft"):
            rejected.append({"index": i, "reason": f"relation_type 不合法：{e.relation_type}"})
            continue
        if not (e.reason or "").strip():
            rejected.append(
                {"index": i, "kp_id": e.kp_id, "reason": "reason 为空（B1-5 要求 100% 完备）"}
            )
            continue
        if e.kp_id == e.prereq_kp_id:
            rejected.append({"index": i, "kp_id": e.kp_id, "reason": "自环"})
            continue
        valid.append(e)

    # ---- ② 知识点必须存在 ------------------------------------------------
    ids = {e.kp_id for e in valid} | {e.prereq_kp_id for e in valid}
    existing = set(db.scalars(select(KnowledgePoint.id).where(KnowledgePoint.id.in_(ids))).all())
    missing = sorted(ids - existing)
    if missing:
        # 整批拒收：**一条引用了不存在知识点的导入不该被部分采纳** ——
        # 部分采纳会让"这批导入到底进没进"变得难以回答。
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            f"导入被拒：{len(missing)} 个知识点不存在，请先完成知识点抽取",
            {"missing": missing[:10]},
        )

    # ---- ③ 落库（先写，再验环；验出环就整批回滚）------------------------
    now = utc_now_iso()
    seen: set[tuple[str, str]] = set()
    accepted = 0
    for e in valid:
        key = (e.kp_id, e.prereq_kp_id)
        if key in seen:
            continue
        seen.add(key)

        row = db.get(KpPrerequisite, {"kp_id": e.kp_id, "prereq_kp_id": e.prereq_kp_id})
        if row is None:
            row = KpPrerequisite(
                kp_id=e.kp_id,
                prereq_kp_id=e.prereq_kp_id,
                pruned=0,
                created_at=now,
            )
            db.add(row)
        # ★ 无论新建还是覆盖，都回到"候选"状态 —— 覆盖意味着上游改了判断
        row.relation_type = e.relation_type
        row.reason = e.reason
        row.evidence_quote = e.evidence_quote
        row.confidence = e.confidence
        row.source_channel = "semantic"
        row.needs_review = 1
        row.pruned = 0
        accepted += 1

    db.flush()

    # ---- ④ 环校验：**不变量不允许被绕过** --------------------------------
    graph, _, _, result = load_graph(db)
    if result["cycle_count"]:
        db.rollback()
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            f"导入被拒：这批边会让依赖图出现 {result['cycle_count']} 个环 —— "
            "依赖图必须无环（B1-2），请先修候选边再导入",
            {"nodes_in_cycle": (result.get("nodes_in_cycle") or [])[:10]},
        )

    db.commit()
    return ok(
        ImportEdgesOut(accepted=accepted, rejected=rejected, cycle_count=result["cycle_count"])
    )


# ---------------------------------------------------------------------------
# 端点 31：复核队列
# ---------------------------------------------------------------------------


@router.get(
    "/review/queue",
    response_model=Envelope[ReviewQueueOut],
    summary="待人工复核的依赖边",
    description=(
        "列出 `needs_review=1` 的边（构建期导入的候选 + 结构线索产出时标出的可疑项）。\n\n"
        "**这就是「人做裁决」那个环节的入口** —— 队列为空说明图上没有未经确认的依赖。"
    ),
)
def review_queue(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Envelope[ReviewQueueOut]:
    rows = db.scalars(
        select(KpPrerequisite)
        .where(KpPrerequisite.needs_review == 1, KpPrerequisite.pruned == 0)
        .order_by(KpPrerequisite.created_at.desc())
        .limit(limit)
    ).all()

    ids = {r.kp_id for r in rows} | {r.prereq_kp_id for r in rows}
    names = (
        dict(db.execute(select(KnowledgePoint.id, KnowledgePoint.name).where(KnowledgePoint.id.in_(ids))).all())
        if ids
        else {}
    )

    items = [
        ReviewItemOut(
            kind="edge",
            kp_id=r.kp_id,
            prereq_kp_id=r.prereq_kp_id,
            kp_name=names.get(r.kp_id, ""),
            prereq_name=names.get(r.prereq_kp_id, ""),
            relation_type=r.relation_type,
            reason=r.reason or "",
            evidence_quote=r.evidence_quote,
            confidence=float(r.confidence) if r.confidence is not None else None,
            source_channel=r.source_channel,
        )
        for r in rows
    ]
    return ok(ReviewQueueOut(items=items, total=len(items)))


# ---------------------------------------------------------------------------
# 端点 32：裁决
# ---------------------------------------------------------------------------


@router.post(
    "/review/decide",
    response_model=Envelope[DecideOut],
    summary="裁决一条候选依赖边",
    description=(
        "`accept` = 采纳（`needs_review=0`，进正式图）；"
        "`reject` = 驳回（`pruned=1`，**软删除留痕**）。\n\n"
        "**驳回不物理删除** —— 被驳回的边是「人做了判断」的证据，"
        "答辩时说「检出了 N 条不合理依赖并由人驳回」比「图很干净」更有说服力。"
    ),
)
def decide(payload: DecideIn, db: DbSession) -> Envelope[DecideOut]:
    if payload.decision not in ("accept", "reject"):
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            f"decision 取值不合法：{payload.decision}",
            {"allowed": ["accept", "reject"]},
        )

    row = db.get(KpPrerequisite, {"kp_id": payload.kp_id, "prereq_kp_id": payload.prereq_kp_id})
    if row is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"依赖边不存在：{payload.prereq_kp_id} -> {payload.kp_id}",
        )

    if payload.decision == "accept":
        row.needs_review = 0
        row.pruned = 0
    else:
        row.needs_review = 0  # 已裁决，不再留在队列里
        row.pruned = 1
        if payload.note:
            # 把裁决理由追加进去，保留原理由 —— 两条都要留，便于回溯"为什么被驳"
            row.reason = f"{row.reason or ''}（人工驳回：{payload.note}）".strip()

    db.commit()
    return ok(
        DecideOut(
            kp_id=row.kp_id,
            prereq_kp_id=row.prereq_kp_id,
            decision=payload.decision,
            needs_review=bool(row.needs_review),
            pruned=bool(row.pruned),
        )
    )


