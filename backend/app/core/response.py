"""统一响应包封（归属：P2，三人共用）。

为什么要泛型模型 + helper，而不是中间件
----------------------------------------
中间件包封写起来最省事，但它会让 OpenAPI 里的 `response_model` 和**实际返回结构**对不上——
P3 在 `/docs` 里看到的就不是真实形态，"接口冻结"于是变成假的。

这里改用 `Envelope[T]` 泛型 + `ok()` helper：路由声明 `response_model=Envelope[XXX]`，
FastAPI 能正确生成 schema，P3 在 `/docs` 里看到的就是最终形态。

对应规格：docs/api-spec.md §1.1
"""

from __future__ import annotations

import contextvars
import uuid
from typing import Any, Generic, TypeVar

from fastapi import Response
from pydantic import BaseModel, Field

T = TypeVar("T")

REQUEST_ID_HEADER = "X-Request-ID"

# 由中间件写入、由 ok()/fail() 读取，避免把 Request 对象穿到每个路由签名里。
# Starlette 的 run_in_threadpool 会传播 contextvars，同步路由里也能读到。
_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def new_request_id() -> str:
    """生成形如 `req_8f21a3c4` 的请求标识（规格示例为 `req_8f21`）。"""
    return f"req_{uuid.uuid4().hex[:8]}"


def set_request_id(value: str) -> None:
    _request_id_ctx.set(value)


def current_request_id() -> str:
    """取当前请求的 request_id；不在请求上下文里时现生成一个。"""
    return _request_id_ctx.get() or new_request_id()


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------


class Envelope(BaseModel, Generic[T]):
    """成功响应包封：`{ ok: true, data: ..., request_id: ... }`。"""

    ok: bool = Field(default=True, description="固定为 true")
    data: T = Field(description="业务数据")
    request_id: str = Field(description="请求标识，排查问题时报这个值")


class ErrorDetail(BaseModel):
    code: str = Field(description="错误码，见 docs/api-spec.md §1.2")
    message: str = Field(description="可直接展示给用户的中文说明")
    detail: dict[str, Any] | None = Field(default=None, description="附加信息，可为空")


class ErrorEnvelope(BaseModel):
    """失败响应包封：`{ ok: false, error: {...}, request_id: ... }`。"""

    ok: bool = Field(default=False, description="固定为 false")
    error: ErrorDetail
    request_id: str


# 分页相关模型（`PageData` / `PageParams`）已移到 `app/core/pagination.py` ——
# 分页的参数校验与响应体放在一起更内聚，避免"改了一处忘了另一处"。


def text_response(content: str, media_type: str) -> Response:
    """构造**非 JSON 响应**（markdown / CSV）。

    约定（docs/api-spec.md §1.1 的非 JSON 例外条款）：
      · 成功时直接返回原始内容，**请求标识走 `X-Request-ID` 响应头**；
      · 失败时仍由全局异常处理器返回 JSON 包封 —— 这样前端只需要一套错误处理逻辑，
        不用为"下载接口报错"再写一个分支。
    """
    return Response(
        content=content,
        media_type=media_type,
        headers={REQUEST_ID_HEADER: current_request_id()},
    )


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------


def ok(data: T, request_id: str | None = None) -> Envelope[T]:
    """构造成功响应。路由里直接 `return ok(payload)` 即可。"""
    return Envelope[T](ok=True, data=data, request_id=request_id or current_request_id())


def fail(
    code: str,
    message: str,
    detail: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> ErrorEnvelope:
    """构造失败响应。

    ⚠️ `message` 必须是**能直接展示给用户的中文**，不允许出现英文堆栈或裸错误码——
    这是 docs/api-spec.md §1.1 的硬规则，也是用户体验评分项。
    """
    return ErrorEnvelope(
        ok=False,
        error=ErrorDetail(code=code, message=message, detail=detail),
        request_id=request_id or current_request_id(),
    )
