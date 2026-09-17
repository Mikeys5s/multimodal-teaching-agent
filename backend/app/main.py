"""FastAPI 应用入口（归属：P2）。

用 `create_app()` 工厂 + 模块级 `app` 实例：
uvicorn 直接 `app.main:app` 能跑；测试里可以造独立实例，互不干扰。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import settings
from app.core.errors import register_exception_handlers
from app.core.response import REQUEST_ID_HEADER, new_request_id, set_request_id
from app.db import ensure_runtime_dirs

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """启动时确保运行期目录存在；退出时留一个明确的分界日志。"""
    ensure_runtime_dirs()
    logger.info("启动完成 | version=%s | db=%s", settings.version, settings.db_file)
    yield
    logger.info("服务已停止")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
        description=(
            "多模态教学智能体后端。\n\n"
            "**约定**：所有响应统一包封为 `{ok, data, request_id}` 或 "
            "`{ok, error:{code,message,detail}, request_id}`，见 `docs/api-spec.md` §1。\n\n"
            "**架构**：离线构建 + 在线零模型依赖 —— 运行期的检索、图算法、状态机 "
            "全部是确定性算法，不调用任何大模型。"
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # ---- request_id 注入 ----
    # 放中间件里，是为了让成功响应、错误响应、日志三处用的是同一个 id。
    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        rid = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
        set_request_id(rid)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = rid  # 报问题时把这个值发给我们即可定位
        return response

    # ---- CORS ----
    # 只在开发期开：生产环境是单容器同源部署（FastAPI 同时托管前端产物），不需要 CORS。
    if settings.debug:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.dev_frontend_origin],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[REQUEST_ID_HEADER],
        )

    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
