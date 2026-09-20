"""知识点读侧的共用构造器（归属：P2）。

## 为什么单独抽出来

「知识点列表」「知识点详情」「导出」三个端点要的是**同一份数据**，
只是**输出的形状不同**（列表项 / 带子表 / 扁平导出行）。

如果各写一遍会怎样：**三个地方各自 join 章/节/材料、各自算三类计数** ——
一处改了字段、另两处忘了，就会出现"列表页显示难度 3、导出里是 4"这种
**不报错、但两边不一致**的情况。这类问题查起来极其费时。

**所以数据装配只写一遍，形状转换各自写。**

## 两条性能纪律

- **章/节/材料名批量取**（一次 `IN`），不在循环里查库 —— 一页几十个知识点不能几十次往返
- **计数用 `count()` 查询**，不把整表拉回来数
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Chapter,
    KnowledgePoint,
    KpExample,
    KpMisconception,
    KpPrerequisite,
    Material,
    Section,
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


def load_refs(db: Session, kps: list[KnowledgePoint]) -> tuple[dict, dict, dict]:
    """批量取章 / 节 / 材料，**避免 N+1 查询**。"""
    ch_ids = {k.chapter_id for k in kps if k.chapter_id}
    sec_ids = {k.section_id for k in kps if k.section_id}
    mat_ids = {k.material_id for k in kps if k.material_id}
    chapters = (
        {c.id: c for c in db.scalars(select(Chapter).where(Chapter.id.in_(ch_ids)))}
        if ch_ids
        else {}
    )
    sections = (
        {s.id: s for s in db.scalars(select(Section).where(Section.id.in_(sec_ids)))}
        if sec_ids
        else {}
    )
    materials = (
        {m.id: m for m in db.scalars(select(Material).where(Material.id.in_(mat_ids)))}
        if mat_ids
        else {}
    )
    return chapters, sections, materials


def load_counts(db: Session, kp_ids: list[str]) -> dict[str, dict[str, int]]:
    """批量算每个知识点的三类计数（前置 / 例题 / 误区）。"""
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
        rows = db.execute(select(col, func.count()).where(col.in_(kp_ids)).group_by(col)).all()
        for kp_id, n in rows:
            out[kp_id][key] = n
    return out


def to_kp_item(
    kp: KnowledgePoint,
    chapters: dict,
    sections: dict,
    materials: dict,
    counts: dict[str, dict[str, int]],
) -> KpItemOut:
    """知识点行 → 列表项。**`source.quote` 必须有**（A2-3 溯源覆盖率 100%）。"""
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


def load_kp_items(db: Session, kps: list[KnowledgePoint]) -> list[KpItemOut]:
    """一批知识点行 → 列表项（含批量取引用与计数）。列表与导出都走它。"""
    chapters, sections, materials = load_refs(db, kps)
    counts = load_counts(db, [k.id for k in kps])
    return [to_kp_item(k, chapters, sections, materials, counts) for k in kps]


def to_kp_detail(db: Session, kp: KnowledgePoint) -> KpDetailOut:
    """知识点行 → 详情（列表项 + 前置边 + 例题 + 误区）。"""
    base = load_kp_items(db, [kp])[0]

    edges = db.scalars(select(KpPrerequisite).where(KpPrerequisite.kp_id == kp.id)).all()
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
