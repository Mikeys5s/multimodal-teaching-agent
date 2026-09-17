"""测试夹具（归属：P2）。

关键点：测试引擎**必须走和生产同一套 pragma 设置**（`apply_sqlite_pragmas`）。
如果测试自己建引擎却忘了开 `foreign_keys`，就会出现
"外键测试在测试环境通过、在生产环境不生效" —— 这是最糟糕的一种假绿。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401  确保所有模型被注册进 Base.metadata
from alembic import command
from app.config import BACKEND_ROOT
from app.db import Base, apply_sqlite_pragmas


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
