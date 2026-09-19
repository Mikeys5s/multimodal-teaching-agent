"""异步任务的契约（归属：P2）。对应 docs/api-spec.md §6（端点 26、27）。

设计要点：`stage_detail` 是**给用户看的中文进度描述**，前端直接展示、不做二次加工。
所以它的契约是"必须是人话" —— `正在识别第 7/20 页` 而不是 `processing...`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobOut(BaseModel):
    """单个任务的状态（`GET /api/jobs/{job_id}`）。"""

    id: str
    job_type: str = Field(description="parse / extract_knowledge / embed / reindex")
    target_id: str | None = Field(default=None, description="关联资源 id，如 material_id")
    status: str = Field(description="queued / running / done / failed")
    progress: int = Field(ge=0, le=100, description="0–100")

    stage_detail: str | None = Field(
        default=None,
        description="★ 人类可读的中文进度描述，如「正在识别第 7/20 页」。前端直接展示，不加工",
    )
    result_json: str | None = Field(default=None, description="结果摘要 JSON 字符串")
    error_message: str | None = Field(default=None, description="失败原因，面向用户的中文文案")

    started_at: str | None = None
    finished_at: str | None = None
    created_at: str


class JobListOut(BaseModel):
    """`GET /api/jobs?target_id=&job_type=` 的响应体。

    刻意**不分页**：任务量天然很少（一轮演示几十条），加分页只会让前端多做无谓的控件。
    """

    items: list[JobOut] = Field(default_factory=list)
    total: int = 0
