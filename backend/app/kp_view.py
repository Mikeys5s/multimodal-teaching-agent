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

import re  # 派生内容里要剥掉 summary_md 的 markdown 标题行

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


def _derive_examples(kp: KnowledgePoint, prereq_names: list[str]) -> list[dict]:
    """**派生**思考题 —— 用于「没有人工精选例题」的知识点。

    全库 629 个点里人工精选的只有 9 个。剩下的点如果显示「暂无例题」，
    演示与答辩时点开就是空的。而「不空」不一定要靠编内容 ——
    可以**从已有的确定性数据派生**：题干来自 `summary_md`（材料原文的摘要）。

    ⚠️ 派生内容一律标 `source="derived"`，前端单独分区、单独徽章，**
    不混进「人工精选」里冒充** —— 这是 §1.4「宁缺毋错」的直接要求。
    """
    out: list[dict] = []
    summary = (kp.summary_md or "").strip()
    if not summary:
        return out

    body = re.sub(r"^#+\s.*$", "", summary, flags=re.M).strip()
    if not body:
        return out
    short = body if len(body) <= 300 else body[:300].rstrip() + "…"

    out.append({
        "id": f"{kp.id}__derived_ex1",
        "question_type": "short_answer",
        "stem_md": f"材料里这样讲这个知识点：\n\n> {short}\n\n"
                   f"请用你自己的话说明「{kp.name}」到底在解决什么问题 —— "
                   f"并指出这段话里最关键的一个限定条件。",
        "options_json": None,
        "answer_md": f"要点来自材料原文：\n\n{short}",
        "analysis_md": "本题由原文摘要派生（非人工精选）。"
                       "若需要可判对错的硬题目，见本知识点的「人工精选」分区（如有）。",
        "difficulty": kp.difficulty,
        "source_page": None,
        "source": "derived",
    })

    if prereq_names:
        first = prereq_names[0]
        out.append({
            "id": f"{kp.id}__derived_ex2",
            "question_type": "short_answer",
            "stem_md": f"在学「{kp.name}」之前，材料把它排在「{first}」之后。\n\n"
                       f"请说明：如果不先掌握「{first}」，「{kp.name}」这里会在哪一步卡住？",
            "options_json": None,
            "answer_md": f"这是一道**先修检查题**：能说清「{first}」与「{kp.name}」的依赖关系，"
                         f"说明前置已具备；说不清则建议先回去补「{first}」。\n\n"
                         f"依赖依据见本知识点的「前置知识点」分区（带 relation_type 与理由）。",
            "analysis_md": "由「前置依赖边」派生（非人工精选）—— 用于自查前置是否吃透。",
            "difficulty": kp.difficulty,
            "source_page": None,
            "source": "derived",
        })
    return out


def _derive_misconceptions(kp: KnowledgePoint, hard_prereqs: list[tuple[str, str]]) -> list[dict]:
    """**派生**易错点 —— 同样只用于「没有人工误区」的点。

    ⚠️ `source` 用 `llm_inferred`（`MISCONCEPTION_SOURCES` 里已有的合法值，
    语义是「由系统推断、未经人工确认」）。**不新增枚举值** —— 那要动 CHECK 约束。
    """
    out: list[dict] = []
    if hard_prereqs:
        _pre_id, pre_name = hard_prereqs[0]
        out.append({
            "id": f"{kp.id}__derived_mc1",
            "description": f"跳过「{pre_name}」直接学「{kp.name}」—— "
                           f"结论记住了，但一问「为什么」就答不上来。",
            "cause": f"材料把「{pre_name}」排在前面是有原因的："
                     f"「{kp.name}」的论述里用到了前置的概念。"
                     f"没学过前置时，读得通字面，但建不起因果。",
            "remedy": f"先回去把「{pre_name}」的摘要读一遍，再回来看这个点 —— "
                      f"重点看它用到了前置的哪个性质。",
            "source": "llm_inferred",
            "confidence": 0.5,
        })
    out.append({
        "id": f"{kp.id}__derived_mc2",
        "description": "把摘要当成全部 —— 只记住了一段话，"
                       "说不清这个知识点的**适用条件**和**它不解决什么**。",
        "cause": "摘要是「压缩后的要点」，省掉的正是边界条件。"
                 "只读摘要会得到一个「什么场合都对」的印象，"
                 "而真实的协议/算法都有前提。",
        "remedy": "对照着问自己两个问题：① **什么情况下它不成立？** "
                  "② **它和相邻的知识点分工在哪？** 答不上就别急着往下学。",
        "source": "llm_inferred",
        "confidence": 0.4,
    })
    return out


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

    active_edges = [e for e in edges if not e.pruned]
    hard = [(e.prereq_kp_id, names.get(e.prereq_kp_id, ""))
            for e in active_edges if e.relation_type == "hard"]
    all_pre = [names.get(e.prereq_kp_id, "") for e in active_edges]
    all_pre = [n for n in all_pre if n]

    ex_rows: list[dict]
    if examples:
        ex_rows = [
            {
                "id": x.id, "question_type": x.question_type, "stem_md": x.stem_md,
                "options_json": x.options_json, "answer_md": x.answer_md,
                "analysis_md": x.analysis_md, "difficulty": x.difficulty,
                "source_page": x.source_page,
                "source": "human",
            }
            for x in examples
        ]
    else:
        ex_rows = _derive_examples(kp, all_pre)

    mc_rows: list[dict]
    if misconceptions:
        mc_rows = [
            {
                "id": m.id, "description": m.description, "cause": m.cause,
                "remedy": m.remedy, "source": m.source,
                "confidence": float(m.confidence) if m.confidence is not None else None,
            }
            for m in misconceptions
        ]
    else:
        mc_rows = _derive_misconceptions(kp, hard)

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
        examples=[ExampleOut(**r) for r in ex_rows],
        misconceptions=[MisconceptionOut(**r) for r in mc_rows],
    )
