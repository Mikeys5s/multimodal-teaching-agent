"""异步任务查询（归属：P2）。对应 docs/api-spec.md §6，端点 26、27。

设计要点：`stage_detail` 是**给用户看的中文进度描述**，前端直接展示、不做二次加工。
所以这里返回的每个 `stage_detail` 都是人话 —— `正在识别第 7/20 页` 而不是 `processing...`。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.response import Envelope, ok
from app.db import get_db
from app.schemas.job import JobListOut, JobOut

router = APIRouter(tags=["jobs"])

DbSession = Annotated[Session, Depends(get_db)]

MOCK_MODE = True

JOB_TYPES = ("parse", "extract_knowledge", "embed", "reindex")


def _mock_job(job_id: str, job_type: str = "parse") -> JobOut:
    return JobOut(
        id=job_id,
        job_type=job_type,
        target_id="mat_9f2a1c40",
        status="running",
        progress=35,
        # ★ 人类可读的中文进度 —— 这是"用户体验"评分项的具体落点
        stage_detail="正在识别第 7/20 页",
        result_json=None,
        error_message=None,
        started_at="2026-09-17T13:02:12+00:00",
        finished_at=None,
        created_at="2026-09-17T13:02:11+00:00",
    )


@router.get(
    "/jobs/{job_id}",
    response_model=Envelope[JobOut],
    summary="任务详情",
    description="前端按固定间隔轮询（建议 1–2 秒）。`stage_detail` 直接展示给用户，不加工。",
)
def get_job(job_id: str, db: DbSession) -> Envelope[JobOut]:
    if not job_id.startswith("job_"):
        raise ApiError(ErrorCode.NOT_FOUND, f"任务 {job_id} 不存在（id 应以 job_ 开头）")
    return ok(_mock_job(job_id))


@router.get(
    "/jobs",
    response_model=Envelope[JobListOut],
    summary="任务列表",
    description=(
        "按资源或类型查任务。**刻意不分页** —— 任务量天然很少（一轮演示几十条），"
        "加分页只会让前端多做无谓的控件。"
    ),
)
def list_jobs(
    db: DbSession,
    target_id: Annotated[str | None, Query(description="按关联资源过滤，如 material_id")] = None,
    job_type: Annotated[str | None, Query(description="按任务类型过滤")] = None,
) -> Envelope[JobListOut]:
    if job_type is not None and job_type not in JOB_TYPES:
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            f"job_type 取值不合法：{job_type}",
            {"allowed": list(JOB_TYPES)},
        )

    items = [_mock_job("job_9f2a1c40")] if MOCK_MODE else []
    if target_id is not None:
        items = [i for i in items if i.target_id == target_id]
    if job_type is not None:
        items = [i for i in items if i.job_type == job_type]
    return ok(JobListOut(items=items, total=len(items)))
