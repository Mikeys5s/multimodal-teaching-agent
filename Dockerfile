# 析知 XiZhi · 单容器镜像（SPEC §4.7）
#
# ## 形态
#
# 一个镜像同时装**前端产物**和**后端服务**，对外只暴露一个端口：
#   /            → 前端静态产物（SPA，带 catch-all 回退）
#   /api/**      → FastAPI 接口
#   /docs        → OpenAPI 文档
#
# 同源部署 → **不需要 CORS**，也不需要 nginx 反向代理。
#
# ## 三个刻意的设计
#
# **① 前端产物是"可选"的 —— 前端不存在也能构建成功。**
# 用 `COPY . .` 整仓拷进来再判断，而不是直接 `COPY frontend/`。
# 原因：前端目录在某个时间点可能还没进仓库（**现在就是**），
# 而 `COPY` 一个不存在的目录会**直接构建失败**。
# 这样后端可以独立先上线，不被前端阻塞 —— **M3 是硬里程碑，不能押在别人身上。**
#
# **② 必须用 editable 安装（`pip install -e .`），不能用普通安装。**
# 项目里 `BACKEND_ROOT = Path(__file__).resolve().parents[1]` 决定了
# 上传目录、数据库、alembic 脚本的位置都**相对源码目录**解析。
# 普通安装会把 `app` 放进 site-packages，那套相对路径全部失效。
#
# **③ 依赖分层要放在源码拷入之后做，不能提前。**
# `pip install -e .` 需要源码在场，先拷 `pyproject.toml` 再装是**跑不通的**
# （editable 安装找不到包）。这里牺牲一点层缓存换正确性 ——
# 本项目依赖不多，重建代价可以接受。

# ---------------------------------------------------------------------------
# 阶段 1：构建前端
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /src
COPY . .

RUN if [ -f frontend/package.json ]; then \
        echo "==> 检测到 frontend/package.json，开始构建前端"; \
        cd frontend && npm ci && npm run build; \
    else \
        echo "==> 未检测到前端（frontend/package.json 不存在），跳过构建"; \
        mkdir -p frontend/dist; \
    fi \
    && echo "==> 前端阶段产物：" && ls -la frontend/dist | head -20


# ---------------------------------------------------------------------------
# 阶段 2：Python 运行时
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tini 负责转发信号，避免容器里 uvicorn 收不到 SIGTERM
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# 目录布局刻意与仓库一致：
#   /app/backend        ← 源码（BACKEND_ROOT）
#   /app/frontend/dist  ← 前端产物
# 这样 `frontend_dist = "../frontend/dist"` 这个默认配置在本地和容器里**同时成立**，
# 不需要靠环境变量去区分两套环境。
WORKDIR /app/backend

COPY backend/ /app/backend/
COPY --from=frontend /src/frontend/dist /app/frontend/dist

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e . \
    && python -c "import app.main; print('==> 后端可导入，端点', len(app.main.app.openapi()['paths']))"

# 运行期数据（SQLite + 上传文件）落在 /data，由 compose 挂卷持久化
ENV DB_PATH=/data/xizhi.db \
    UPLOAD_DIR=/data/uploads \
    APP_PORT=8000 \
    DEBUG=false
RUN mkdir -p /data/uploads && chmod +x /app/backend/docker-entrypoint.sh

EXPOSE 8000

# 用 exec 形式避免 shell 引号问题
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["/usr/bin/tini", "--", "/app/backend/docker-entrypoint.sh"]
