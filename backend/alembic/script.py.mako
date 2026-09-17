"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    # ⚠️ 有数据的库上执行 downgrade 会**丢数据**（SQLite 的 DROP TABLE 不可逆）。
    #    仅限本地开发库使用，禁止对共享库 / 演示库执行。详见 backend/README.md。
    ${downgrades if downgrades else "pass"}
