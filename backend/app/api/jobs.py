"""异步任务查询（归属：P2）。对应 docs/api-spec.md §6，端点 26、27。

设计要点：`stage_detail` 是**给用户看的中文进度描述**，前端直接展示、不做二次加工。
所以这里返回的每个 `stage_detail` 都是人话 —— `正在识别第 7/20 页` 而不是 `processing...`。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.response import Envelope, ok
from app.db import get_db
from app.models import Job
from app.schemas.job import JobListOut, JobOut

router = APIRouter(tags=["jobs"])

DbSession = Annotated[Session, Depends(get_db)]

JOB_TYPES = ("parse", "extract_knowledge", "embed", "reindex")


def _to_job_out(row: Job) -> JobOut:
    """`jobs` 行 → 响应模型。**字段一一对应，不做任何加工。**

    ⚠️ 这里刻意不"顺手美化"：`result_json` 原样返回 JSON 字符串，
    **不替前端 `json.loads`**。契约里它本来就是 `str | null`（api-spec §6）——
    在这里解码等于**偷偷改了契约**：前端按文档写会拿到字符串、按实现写会拿到对象，
    而**两边都觉得自己是对的**。
    """
    return JobOut(
        id=row.id,
        job_type=row.job_type,
        target_id=row.target_id,
        status=row.status,
        progress=row.progress,
        stage_detail=row.stage_detail,
        result_json=row.result_json,
        error_message=row.error_message,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
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

    row = db.get(Job, job_id)
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, f"任务 {job_id} 不存在")
    return ok(_to_job_out(row))


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

    # 不分页（见端点说明），但**按创建时间倒序** —— 最近的任务在最前面，
    # 这是"任务列表"唯一有意义的排序。
    stmt = select(Job).order_by(Job.created_at.desc())
    if target_id is not None:
        stmt = stmt.where(Job.target_id == target_id)
    if job_type is not None:
        stmt = stmt.where(Job.job_type == job_type)

    rows = db.scalars(stmt).all()
    items = [_to_job_out(r) for r in rows]
    return ok(JobListOut(items=items, total=len(items)))
