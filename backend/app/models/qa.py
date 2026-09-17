"""题目与答疑（归属：P2）。对应 docs/data-model.md §2.9 / §2.10。

`questions` 是从材料里抽出来的**原始题目**（可能还没归属到知识点）；
`kp_examples` 是**归属于某知识点的典型例题**（精选后）。两者可有一对多关系。

`qa_turns` 的 `grounded` 字段是"幻觉率必须为 0"这条红线的载体：
**拒答轮次记为 0**，这样"接地率"才能被算出来并被评委检验。
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
from app.models._common import (
    QA_ROLES,
    QUESTION_TYPES,
    TURN_TYPES,
    sql_in,
    utc_iso_check,
    utc_now_iso,
    utc_server_default,
)


class Question(Base):
    """从材料中抽出的原始题目。`answer_missing=1` 对应 Stage 1 的"存疑处"。"""

    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    material_id: Mapped[str] = mapped_column(
        Text, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    source_block_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("material_blocks.id", ondelete="SET NULL"), nullable=True
    )
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_type: Mapped[str] = mapped_column(Text, nullable=False)
    stem_md: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_md: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="材料未给答案时为 NULL，并置 answer_missing=1"
    )
    answer_missing: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        doc="★ 对应 Stage 1 的「存疑处」，不伪装成完整数据",
    )
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    pk_kp_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("knowledge_points.id", ondelete="SET NULL"),
        nullable=True,
        doc="归属知识点，Stage 2 回填",
    )

    __table_args__ = (
        CheckConstraint(f"question_type IN ({sql_in(QUESTION_TYPES)})", name="question_type"),
        CheckConstraint("answer_missing IN (0, 1)", name="answer_missing_boolean"),
        # 缺答案与 answer_md 为空必须一致 —— 不允许"标了缺失却又有答案"这种自相矛盾
        CheckConstraint(
            "(answer_missing = 1 AND answer_md IS NULL)"
            " OR (answer_missing = 0 AND answer_md IS NOT NULL)",
            name="answer_missing_consistent",
        ),
        Index("idx_questions_material", "material_id"),
        Index("idx_questions_kp", "pk_kp_id"),
    )

    def __repr__(self) -> str:
        return f"<Question {self.id} type={self.question_type} missing={self.answer_missing}>"


class QaSession(Base):
    """一次答疑会话。初赛不做登录，用 `student_label` 作为演示标签。"""

    __tablename__ = "qa_sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_label: Mapped[str | None] = mapped_column(Text, nullable=True, doc="演示用标签，可空")
    material_scope: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", doc="答疑范围：JSON 数组；空数组 = 全部材料"
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now_iso, server_default=utc_server_default()
    )
    updated_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=utc_now_iso,
        onupdate=utc_now_iso,
        server_default=utc_server_default(),
    )

    turns: Mapped[list[QaTurn]] = relationship(
        back_populates="session", order_by="QaTurn.seq", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(utc_iso_check("created_at"), name="created_at_utc_iso"),
        CheckConstraint(utc_iso_check("updated_at"), name="updated_at_utc_iso"),
        Index("idx_qa_sessions_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<QaSession {self.id} label={self.student_label}>"


class QaTurn(Base):
    """一轮问答。既是聊天记录，也是状态机的持久化状态。"""

    __tablename__ = "qa_turns"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        Text, ForeignKey("qa_sessions.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, doc="轮次序号")
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    turn_type: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="苏格拉底状态机的对外可见状态；越界拒答为 refuse"
    )
    retrieved_kp_ids: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="本轮检索依据（知识点 id 的 JSON 数组）"
    )
    retrieved_block_ids: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="溯源到具体解析块（JSON 数组）"
    )
    grounded: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        doc="★ 是否基于材料作答，1/0。**拒答轮次记为 0** —— 「幻觉率必须为 0」这条红线的载体",
    )
    diagnosis_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="三件产出：涉及知识点 / 卡在哪一步 / 下一步练习"
    )
    llm_call_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("llm_calls.id", ondelete="SET NULL"), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now_iso, server_default=utc_server_default()
    )

    session: Mapped[QaSession] = relationship(back_populates="turns")

    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_turns_session_seq"),
        CheckConstraint(f"role IN ({sql_in(QA_ROLES)})", name="role"),
        CheckConstraint(
            f"turn_type IS NULL OR turn_type IN ({sql_in(TURN_TYPES)})", name="turn_type"
        ),
        CheckConstraint("grounded IN (0, 1)", name="grounded_boolean"),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        CheckConstraint(utc_iso_check("created_at"), name="created_at_utc_iso"),
        Index("idx_turns_session", "session_id", "seq"),
        # 接地率 / 拒答次数是质量报告的输入，要能快速聚合
        Index("idx_turns_grounded", "grounded"),
    )

    def __repr__(self) -> str:
        return f"<QaTurn {self.id} seq={self.seq} role={self.role} type={self.turn_type}>"
