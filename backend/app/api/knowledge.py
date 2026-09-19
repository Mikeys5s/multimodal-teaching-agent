"""知识点查询（归属：P2）。对应 docs/api-spec.md §4.2 / §4.3 / §4.4，端点 14、15、28。

★ 本文件承载**创新点的查询侧**：
  · `GET /api/knowledge-points/{id}` 返回的 `prerequisites[].reason` 让"为什么这个要排在前面"可解释；
  · `GET /api/knowledge-points/{id}/gap-analysis` 是**卡点根因回溯** ——
    不满足于说"你这题错了"，而是沿 hard 边反向回溯指出更可能的根因。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.pagination import PageData, PageParams
from app.core.response import Envelope, ok
from app.db import get_db
from app.graph_view import gap_analysis as run_gap_analysis
from app.graph_view import load_graph
from app.models import (
    Chapter,
    KnowledgePoint,
    KpExample,
    KpMisconception,
    KpPrerequisite,
    Material,
    Section,
)
from app.schemas.graph import (
    GapAnalysisOut,
    GapSourceOut,
    HardPrereqOut,
    KpBriefOut,
    LikelyGapOut,
)
from app.schemas.knowledge import (
    ChapterRefOut,
    ExampleOut,
    KpDetailOut,
    KpItemOut,
    MisconceptionOut,
    PrerequisiteOut,
    SectionRefOut,
    SourceRefOut,
)

router = APIRouter(tags=["knowledge"])

DbSession = Annotated[Session, Depends(get_db)]
PageDep = Annotated[PageParams, Depends(PageParams.as_dependency)]

MOCK_MODE = True

KP_TYPES = ("concept", "skill", "theorem", "method", "fact")

KP_ID = "kp_9f2a1c40_000_002_003"


def _strict_bool(
    # ⚠️ 参数名必须与查询参数名一致（`needs_review`）——
    # FastAPI 是按**形参名**去查请求参数的。写成 `value` 会去读 `?value=`，
    # 永远拿到 None，于是校验静默失效（查了半天才发现）。
    needs_review: Annotated[str | None, Query(description="严格布尔：只接受 true / false")] = None,
) -> bool | None:
    """严格布尔查询参数（api-spec v1.3）。

    ⚠️ 为什么要自己解析：**FastAPI 默认的 `bool` 解析会把 `1`/`0` 也当成布尔**，
    于是规格里写的「不静默兼容 `0`/`1`」形同虚设 —— 契约写了、实际不生效，
    比不写更糟。这个函数把取值收窄到只有 `true` / `false`。

    （这个疏漏是被 `tests/test_api_smoke.py` 抓到的。）
    """
    if needs_review is None:
        return None
    normalized = needs_review.strip().lower()
    if normalized not in ("true", "false"):
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            f"needs_review 只接受 true 或 false，收到 {needs_review!r}",
            {"allowed": ["true", "false"]},
        )
    return normalized == "true"


StrictBoolDep = Annotated[bool | None, Depends(_strict_bool)]


# ---------------------------------------------------------------------------
# mock 数据（计算机网络 · 传输层，演示时直接可用）
# ---------------------------------------------------------------------------


def _load_refs(db: Session, kps: list[KnowledgePoint]) -> tuple[dict, dict, dict]:
    """批量取章 / 节 / 材料，**避免 N+1 查询**。

    列表端点一页可能有几十个知识点，逐个 `db.get(Chapter, ...)` 就是几十次往返。
    这里一次 `IN` 全取回来 —— 数据量小、代码也更短。
    """
    ch_ids = {k.chapter_id for k in kps if k.chapter_id}
    sec_ids = {k.section_id for k in kps if k.section_id}
    mat_ids = {k.material_id for k in kps if k.material_id}
    chapters = (
        {c.id: c for c in db.scalars(select(Chapter).where(Chapter.id.in_(ch_ids)))} if ch_ids else {}
    )
    sections = (
        {s.id: s for s in db.scalars(select(Section).where(Section.id.in_(sec_ids)))} if sec_ids else {}
    )
    materials = (
        {m.id: m for m in db.scalars(select(Material).where(Material.id.in_(mat_ids)))}
        if mat_ids
        else {}
    )
    return chapters, sections, materials


def _load_counts(db: Session, kp_ids: list[str]) -> dict[str, dict[str, int]]:
    """批量算每个知识点的三类计数（前置 / 例题 / 误区）。同样避免 N+1。"""
    out: dict[str, dict[str, int]] = {
        k: {"prereq": 0, "example": 0, "misconception": 0} for k in kp_ids
    }
    if not kp_ids:
        return out

    for col, key in (
        (KpPrerequisite.kp_id, "prereq"),
        (KpExample.kp_id, "example"),
        (KpMisconception.kp_id, "misconception"),
    ):
        rows = db.execute(
            select(col, func.count()).where(col.in_(kp_ids)).group_by(col)
        ).all()
        for kp_id, n in rows:
            out[kp_id][key] = n
    return out


def _to_kp_item(
    kp: KnowledgePoint,
    chapters: dict,
    sections: dict,
    materials: dict,
    counts: dict[str, dict[str, int]],
) -> KpItemOut:
    """知识点行 → 列表项。**`source` 里必须有 quote**（A2-3 溯源覆盖率 100%）。"""
    ch = chapters.get(kp.chapter_id)
    sec = sections.get(kp.section_id)
    mat = materials.get(kp.material_id)
    c = counts.get(kp.id, {"prereq": 0, "example": 0, "misconception": 0})

    return KpItemOut(
        id=kp.id,
        name=kp.name,
        summary_md=kp.summary_md or "",
        difficulty=kp.difficulty,
        difficulty_reason=kp.difficulty_reason,
        kp_type=kp.kp_type,
        chapter=ChapterRefOut(
            id=kp.chapter_id,
            number=(ch.number if ch else None),
            title=(ch.title if ch else ""),
        ),
        section=SectionRefOut(
            id=kp.section_id,
            number=(sec.number if sec else None),
            title=(sec.title if sec else ""),
        ),
        source=SourceRefOut(
            material_id=kp.source_material_id or kp.material_id,
            material_name=(mat.filename if mat else ""),
            page=kp.source_page,
            block_id=kp.source_block_id,
            quote=kp.source_quote or "",
        ),
        prerequisite_count=c["prereq"],
        example_count=c["example"],
        misconception_count=c["misconception"],
        needs_review=bool(kp.needs_review),
        confidence=float(kp.confidence) if kp.confidence is not None else None,
    )


def _to_kp_detail(db: Session, kp: KnowledgePoint) -> KpDetailOut:
    """知识点行 → 详情（列表项 + 前置边 + 例题 + 误区）。"""
    chapters, sections, materials = _load_refs(db, [kp])
    base = _to_kp_item(kp, chapters, sections, materials, _load_counts(db, [kp.id]))

    edges = db.scalars(
        select(KpPrerequisite).where(KpPrerequisite.kp_id == kp.id)
    ).all()
    prereq_ids = [e.prereq_kp_id for e in edges]
    names = (
        dict(
            db.execute(
                select(KnowledgePoint.id, KnowledgePoint.name).where(
                    KnowledgePoint.id.in_(prereq_ids)
                )
            ).all()
        )
        if prereq_ids
        else {}
    )

    examples = db.scalars(
        select(KpExample).where(KpExample.kp_id == kp.id).order_by(KpExample.seq)
    ).all()
    misconceptions = db.scalars(
        select(KpMisconception).where(KpMisconception.kp_id == kp.id)
    ).all()

    return KpDetailOut(
        **base.model_dump(),
        prerequisites=[
            PrerequisiteOut(
                kp_id=e.prereq_kp_id,
                name=names.get(e.prereq_kp_id, ""),
                relation_type=e.relation_type,
                reason=e.reason or "",
                confidence=float(e.confidence) if e.confidence is not None else None,
            )
            for e in edges
            if not e.pruned
        ],
        examples=[
            ExampleOut(
                id=x.id,
                question_type=x.question_type,
                stem_md=x.stem_md,
                options_json=x.options_json,
                answer_md=x.answer_md,
                analysis_md=x.analysis_md,
                difficulty=x.difficulty,
                source_page=x.source_page,
            )
            for x in examples
        ],
        misconceptions=[
            MisconceptionOut(
                id=m.id,
                description=m.description,
                cause=m.cause,
                remedy=m.remedy,
                source=m.source,
                confidence=float(m.confidence) if m.confidence is not None else None,
            )
            for m in misconceptions
        ],
    )



# ---------------------------------------------------------------------------
# 端点 14：知识点列表
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-points",
    response_model=Envelope[PageData[KpItemOut]],
    summary="知识点查询",
    description=(
        "支持按章节 / 难度区间 / 类型 / 待核实 / 关键词过滤。\n\n"
        "`needs_review` 为**布尔**（api-spec v1.3 统一），不传即不过滤；"
        "`difficulty_min > difficulty_max` 返回 400。"
    ),
)
def list_knowledge_points(
    db: DbSession,
    page: PageDep,
    material_id: Annotated[str | None, Query()] = None,
    chapter_id: Annotated[str | None, Query()] = None,
    section_id: Annotated[str | None, Query()] = None,
    difficulty_min: Annotated[int | None, Query(ge=1, le=5)] = None,
    difficulty_max: Annotated[int | None, Query(ge=1, le=5)] = None,
    kp_type: Annotated[str | None, Query()] = None,
    needs_review: StrictBoolDep = None,
    q: Annotated[str | None, Query(description="关键词全文检索")] = None,
) -> Envelope[PageData[KpItemOut]]:
    if (
        difficulty_min is not None
        and difficulty_max is not None
        and difficulty_min > difficulty_max
    ):
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            f"难度区间不合法：min={difficulty_min} 大于 max={difficulty_max}",
        )
    if kp_type is not None and kp_type not in KP_TYPES:
        raise ApiError(
            ErrorCode.INVALID_PARAM, f"kp_type 取值不合法：{kp_type}", {"allowed": list(KP_TYPES)}
        )
    for name, value in (
        ("material_id", material_id),
        ("chapter_id", chapter_id),
        ("section_id", section_id),
    ):
        if value is not None and not value:
            raise ApiError(ErrorCode.INVALID_PARAM, f"{name} 不能为空字符串")

    # ⚠️ 这里原来只实现了 `needs_review` 与 `kp_type` 两个过滤，
    #    **`material_id` / `chapter_id` / `section_id` / 难度区间 / 关键词全被静默忽略** ——
    #    也就是说传了 `?material_id=mat_x` 依然会返回别的材料的知识点，
    #    而**调用方以为筛过了**。这是最典型的一类"不报错的错"，现在全部落实。
    stmt = select(KnowledgePoint)
    if material_id is not None:
        stmt = stmt.where(KnowledgePoint.material_id == material_id)
    if chapter_id is not None:
        stmt = stmt.where(KnowledgePoint.chapter_id == chapter_id)
    if section_id is not None:
        stmt = stmt.where(KnowledgePoint.section_id == section_id)
    if difficulty_min is not None:
        stmt = stmt.where(KnowledgePoint.difficulty >= difficulty_min)
    if difficulty_max is not None:
        stmt = stmt.where(KnowledgePoint.difficulty <= difficulty_max)
    if kp_type is not None:
        stmt = stmt.where(KnowledgePoint.kp_type == kp_type)
    if needs_review is not None:
        stmt = stmt.where(KnowledgePoint.needs_review == (1 if needs_review else 0))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(KnowledgePoint.name.like(like), KnowledgePoint.summary_md.like(like))
        )

    # 计数用独立的 count 查询（**不要把整表拉回来数**，那在千级知识点上是白拉）
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(KnowledgePoint.seq).offset(page.offset).limit(page.limit)).all()

    chapters, sections, materials = _load_refs(db, list(rows))
    counts = _load_counts(db, [k.id for k in rows])
    items = [_to_kp_item(k, chapters, sections, materials, counts) for k in rows]
    return ok(PageData.of(items=items, total=total, params=page))


# ---------------------------------------------------------------------------
# 端点 15：知识点详情
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-points/{kp_id}",
    response_model=Envelope[KpDetailOut],
    summary="知识点详情",
    description=(
        "在列表项结构上追加三段：前置依赖 / 典型例题 / 常见误区。\n\n"
        "`prerequisites[].reason` **必须来自依赖边上的 reason** —— "
        "「为什么这个要排在前面」要能逐条说清，不是黑盒拓扑排序。"
    ),
)
def get_knowledge_point(kp_id: str, db: DbSession) -> Envelope[KpDetailOut]:
    kp = _require_kp(kp_id, db)
    return ok(_to_kp_detail(db, kp))


# ---------------------------------------------------------------------------
# 端点 28：卡点根因回溯
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-points/{kp_id}/gap-analysis",
    response_model=Envelope[GapAnalysisOut],
    summary="卡点根因回溯",
    description=(
        "沿 `hard` 边反向可达，返回全部硬前置与「最可能的断层」。\n\n"
        "`student_evidence` 是**可重复查询参数**，传 `kp_misconceptions.id`；"
        "**无效值忽略而不报错** —— 它只影响排序精度，不该让整个请求失败（api-spec v1.3）。"
    ),
)
def gap_analysis(
    kp_id: str,
    db: DbSession,
    student_evidence: Annotated[
        list[str] | None, Query(description="本轮暴露的误区 id，可重复传入")
    ] = None,
) -> Envelope[GapAnalysisOut]:
    kp = _require_kp(kp_id, db)
    evidence = student_evidence or []

    # ★ 真算：沿 hard 边反向可达 + 按「命中误区 / 距目标层数 / 被依赖数」排序
    #    （算法在 graph_infer，不重写 —— 那是已实测通过的实现）
    graph, kp_rows, _, _ = load_graph(db)
    by_id = {k.id: k for k in kp_rows}

    result = run_gap_analysis(graph, kp_id, misconception_hits=evidence)

    # ⚠️ 目标没有 hard 前置是**正常情况**，不是错误：它本身就是起点知识点，
    #    卡点就在它自身。所以如实返回空前置 + 那句建议，而不是报错或编一个断层。
    candidates = result.get("candidates") or []
    top = result.get("likely_gap")

    def _name(kid: str) -> str:
        row = by_id.get(kid)
        return row.name if row else ""

    likely = None
    if top is not None:
        gap_kp_id = top["knowledge_point"]
        gap_kp = by_id.get(gap_kp_id)
        likely = LikelyGapOut(
            kp_id=gap_kp_id,
            name=_name(gap_kp_id),
            # evidence 用算法给出的「为什么是它」逐条拼起来 ——
            # 这样「最可能断层」是可解释的，不是一句模棱两可的结论。
            evidence="；".join(result.get("why") or []) or "该前置是目标最近的硬前置",
            source=GapSourceOut(
                material_id=(gap_kp.material_id if gap_kp else kp.material_id),
                page=(gap_kp.source_page if gap_kp else None),
            ),
        )

    return ok(
        GapAnalysisOut(
            target_kp=KpBriefOut(kp_id=kp.id, name=kp.name),
            hard_prerequisites=[
                HardPrereqOut(
                    kp_id=c["knowledge_point"],
                    name=_name(c["knowledge_point"]),
                    depth=c.get("breadth_from_target") or 1,
                    reason=(
                        "本轮回答命中了它的常见误区"
                        if c.get("misconception_hit")
                        else f"它是目标的硬前置，且被 {c.get('depended_by_count', 0)} 个知识点依赖"
                    ),
                )
                for c in candidates
            ],
            likely_gap=likely,
            suggestion=result.get("message") or "未发现明显断层，建议回到目标知识点本身复习。",
        )
    )

def _require_kp(kp_id: str, db: Session) -> KnowledgePoint:
    """知识点存在性校验。**一律真查库** —— 查不到就 404。

    原来 mock 模式下只做格式校验（`startswith("kp_")`）就返回，
    于是**任何 kp_ 开头的胡乱 id 都会返回一份"完整"的知识点**。
    那种假成功比 404 难查得多：界面有内容、调用方以为对了。
    """
    if not kp_id.startswith("kp_"):
        raise ApiError(ErrorCode.NOT_FOUND, f"知识点 {kp_id} 不存在（id 应以 kp_ 开头）")
    kp = db.get(KnowledgePoint, kp_id)
    if kp is None:
        raise ApiError(ErrorCode.NOT_FOUND, f"知识点 {kp_id} 不存在")
    return kp
