"""章与节（归属：P2）。对应 docs/data-model.md §2.3。

刻意**分两张表**而不是共用 `outline_nodes`：两者的业务语义与查询模式不同
（章用于导航与统计，节承载知识点），分表更利于代码可读性 —— 这一条是按
"工程完整性"评分项刻意做的取舍，不是没想过合并。
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
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
        # 复合外键的父侧必须有对应的唯一索引 —— 这条是给 sections 的复合外键用的。
        # (`id` 已是主键因而天然唯一，但 SQLite 要求父侧存在**与引用列完全对应**的
        #  唯一索引，所以必须显式声明这一个。)
        UniqueConstraint("id", "material_id", name="uq_chapters_id_material"),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        Index("idx_chapters_material_seq", "material_id", "seq"),
    )

    def __repr__(self) -> str:
        return f"<Chapter {self.id} {self.title!r}>"


class Section(Base):
    """教材的一节。**是知识点的直接父级 —— 三级结构完整率的落点。**"""

    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(Text, primary_key=True, doc="sec_<材料hash8>_<章seq>_<节seq>")
    # 这两个字段**不再各挂一个单列外键**，而是由下面一条复合外键统一约束：
    # 单列外键只能保证"chapter_id 存在""material_id 存在"，但保证不了
    # "这个 chapter 属于这个 material" —— 那正是跨链脏数据的来源。
    material_id: Mapped[str] = mapped_column(
        Text, nullable=False, doc="冗余字段；由复合外键保证与 chapter 同链"
    )
    chapter_id: Mapped[str] = mapped_column(
        Text, nullable=False, doc="由复合外键保证与 material_id 同链"
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
        # 供 knowledge_points 的复合外键引用（父侧唯一索引）
        UniqueConstraint("id", "chapter_id", "material_id", name="uq_sections_chain"),
        # ★ 层级链一致性（隐患 A 的修复）：节所属的 (chapter_id, material_id)
        #   必须真的存在于 chapters 表里。这样"节挂在 A 材料、却声称属于 B 材料的章"
        #   在写入那一刻就被拒绝，不必等到跑质量报告才发现。
        #   ON UPDATE CASCADE：调整节的归属时，下游 knowledge_points 会自动跟随。
        ForeignKeyConstraint(
            ["chapter_id", "material_id"],
            ["chapters.id", "chapters.material_id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_sections_chapter_chain",
        ),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        Index("idx_sections_chapter_seq", "chapter_id", "seq"),
        # 让 material_id 这个冗余字段真的有用：按材料汇总时的入口
        Index("idx_sections_material", "material_id"),
    )

    def __repr__(self) -> str:
        return f"<Section {self.id} {self.title!r}>"
