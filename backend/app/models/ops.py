"""运维类实体（归属：P2）。对应 docs/data-model.md §2.11 / §2.12。

`jobs.stage_detail` 是刻意设计的字段：**进度必须对用户可读**。
它是"用户体验 20%"里的具体得分点 —— 前端直接展示，不做二次加工。
所以它的写入约定是：**写中文，写具体，不写 `processing...`**。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import (
    JOB_STATUSES,
    JOB_TYPES,
    sql_in,
    utc_iso_check,
    utc_now_iso,
    utc_server_default,
)


class Job(Base):
    """异步任务。耗时操作一律"立即返回 job_id + 前端轮询"。"""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, doc="job_id，形如 job_x1")
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="关联资源 id（如 material_id）"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    stage_detail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="★ 当前阶段的人类可读中文描述，如「正在识别第 7/20 页」。前端直接展示，不加工",
    )
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True, doc="结果摘要 JSON")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 注意：created_at 在规格里标为可空，但它是任务排序的依据，
    # 建模时收紧为 NOT NULL + 默认值 —— 缺了它前端列表顺序不确定
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now_iso, server_default=utc_server_default()
    )

    __table_args__ = (
        CheckConstraint(f"job_type IN ({sql_in(JOB_TYPES)})", name="job_type"),
        CheckConstraint(f"status IN ({sql_in(JOB_STATUSES)})", name="status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress_range"),
        # started_at / finished_at 可为空（任务还没开始 / 还没结束），非空时必须是正确格式
        CheckConstraint(
            f"started_at IS NULL OR {utc_iso_check('started_at')}", name="started_at_utc_iso"
        ),
        CheckConstraint(
            f"finished_at IS NULL OR {utc_iso_check('finished_at')}",
            name="finished_at_utc_iso",
        ),
        CheckConstraint(utc_iso_check("created_at"), name="created_at_utc_iso"),
        # 前端轮询"这个素材当前有没有任务在跑"是最频繁的查询
        Index("idx_jobs_target", "target_id", "status"),
        Index("idx_jobs_status", "status"),
        Index("idx_jobs_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Job {self.id} {self.job_type} status={self.status} {self.progress}%>"


class LlmCall(Base):
    """LLM 调用日志（可观测性）。

    ⚠️ 当前架构下运行期不调用大模型（SPEC §4.8），本表主要服务于**构建期**在
    LearnBuddy 平台上的抽取记录与本地兜底通道。字段保留，不因"暂时用不上"而删 ——
    规则口径若变化，Provider 层一行配置就能切回。
    """

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    caller: Mapped[str] = mapped_column(Text, nullable=False, doc="调用来源，如 parse.image_to_md")
    prompt_version: Mapped[str] = mapped_column(
        Text, nullable=False, doc="Prompt 契约版本号，如 P2@v1"
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schema_valid: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="结构化输出是否通过校验"
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now_iso, server_default=utc_server_default()
    )

    __table_args__ = (
        CheckConstraint(
            "schema_valid IS NULL OR schema_valid IN (0, 1)", name="schema_valid_boolean"
        ),
        CheckConstraint("retry_count >= 0", name="retry_count_non_negative"),
        CheckConstraint(utc_iso_check("created_at"), name="created_at_utc_iso"),
        Index("idx_llm_calls_caller", "caller"),
        Index("idx_llm_calls_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<LlmCall {self.id} {self.caller} {self.provider}/{self.model}>"
