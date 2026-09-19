"""抽取触发（归属：P2）。对应 docs/api-spec.md §4.1，端点 13。

⚠️ 这里同样遵循团队约定 D-22：**输入校验真实、业务数据 mock**。
本端点的校验重点是 **409 冲突**：同一批素材已有抽取任务在跑时不能重复触发 ——
这是"同一资源不并发跑两次抽取"的直接体现，也是 P3 需要处理的错误分支之一。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.response import Envelope, ok
from app.db import get_db
from app.models import Job, Material

router = APIRouter(tags=["extract"])

DbSession = Annotated[Session, Depends(get_db)]

# 与 materials.py 保持同一个开关口径
MOCK_MODE = True


class ExtractIn(BaseModel):
    """`POST /api/extract/knowledge` 的请求体。"""

    material_ids: list[str] = Field(min_length=1, description="要抽取的素材 id，至少一个")
    force: bool = Field(
        default=False, description="true = 忽略已有抽取结果强制重跑（会覆盖，慎用）"
    )


class ExtractAcceptedOut(BaseModel):
    """抽取任务已受理（202）。"""

    job_id: str
    estimated_seconds: int = Field(description="预估耗时，前端据此显示进度条量级")


@router.post(
    "/extract/knowledge",
    response_model=Envelope[ExtractAcceptedOut],
    status_code=202,
    summary="触发知识点抽取",
    description=(
        "异步任务，立即返回 `job_id` 供前端轮询。\n\n"
        "指定素材不存在 → 404；已有抽取任务在跑且未指定 `force` → **409 JOB_IN_PROGRESS**。"
    ),
)
def extract_knowledge(payload: ExtractIn, db: DbSession) -> Envelope[ExtractAcceptedOut]:
    for mid in payload.material_ids:
        if not mid.startswith("mat_"):
            raise ApiError(ErrorCode.NOT_FOUND, f"素材 {mid} 不存在（id 应以 mat_ 开头）")
        if not MOCK_MODE and db.get(Material, mid) is None:
            raise ApiError(ErrorCode.NOT_FOUND, f"素材 {mid} 不存在")

    if not payload.force:
        running = db.execute(
            select(Job.id).where(
                Job.job_type == "extract_knowledge",
                Job.target_id.in_(payload.material_ids),
                Job.status.in_(("queued", "running")),
            )
        ).first()
        if running is not None:
            raise ApiError(ErrorCode.JOB_IN_PROGRESS)

    # 素材数量越多预估越久；给出量级即可，前端不必精确
    estimated = 60 * len(payload.material_ids)
    return ok(ExtractAcceptedOut(job_id="job_extract_0001", estimated_seconds=estimated))
