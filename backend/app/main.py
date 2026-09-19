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
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import settings
from app.core.errors import ApiError, ErrorCode, register_exception_handlers
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
    _mount_frontend(app)

    return app


# 前端产物缺失时，根路径给人的提示（而不是一个干巴巴的 404）。
_NO_FRONTEND_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>析知 XiZhi · 后端已就绪</title>
<style>
 body{font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif;max-width:42em;margin:12vh auto;padding:0 1.5em;color:#1f2328}
 code{background:#f0f1f3;padding:.15em .4em;border-radius:4px;font-size:.92em}
 .muted{color:#656d76}
</style></head><body>
<h1>析知 XiZhi · 后端已就绪</h1>
<p>API 正常，但**还没有前端产物**。当前是「只有后端」的状态。</p>
<ul>
  <li>接口文档：<a href="/docs"><code>/docs</code></a></li>
  <li>健康检查：<a href="/api/health"><code>/api/health</code></a></li>
  <li>数据自检：<a href="/api/report/quality"><code>/api/report/quality</code></a></li>
</ul>
<p class="muted">要看到完整界面，先构建前端：
<code>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</code>，
产物落到 <code>frontend/dist</code> 后重启服务即可。</p>
</body></html>
"""


def _reject_unknown_api_path(full_path: str) -> None:
    """★ 落到 catch-all 上的 `/api/**` 必须返回 **JSON 404**，不能返回页面。

    这是自测时抓到的一个真 bug：catch-all 是 `/{full_path:path}`，
    它会连带把**未注册的接口路径**也吃掉 —— 于是 `/api/nonexistent`
    返回的是 HTML。

    后果不是"少了个 404"，而是**前端调错接口时拿到 HTML**，
    然后在 `response.json()` 那一行炸掉，报一个跟真正原因毫无关系的错。
    我们的错误包封约定（`{ok:false, error:{...}}`）也就此被绕过。

    所以：非 `/api` 的路径才交给页面层处理，`/api` 的照旧走错误包封。
    """
    if full_path == "api" or full_path.startswith("api/"):
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"接口不存在：/{full_path}",
            {"hint": "接口清单见 /docs"},
        )


def _mount_frontend(app: FastAPI) -> None:
    """把前端构建产物挂到根路径 —— 单容器同源部署（SPEC §4.7）。

    ## 四个刻意的选择

    **① 产物不存在时不报错，而是给一句人话。**
    开发期、或前端还没构建时，根路径返回一段说明而不是 404 ——
    否则第一次跑起来的人会以为是路由坏了。后端本身照常提供 `/api`。

    **② 必须做 SPA 回退（catch-all → index.html）。**
    这是个容易漏的坑：`StaticFiles(html=True)` 只处理真实存在的文件，
    而 React Router 的 `/materials` 这类路径在磁盘上**没有对应文件**，
    直接刷新就会 404。所以兜底把未知路径交回 `index.html`，由前端路由接手。

    **③ catch-all 必须给 `/api/**` 让路。**
    否则未注册的接口路径会被页面吃掉，返回 HTML 而不是 JSON 404
    —— 见 `_reject_unknown_api_path()`。**这个 bug 是自测时抓到的。**

    **④ 挂载放在 `include_router` 之后。**
    FastAPI 按注册顺序匹配，`/{full_path:path}` 非常贪婪 ——
    放前面会把 `/api/**`、`/docs` 全吃掉。
    """
    dist = settings.frontend_dist_path
    index = dist / "index.html"

    if not index.is_file():
        # 用 catch-all 而不是只注册 `/` —— 让「没有前端」这个状态的表现和
        # 「有前端」一致：任何非接口路径都落到同一个页面上。
        # 只注册 `/` 的话，访问 `/materials` 会撞上一个 FastAPI 的裸 404 JSON，
        # 而那正是最容易被误会成"服务坏了"的样子。
        @app.get("/{full_path:path}", include_in_schema=False)
        def _no_frontend(full_path: str) -> HTMLResponse:
            _reject_unknown_api_path(full_path)
            return HTMLResponse(_NO_FRONTEND_HTML)

        logger.info("未找到前端产物（%s），只提供 API", dist)
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str) -> FileResponse:
        _reject_unknown_api_path(full_path)

        # 先放行真实存在的文件（favicon.ico、robots.txt、图片等）
        candidate = (dist / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            # 防目录穿越：解析后必须仍在产物目录内
            and candidate.is_relative_to(dist.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(index)

    logger.info("已挂载前端产物：%s", dist)


app = create_app()
