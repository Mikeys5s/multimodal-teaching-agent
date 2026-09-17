"""健康检查与元信息（归属：P2）。对应 docs/api-spec.md §2。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.core.response import Envelope, ok
from app.db import get_db, pragma_status
from app.schemas.meta import CapabilitiesOut, HealthOut

router = APIRouter(tags=["meta"])

# FastAPI 的推荐写法：依赖放 Annotated 里，而不是参数默认值
# （放默认值会触发 ruff B008，而且签名更啰嗦）
DbSession = Annotated[Session, Depends(get_db)]

# 支持的素材类型（与 SPEC §2.3 S1 一致；音频明确不支持，见 D-08）
SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".jpg", ".jpeg", ".png"]

PARSE_METHODS = {
    ".pdf": "文本层可用时走 PyMuPDF；扫描版走 PaddleOCR + 人工校对",
    ".docx": "python-docx 直接抽取",
    ".pptx": "python-pptx 抽取文本框与备注",
    ".jpg": "PaddleOCR 本地解析 + 人工校对",
    ".jpeg": "PaddleOCR 本地解析 + 人工校对",
    ".png": "PaddleOCR 本地解析 + 人工校对",
}


@router.get(
    "/health",
    response_model=Envelope[HealthOut],
    summary="健康检查",
    description="演示前自检用。返回服务、数据库与模型通道的状态。",
)
def health() -> Envelope[HealthOut]:
    """真实探测数据库连接，而不是返回一个写死的 ok。

    这么写有个实际好处：如果 `foreign_keys` 这类 pragma 没生效，
    打开这个接口就能看见，不用去读代码猜。
    """
    pragmas = pragma_status()
    db_state = (
        "ok" if "error" not in pragmas and pragmas else f"error:{pragmas.get('error', 'unknown')}"
    )
    overall = "ok" if db_state == "ok" else "degraded"

    return ok(
        HealthOut(
            status=overall,
            db=db_state,
            llm="not_in_use",  # 离线构建 + 在线零模型依赖（SPEC §4.8）
            version=settings.version,
        )
    )


@router.get(
    "/health/pragma",
    response_model=Envelope[dict],
    summary="SQLite pragma 自检",
    description="读回当前连接的实际 pragma 值。foreign_keys 必须为 1。",
    include_in_schema=True,
)
def health_pragma() -> Envelope[dict]:
    return ok({"pragmas": pragma_status(), "db_file": str(settings.db_file)})


@router.get(
    "/meta/capabilities",
    response_model=Envelope[CapabilitiesOut],
    summary="能力与限制",
    description="前端据此渲染上传提示，避免在前端硬编码支持格式与大小限制。",
)
def capabilities(_request: Request, _db: DbSession) -> Envelope[CapabilitiesOut]:
    return ok(
        CapabilitiesOut(
            supported_material_types=SUPPORTED_EXTENSIONS,
            max_upload_mb=settings.max_upload_mb,
            parse_methods=PARSE_METHODS,
        )
    )
