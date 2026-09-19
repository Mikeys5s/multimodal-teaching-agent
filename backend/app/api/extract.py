"""抽取触发（归属：P2）。对应 docs/api-spec.md §4.1，端点 13。

## 实现口径：**已接真实业务**（D-22 的 mock 阶段结束）

本端点的校验重点是 **409 冲突**：同一批素材已有抽取任务在跑时不能重复触发。

另外两条**在受理阶段就该拦掉**（不要拖到后台任务里才失败）：
· 素材不存在 → 404
· **素材还没解析完成 → 400** —— 抽取的输入是解析产物，没解析就抽只会得到空结果
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.response import Envelope, ok
from app.db import engine, get_db
from app.models import Job, Material, utc_now_iso
from app.pipeline import run_extract_job

router = APIRouter(tags=["extract"])

DbSession = Annotated[Session, Depends(get_db)]


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
def extract_knowledge(
    payload: ExtractIn, db: DbSession, background: BackgroundTasks
) -> Envelope[ExtractAcceptedOut]:
    for mid in payload.material_ids:
        if not mid.startswith("mat_"):
            raise ApiError(ErrorCode.NOT_FOUND, f"素材 {mid} 不存在（id 应以 mat_ 开头）")
        mat = db.get(Material, mid)
        if mat is None:
            raise ApiError(ErrorCode.NOT_FOUND, f"素材 {mid} 不存在")
        # 抽取的输入是**解析产物**。没解析就抽，只会得到一个"素材里没有内容"的报错；
        # 与其让它在后台任务里失败，不如在受理时就明确告诉调用方缺什么。
        if mat.status not in ("done", "partial"):
            raise ApiError(
                ErrorCode.INVALID_PARAM,
                f"素材 {mid} 尚未解析完成（当前状态 {mat.status}），无法抽取知识点",
                {"material_id": mid, "status": mat.status},
            )

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

    # ---- 建**真任务**并触发抽取 ------------------------------------------
    #
    # ⚠️ 这里曾经返回一个写死的 `job_extract_0001` —— 它不对应任何真实任务，
    #    前端拿它轮询会**一直查不到**。端到端测试的"步骤4"就是钉这一条。
    now = utc_now_iso()
    digest = hashlib.sha1("|".join(sorted(payload.material_ids)).encode()).hexdigest()[:12]
    job_id = f"job_extract_{digest}"
    db.add(
        Job(
            id=job_id,
            job_type="extract_knowledge",
            target_id=payload.material_ids[0],
            status="queued",
            progress=0,
            stage_detail="排队中",
            created_at=now,
        )
    )
    db.commit()

    background.add_task(_run_extract_in_background, job_id, list(payload.material_ids))
    return ok(ExtractAcceptedOut(job_id=job_id, estimated_seconds=estimated))


def _run_extract_in_background(job_id: str, mat_ids: list[str]) -> None:
    """后台抽取任务入口。

    与解析任务同构：**自己开 session**（请求的 session 在响应返回时就关了），
    且**不吞异常**（失败已写进状态，异常继续上抛才能进日志）。
    """
    from app.db import Session as DbSessionFactory

    with DbSessionFactory(engine) as session:
        run_extract_job(session, job_id, mat_ids)
