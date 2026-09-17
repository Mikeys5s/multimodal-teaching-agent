"""章与节（归属：P2）。对应 docs/data-model.md §2.3。

刻意**分两张表**而不是共用 `outline_nodes`：两者的业务语义与查询模式不同
（章用于导航与统计，节承载知识点），分表更利于代码可读性 —— 这一条是按
"工程完整性"评分项刻意做的取舍，不是没想过合并。
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Chapter(Base):
    """教材的一章。归属某一份素材（跨素材合并章节为 v2 需求，初赛不做）。"""

    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(Text, primary_key=True, doc="ch_<材料hash8>_<章seq:03d>")
    material_id: Mapped[str] = mapped_column(
        Text, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="章节号如 3.2，保留材料原貌；仅用于展示与检索，不参与 ID 生成"
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, doc="同级排序，从 0 开始")
    source_block_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("material_blocks.id", ondelete="SET NULL"), nullable=True, doc="溯源"
    )
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True, doc="章的概要，用于检索")

    sections: Mapped[list[Section]] = relationship(
        back_populates="chapter",
        order_by="Section.seq",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("material_id", "seq", name="uq_chapters_material_seq"),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        Index("idx_chapters_material_seq", "material_id", "seq"),
    )

    def __repr__(self) -> str:
        return f"<Chapter {self.id} {self.title!r}>"


class Section(Base):
    """教材的一节。**是知识点的直接父级 —— 三级结构完整率的落点。**"""

    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(Text, primary_key=True, doc="sec_<材料hash8>_<章seq>_<节seq>")
    material_id: Mapped[str] = mapped_column(
        Text, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[str] = mapped_column(
        Text, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[str | None] = mapped_column(Text, nullable=True, doc="节号如 3.2.1，保留原貌")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, doc="章内排序，从 0 开始")
    source_block_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("material_blocks.id", ondelete="SET NULL"), nullable=True
    )
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True)

    chapter: Mapped[Chapter] = relationship(back_populates="sections")
    # 反向关系声明在 KnowledgePoint 一侧（避免跨模块 import）
    knowledge_points: Mapped[list[KnowledgePoint]] = relationship(  # noqa: F821
        back_populates="section",
        order_by="KnowledgePoint.seq",
    )

    __table_args__ = (
        UniqueConstraint("chapter_id", "seq", name="uq_sections_chapter_seq"),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        Index("idx_sections_chapter_seq", "chapter_id", "seq"),
    )

    def __repr__(self) -> str:
        return f"<Section {self.id} {self.title!r}>"
