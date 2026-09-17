"""错误码与全局异常处理（归属：P2，三人共用）。

错误码表严格取自 docs/api-spec.md §1.2，不自行发明新码；
需要新码时先改规格再改代码（SPEC §9.3「规格变更」）。
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.response import fail

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    """错误码 → HTTP 状态码的映射（docs/api-spec.md §1.2）。"""

    INVALID_PARAM = "INVALID_PARAM"  # 400 参数校验失败
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"  # 400 文件格式不在白名单
    FILE_TOO_LARGE = "FILE_TOO_LARGE"  # 400 超过 50MB
    NOT_FOUND = "NOT_FOUND"  # 404 资源不存在
    JOB_IN_PROGRESS = "JOB_IN_PROGRESS"  # 409 同一资源已有任务在跑
    LLM_SCHEMA_INVALID = "LLM_SCHEMA_INVALID"  # 422 结构化输出校验失败（已重试后）
    INTERNAL = "INTERNAL"  # 500 兜底
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"  # 503 模型服务不可用


STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.INVALID_PARAM: 400,
    ErrorCode.UNSUPPORTED_FORMAT: 400,
    ErrorCode.FILE_TOO_LARGE: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.JOB_IN_PROGRESS: 409,
    ErrorCode.LLM_SCHEMA_INVALID: 422,
    ErrorCode.INTERNAL: 500,
    ErrorCode.LLM_UNAVAILABLE: 503,
}

# 错误码 → 默认中文文案。
# message 必须能直接给用户看，所以这里写的是"人话"，不是技术描述。
DEFAULT_MESSAGE: dict[ErrorCode, str] = {
    ErrorCode.INVALID_PARAM: "请求参数不正确，请检查后重试",
    ErrorCode.UNSUPPORTED_FORMAT: "暂不支持该文件格式，请上传 PDF、Word、PPT 或图片",
    ErrorCode.FILE_TOO_LARGE: "文件超出大小限制，请压缩后再上传",
    ErrorCode.NOT_FOUND: "找不到请求的内容",
    ErrorCode.JOB_IN_PROGRESS: "该素材已有任务正在进行，请等待完成",
    ErrorCode.LLM_SCHEMA_INVALID: "结构化输出解析失败，请重试或转人工校验",
    ErrorCode.INTERNAL: "服务出现异常，请稍后重试",
    ErrorCode.LLM_UNAVAILABLE: "模型服务暂时不可用，请稍后重试",
}


class ApiError(Exception):
    """业务异常：抛出后由全局处理器统一转成 ErrorEnvelope。

    用法：
        raise ApiError(ErrorCode.UNSUPPORTED_FORMAT, "暂不支持 .pages 格式，请转为 PDF 或 DOCX")
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message or DEFAULT_MESSAGE[code]
        self.detail = detail
        self.status_code = STATUS_BY_CODE[code]
        super().__init__(self.message)


# HTTP 状态码 → 错误码（用于 FastAPI/Starlette 自己抛出的异常）
STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.INVALID_PARAM,
    403: ErrorCode.INVALID_PARAM,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.INVALID_PARAM,
    409: ErrorCode.JOB_IN_PROGRESS,
    422: ErrorCode.INVALID_PARAM,
    500: ErrorCode.INTERNAL,
    503: ErrorCode.LLM_UNAVAILABLE,
}

# 少数状态码需要比 DEFAULT_MESSAGE 更贴切的说法
STATUS_MESSAGE_OVERRIDE: dict[int, str] = {
    405: "该接口不支持这种请求方法",
}

# 框架自动生成的英文 detail —— 这些**不能**直接透给用户。
# 规格要求 error.message 必须是能展示的中文（docs/api-spec.md §1.1）。
_FRAMEWORK_EN_DETAILS = {
    "Not Found",
    "Method Not Allowed",
    "Internal Server Error",
    "Unprocessable Entity",
    "Bad Request",
    "Forbidden",
    "Unauthorized",
    "Conflict",
    "Service Unavailable",
}


def _message_for(exc: StarletteHTTPException, code: ErrorCode) -> str:
    """决定给用户看的中文文案。

    刻意区分两种情况：
      · 我们自己 `raise HTTPException(404, "素材不存在")` —— 中文，直接用
      · 框架自动抛的 `Not Found` —— 英文样板，必须换成中文
    否则就会出现 404 页面直接显示 "Not Found" 的情况，与规格冲突。
    """
    detail = exc.detail if isinstance(exc.detail, str) else ""
    if detail and detail not in _FRAMEWORK_EN_DETAILS:
        return detail
    return STATUS_MESSAGE_OVERRIDE.get(exc.status_code, DEFAULT_MESSAGE[code])


def _json(payload, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    """把三类异常统一收敛到 ErrorEnvelope，保证前端只需处理一种结构。"""

    @app.exception_handler(ApiError)
    async def _handle_api_error(_request: Request, exc: ApiError):
        return _json(fail(exc.code.value, exc.message, exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_request: Request, exc: RequestValidationError):
        # FastAPI 默认会吐英文的技术性错误，这里翻成人话，只保留字段定位信息
        fields = [
            {
                "field": ".".join(str(p) for p in err.get("loc", [])[1:]),
                "reason": err.get("msg", ""),
            }
            for err in exc.errors()
        ]
        return _json(
            fail(
                ErrorCode.INVALID_PARAM.value,
                DEFAULT_MESSAGE[ErrorCode.INVALID_PARAM],
                {"fields": fields},
            ),
            STATUS_BY_CODE[ErrorCode.INVALID_PARAM],
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(_request: Request, exc: StarletteHTTPException):
        code = STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL)
        return _json(fail(code.value, _message_for(exc, code)), exc.status_code)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception):
        # 兜底：对外只给一句人话，细节进日志——不要把堆栈泄露给前端
        logger.exception("未捕获异常 path=%s", request.url.path, exc_info=exc)
        return _json(
            fail(ErrorCode.INTERNAL.value, DEFAULT_MESSAGE[ErrorCode.INTERNAL]),
            STATUS_BY_CODE[ErrorCode.INTERNAL],
        )
