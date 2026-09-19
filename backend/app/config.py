"""应用配置（归属：P2）。

设计要点
--------
1. **默认值必须能用** —— 不配 `.env` 也要能跑起来。否则 P1/P3 一拉代码就被卡住，
   而他们的模块可能根本用不到这些配置项。
2. **相对路径锚定到 backend/** —— 不依赖「当前工作目录」。用 `uvicorn app.main:app`
   和用 `pytest` 跑测试时 CWD 未必相同，锚定后才稳定可预期。
3. `.env` 只读仓库根目录那一份，不在 backend/ 下再放一份，避免两处配置漂移。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> 仓库根
BACKEND_ROOT: Path = Path(__file__).resolve().parents[1]
REPO_ROOT: Path = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 基础 ----
    app_name: str = "析知 XiZhi API"
    version: str = "0.1.0"
    debug: bool = True

    # ---- 数据库 ----
    # 相对路径一律相对 backend/ 解析
    db_path: str = "./app.db"

    # ---- 文件存储 ----
    upload_dir: str = "./uploads"
    max_upload_mb: int = 50

    # ---- 服务 ----
    app_port: int = 8000
    # 开发期前端地址，用于 CORS 白名单。
    # 生产环境是单容器同源部署，不需要 CORS（SPEC §4.7）。
    dev_frontend_origin: str = "http://localhost:5173"

    # ---- 前端产物（单容器部署）----
    # 相对路径锚定到 backend/，所以默认值 `../frontend/dist` 指向仓库根的 frontend/dist。
    # 容器里的目录布局与仓库一致（`/app/backend` + `/app/frontend/dist`），
    # 因此**同一份配置在本地和容器里都成立**，不需要靠环境变量区分。
    frontend_dist: str = "../frontend/dist"

    # ---- 路径解析 ----

    def resolve(self, raw: str) -> Path:
        """把配置里的路径解析成绝对路径：相对路径锚定到 backend/。"""
        path = Path(raw).expanduser()
        return path.resolve() if path.is_absolute() else (BACKEND_ROOT / path).resolve()

    @property
    def db_file(self) -> Path:
        return self.resolve(self.db_path)

    @property
    def upload_path(self) -> Path:
        return self.resolve(self.upload_dir)

    @property
    def frontend_dist_path(self) -> Path:
        return self.resolve(self.frontend_dist)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例。

    用函数而不是模块级常量，是为了让测试能通过 `get_settings.cache_clear()`
    换一套配置重跑。
    """
    return Settings()


settings = get_settings()
