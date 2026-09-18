"""测试夹具（归属：P2）。

## 关键点 1：测试引擎必须走和生产同一套 pragma

见下面 `engine` fixture 的注释。

## 关键点 2：⚠️ 整个测试会话**绝不能碰真实的 `backend/app.db`**

历史问题（Issue #12）：干净环境先跑 `pytest` 会在 `backend/` 下留下一个真实的
`app.db`（表建好了但没有 `alembic_version`），导致随后的
`alembic upgrade head` 报 `table already exists`。

**根因**：有些测试要打真实接口（`TestClient(app)`），而 app 的 engine 指向
`settings.db_file`，默认就是 `backend/app.db`。

**修法**：在 `import app.*` **之前**把 `DB_PATH` 指到一个临时目录。
这样 app 的 engine 从一开始就落在临时库里，污染不了仓库。

> ⚠️ 必须放在文件最顶部、且在任何 `app.*` 导入之前 ——
> `app.config.settings` 是在**导入时**求值的，晚一步就来不及了。
"""

from __future__ import annotations

import os
import pathlib
import tempfile

# ---------------------------------------------------------------------------
# ⚠️ 必须是本文件最先执行的事情（早于任何 app.* 导入）
# ---------------------------------------------------------------------------
_TEST_DB_DIR = pathlib.Path(tempfile.mkdtemp(prefix="xizhi-pytest-"))
# 用 setdefault：外部显式传了 DB_PATH 就尊重它
os.environ.setdefault("DB_PATH", str(_TEST_DB_DIR / "test_app.db"))

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import Engine, create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402, F401  确保所有模型被注册进 Base.metadata
from alembic import command  # noqa: E402
from app.config import BACKEND_ROOT  # noqa: E402
from app.db import Base, apply_sqlite_pragmas  # noqa: E402


def pytest_report_header(config: pytest.Config) -> str:
    """把临时库位置打出来，方便排查"测试是不是又写到真实库去了"。"""
    return f"xizhi tests: DB_PATH={os.environ.get('DB_PATH')}"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """一份干净的临时库，表结构由模型直接创建（快）。"""
    eng = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    apply_sqlite_pragmas(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


@pytest.fixture
def migrated_db(tmp_path: Path) -> Iterator[Engine]:
    """用 Alembic 迁移建出来的库，用于验证「迁移 == 模型」。"""
    db_file = tmp_path / "migrated.db"
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    command.upgrade(cfg, "head")

    eng = create_engine(f"sqlite:///{db_file}", future=True)
    apply_sqlite_pragmas(eng)
    try:
        yield eng
    finally:
        eng.dispose()
