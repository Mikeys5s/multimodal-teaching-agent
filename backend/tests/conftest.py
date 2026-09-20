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


# ---------------------------------------------------------------------------
# OCR 开关（D3 之后：扫描版 PDF / 图片材料默认会**真起 paddle 引擎**）
# ---------------------------------------------------------------------------


@pytest.fixture
def ocr_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 OCR 固定成「不可用」，让用例走**降级路径**（不 import paddleocr、不起引擎）。

    `app/parse/ocr.py` 的可用性结论缓存在模块级 `_AVAILABLE`（探测一次就不再探），
    所以把它按成 `False` 之后，`pdf.py` 的扫描版分支与 `parse_image()` 的
    `ensure_available()` 就都走「本机未安装 OCR 依赖」那条路 —— 与真没装
    `pip install -e ".[ocr]"` 是**同一条代码路径**，但不花一页 140 s 的识别时间。

    主题**不是** OCR 的用例（整页图无文本层的边界判定 / 降级 / 坏输入）都该挂这个
    fixture：它们守的是「扫描版不给假内容」，不是「OCR 认得多准」。
    """
    from app.parse import ocr

    monkeypatch.setattr(ocr, "_AVAILABLE", False)
    monkeypatch.setattr(ocr, "_ENGINE", None)


@pytest.fixture
def ocr_available_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 OCR 固定成「可用」但**不构造引擎**：只跳过可用性探测（省一次 ~3 s 的 import）。

    给「坏图 / 坏输入」这类用例用：它们要验的是图片读不出来时给的是
    `UNSUPPORTED_FORMAT`，而不是「没装 OCR 依赖」，所以 `ensure_available()` 必须放行；
    而调用会走到 `_read_image_file()` 就报错，永远不会碰引擎。
    """
    from app.parse import ocr

    monkeypatch.setattr(ocr, "_AVAILABLE", True)
    monkeypatch.setattr(ocr, "_ENGINE", None)


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
