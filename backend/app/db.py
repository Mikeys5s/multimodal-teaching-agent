"""数据库引擎与会话（归属：P2）。

⚠️ 关于 SQLite 的三个 pragma —— 这是本文件存在的核心原因
------------------------------------------------------------
SQLite 的 pragma 是**连接级**的，不是数据库级的。也就是说，
`connection` 一旦新建，就必须重新设置一遍，否则那条连接上的行为会退回默认值。

其中最危险的是 `foreign_keys`：**SQLite 默认不启用外键约束**。
如果只在建库时设一次，之后新建的连接（比如 FastAPI 后台任务的连接）上
外键就是不生效的 —— 数据脏了不会报错，等到查询对不上才发现，非常难查。

所以这里用 `event.listens_for(engine, "connect")` 挂在**每一个新连接**上。
"""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

# ---- 引擎 ----
# check_same_thread=False：FastAPI 的 BackgroundTasks 会在不同线程里访问数据库，
# 不关掉这个检查会直接抛 ProgrammingError。
engine: Engine = create_engine(
    f"sqlite:///{settings.db_file}",
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    """每个新连接都必须设一遍 pragma。"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")  # 读写并发：解析任务写、前端读，不互锁
        cursor.execute("PRAGMA foreign_keys=ON")  # ★ 默认关闭，漏了外键形同虚设
        cursor.execute("PRAGMA busy_timeout=5000")  # 写冲突时等 5s 而不是立刻报错
        cursor.execute("PRAGMA synchronous=NORMAL")  # WAL 下的常规取舍：性能与安全平衡
    finally:
        cursor.close()


# ---- 会话 ----
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。

    Alembic 通过 `Base.metadata` 感知表结构 —— 因此新增模型文件后
    **必须在 app/models/__init__.py 里 import 它**，否则会生成空迁移。
    """


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_runtime_dirs() -> None:
    """确保运行期需要的目录存在（上传目录、数据库文件所在目录）。"""
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    settings.db_file.parent.mkdir(parents=True, exist_ok=True)


def pragma_status() -> dict[str, str]:
    """读回当前连接的实际 pragma 值，用于 /api/health 自检。

    这是「不要假设、要验证」的一个小落地：外键开关到底有没有生效，
    跑一下就知道，不用靠读代码猜。
    """
    out: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            for name in ("journal_mode", "foreign_keys", "busy_timeout"):
                row = conn.exec_driver_sql(f"PRAGMA {name}").fetchone()
                out[name] = str(row[0]) if row else "unknown"
    except Exception as exc:  # noqa: BLE001 - 自检接口不该因数据库问题而 500
        logger.warning("读取 pragma 状态失败: %s", exc)
        out["error"] = str(exc)
    return out
