"""知识点的附属实体（归属：P2）。对应 docs/data-model.md §2.6 / §2.7 / §2.8。

例题目、常见误区、向量三张表都直接挂在知识点上，用于知识点详情页与答疑提示语生成。
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import (
    MISCONCEPTION_SOURCES,
    QUESTION_TYPES,
    sql_in,
    utc_iso_check,
    utc_now_iso,
    utc_server_default,
)


class KpExample(Base):
    """归属于某知识点的典型例题（是精选后的，区别于 `questions` 的原始抽取题）。"""

    __tablename__ = "kp_examples"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kp_id: Mapped[str] = mapped_column(
        Text, ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False
    )
    question_type: Mapped[str] = mapped_column(Text, nullable=False)
    stem_md: Mapped[str] = mapped_column(Text, nullable=False, doc="题干")
    options_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc='选项数组 JSON：[{"key":"A","content":"..."}]'
    )
    answer_md: Mapped[str] = mapped_column(Text, nullable=False, doc="答案")
    analysis_md: Mapped[str | None] = mapped_column(Text, nullable=True, doc="解析")
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True, doc="1–5")
    source_block_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("material_blocks.id", ondelete="SET NULL"), nullable=True
    )
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint(f"question_type IN ({sql_in(QUESTION_TYPES)})", name="question_type"),
        # difficulty 可为空（题目没标难度），非空时必须在 1–5
        CheckConstraint(
            "difficulty IS NULL OR difficulty BETWEEN 1 AND 5", name="difficulty_range"
        ),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        Index("idx_examples_kp", "kp_id", "seq"),
    )

    def __repr__(self) -> str:
        return f"<KpExample {self.id} type={self.question_type}>"


class KpMisconception(Base):
    """常见误区 —— **直接服务于答疑的提示语生成**。"""

    __tablename__ = "kp_misconceptions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kp_id: Mapped[str] = mapped_column(
        Text, ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, doc="学生的错误理解是什么")
    cause: Mapped[str | None] = mapped_column(Text, nullable=True, doc="为什么会这样错")
    remedy: Mapped[str | None] = mapped_column(Text, nullable=True, doc="怎么纠正")
    trigger_pattern: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="触发特征：学生这样问 / 这样答时命中该误区"
    )
    source: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="material / llm_inferred / human —— ★ 必须区分来源，LLM 推断的不得伪装成人类确认",
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"source IS NULL OR source IN ({sql_in(MISCONCEPTION_SOURCES)})", name="source"
        ),
        Index("idx_misconceptions_kp", "kp_id"),
        # 人工确认过的误区要能快速筛出来（用于验收举证）
        Index("idx_misconceptions_source", "source"),
    )

    def __repr__(self) -> str:
        return f"<KpMisconception {self.id} source={self.source}>"


class KpEmbedding(Base):
    """知识点向量。规模为千级，用 NumPy 暴力余弦即可，不引入向量数据库。"""

    __tablename__ = "kp_embeddings"

    kp_id: Mapped[str] = mapped_column(
        Text, ForeignKey("knowledge_points.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(Text, nullable=False, doc="embedding 模型标识")
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, doc="float32 小端连续数组，numpy.frombuffer 直接读"
    )
    text_hash: Mapped[str] = mapped_column(
        Text, nullable=False, doc="被向量化文本的 hash，用于判断是否需要重新生成"
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now_iso, server_default=utc_server_default()
    )

    __table_args__ = (
        # 向量长度必须与声明的维度自洽 —— 否则 numpy.frombuffer 会读出垃圾数据且不报错
        CheckConstraint("dim = length(vector) / 4", name="dim_matches_vector_length"),
        CheckConstraint("dim > 0", name="dim_positive"),
        CheckConstraint(utc_iso_check("created_at"), name="created_at_utc_iso"),
    )

    def __repr__(self) -> str:
        return f"<KpEmbedding {self.kp_id} model={self.model} dim={self.dim}>"
