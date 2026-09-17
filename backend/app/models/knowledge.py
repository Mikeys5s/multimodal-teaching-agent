"""知识点与前置依赖边（归属：P2）。对应 docs/data-model.md §2.4 / §2.5。

⚠️ 本文件是**本项目主创新点的载体**（SPEC §1.5）：
`kp_prerequisites` 不是普通的关联表，它决定了
「依赖图能否无环」（B1-2）、「边理由是否完备」（B1-5）、
「结构-语义冲突是否被显式暴露」（B1-4）三项验收。

所以下面几个字段**不能为了好写而放宽**：
  · `reason`            —— NOT NULL，B1-5 的载体
  · `pruned`            —— 软删除标记，是"系统发现并处理了矛盾"的证据
  · `needs_review`      —— 冲突不静默采纳的落点
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models._common import KP_TYPES, RELATION_TYPES, SOURCE_CHANNELS, sql_in
from app.models.outline import Section


class KnowledgePoint(Base):
    """一个知识点。三级结构（章—节—知识点）的叶子，也是最低层级的承载单位。"""

    __tablename__ = "knowledge_points"

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, doc="kp_<材料hash8>_<章seq>_<节seq>_<节内seq:03d>"
    )

    # ---- 层级：三个字段都是 NOT NULL ----
    # section_id 非空是"三级结构完整率 100%"（A2-1）的数据库层保证：
    # 宁可写入失败，也不允许出现挂在节外面的裸知识点。
    section_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sections.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        doc="冗余字段，便于按章查询",
    )
    material_id: Mapped[str] = mapped_column(
        Text, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, doc="冗余字段"
    )

    # ---- 内容 ----
    name: Mapped[str] = mapped_column(Text, nullable=False)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False, doc="一句话讲清楚「这是什么」")
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, doc="1–5")
    difficulty_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="为什么是这个难度（难度判定的可解释性）"
    )
    kp_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'concept'"))

    # ---- 溯源：source_quote 非空是 A2-3 溯源覆盖率 100% 的数据库层保证 ----
    source_material_id: Mapped[str] = mapped_column(
        Text, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_block_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("material_blocks.id", ondelete="SET NULL"), nullable=True
    )
    source_quote: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="原文片段。空值视为抽取失败，不得入库（须落到 needs_review 待人工处置）",
    )

    # ---- 质量 ----
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_review: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), doc="待核实标记；缺失字段或低置信度置 1"
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, doc="节内顺序，从 0 开始")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    section: Mapped[Section] = relationship(back_populates="knowledge_points")

    __table_args__ = (
        # 同一节内不允许重名 —— 否则依赖边会指向"哪个重名的？"，无法解释
        UniqueConstraint("section_id", "name", name="uq_kp_section_name"),
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
        CheckConstraint(f"kp_type IN ({sql_in(KP_TYPES)})", name="kp_type"),
        CheckConstraint("needs_review IN (0, 1)", name="needs_review_boolean"),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        CheckConstraint("length(trim(source_quote)) > 0", name="source_quote_not_blank"),
        Index("idx_kp_section", "section_id", "seq"),
        Index("idx_kp_difficulty", "difficulty"),
        Index("idx_kp_review", "needs_review"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgePoint {self.id} {self.name!r}>"


class KpPrerequisite(Base):
    """前置依赖边：`prereq_kp_id` 是前置，`kp_id` 是后置（"要学会 kp 得先会 prereq"）。

    边的语义继承自 Marble 的 hard/soft 二分；我们额外加了
    **边级原文溯源**（`evidence_quote`）与 **DAG 环校验剪枝记录**（`pruned`）。
    """

    __tablename__ = "kp_prerequisites"

    kp_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        primary_key=True,
        doc="后置方（要学会的那个）",
    )
    prereq_kp_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        primary_key=True,
        doc="前置方（得先会的那个）",
    )

    relation_type: Mapped[str] = mapped_column(
        Text, nullable=False, doc="hard=不会就学不动；soft=会了更好懂"
    )
    reason: Mapped[str] = mapped_column(
        Text, nullable=False, doc="依赖理由，写清「不学懂前置会卡在哪」。B1-5 要求 100% 完备"
    )
    evidence_quote: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="材料原文中支持这条依赖的片段（边级溯源）"
    )
    source_channel: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'semantic'"),
        doc="structure / semantic / both —— 这条边由哪条线索产生（双通道融合）",
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True, doc="融合后的置信度")

    needs_review: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        doc="★ 结构-语义冲突标记：语义判定与章节顺序矛盾时置 1（B1-4）。冲突不静默采纳",
    )
    pruned: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        doc="★ 是否因 DAG 环校验被剪除。**软删除**：被剪的边保留记录，"
        "它是「系统发现并处理了矛盾」的证据，比只报「环数 0」更有说服力",
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(f"relation_type IN ({sql_in(RELATION_TYPES)})", name="relation_type"),
        CheckConstraint(f"source_channel IN ({sql_in(SOURCE_CHANNELS)})", name="source_channel"),
        # 禁自环：自己依赖自己不是"教学依赖"，是抽取错误
        CheckConstraint("kp_id != prereq_kp_id", name="no_self_loop"),
        CheckConstraint("needs_review IN (0, 1)", name="needs_review_boolean"),
        CheckConstraint("pruned IN (0, 1)", name="pruned_boolean"),
        CheckConstraint("length(trim(reason)) > 0", name="reason_not_blank"),
        Index("idx_edges_prereq", "prereq_kp_id"),
        Index("idx_edges_pruned", "pruned"),
        Index("idx_edges_review", "needs_review"),
    )

    def __repr__(self) -> str:
        flag = " [pruned]" if self.pruned else ""
        return f"<KpPrerequisite {self.prereq_kp_id} -> {self.kp_id} ({self.relation_type}){flag}>"
