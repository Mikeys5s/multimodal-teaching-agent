"""Alembic 运行环境（归属：P2）。

两个关键点：
1. **数据库 URL 从 app/config.py 读**，不写在 alembic.ini 里 —— 保证只有一处真源，
   且和运行时用的是同一个文件（不会出现「迁移建在 A 库、服务连的是 B 库」）。
2. **必须显式 import app.models** —— Alembic 只认 `Base.metadata` 里已有的表。
   模型文件没被 import，autogenerate 就会生成**空迁移**，白忙一场。
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# ★ 这一行是 autogenerate 能不能看到表的关键：Alembic 只认 Base.metadata 里已有的表，
#   而 app/models/__init__.py 内部会 import 各个模型模块，所以 import 它就够了。
#   如果新增了模型却生成出空迁移，先回来检查这里。
import app.models  # noqa: F401
from alembic import context
from app.config import settings
from app.db import Base

config = context.config

# 只有调用方没指定 URL 时才从 settings 推导。
# 这样测试可以把迁移指向临时库，验证「迁移建出来的结构 == 模型定义的结构」，
# 而不是只能对着开发库跑。
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.db_file}")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连库。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite 不支持大部分 ALTER，batch 模式让「改列」也能通过重建表实现
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            # 让 SQLite 也参与「约束/索引差异」的比对
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
