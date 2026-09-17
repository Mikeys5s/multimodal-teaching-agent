"""迁移与模型的一致性测试（归属：P2）。

为什么需要这个测试
------------------
Alembic 的 `autogenerate` **不保证把所有结构都写进迁移**。实测踩过一次：
模型里声明了 `Index("idx_materials_created", text("created_at DESC"))`，
迁移里却**静默少了这个索引** —— 模型与数据库不一致，而且不会报错。

这个测试把"模型定义"与"迁移实际建出来的结构"直接对比，把这类隐蔽偏差
变成一次明确的失败。以后任何人改了模型忘了生成迁移、或生成了不完整的迁移，
CI/本地跑测试时立刻就知道。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Engine, Index, UniqueConstraint, inspect

from app.db import Base

EXPECTED_TABLES = {
    "materials",
    "material_blocks",
    "chapters",
    "sections",
    "knowledge_points",
    "kp_prerequisites",
}


def _migrated_names(engine: Engine) -> tuple[set[str], set[str], set[str]]:
    """从迁移建出的真实数据库里读表名 / 索引名 / CHECK 约束名。"""
    insp = inspect(engine)

    tables = set(insp.get_table_names()) - {"alembic_version"}

    index_names: set[str] = set()
    check_names: set[str] = set()
    for table in tables:
        index_names |= {ix["name"] for ix in insp.get_indexes(table)}
        # SQLite 的 CHECK 约束只能从 DDL 文本里读
        with engine.connect() as conn:
            ddl = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
        if not ddl or not ddl[0]:
            continue
        for line in ddl[0].splitlines():
            stripped = line.strip().strip(",").strip()
            if stripped.upper().startswith("CONSTRAINT") and "CHECK" in stripped.upper():
                check_names.add(stripped.split()[1].strip('"'))

    return tables, index_names, check_names


def _model_names() -> tuple[set[str], set[str], set[str]]:
    """从模型 metadata 里读期望的表名 / 索引名 / 命名 CHECK 约束名。"""
    tables = set(Base.metadata.tables)
    index_names: set[str] = set()
    check_names: set[str] = set()
    for table in Base.metadata.tables.values():
        index_names |= {ix.name for ix in table.indexes if isinstance(ix, Index)}
        for c in table.constraints:
            if isinstance(c, CheckConstraint) and c.name:
                check_names.add(c.name)
            if isinstance(c, UniqueConstraint) and c.name:
                # 唯一约束在 SQLite 里落成自动索引或被 CHECK 之外的机制处理，
                # 这里只统计命名 CHECK，唯一性由 test_models_constraints 单独验证
                pass
    return tables, index_names, check_names


def test_migrated_tables_match_models(migrated_db: Engine) -> None:
    tables, _, _ = _migrated_names(migrated_db)
    assert tables == EXPECTED_TABLES


def test_migrated_indexes_match_models(migrated_db: Engine) -> None:
    """★ 这条会抓住"模型里有索引、迁移里漏了"的情况。"""
    _, migrated_indexes, _ = _migrated_names(migrated_db)
    _, model_indexes, _ = _model_names()

    missing = model_indexes - migrated_indexes
    extra = migrated_indexes - model_indexes

    assert not missing, f"模型里有但迁移里没有的索引：{sorted(missing)}"
    assert not extra, f"迁移里有但模型里没有的索引：{sorted(extra)}"


def test_migrated_check_constraints_match_models(migrated_db: Engine) -> None:
    """★ 这条会抓住"CHECK 约束漏进迁移"的情况 —— 那意味着校验形同虚设。"""
    _, _, migrated_checks = _migrated_names(migrated_db)
    _, _, model_checks = _model_names()

    missing = model_checks - migrated_checks
    assert not missing, f"模型里有但迁移里没有的 CHECK 约束：{sorted(missing)}"


def test_foreign_keys_exist_in_migrated_db(migrated_db: Engine) -> None:
    """关键外键不能缺 —— 缺了会留下孤儿数据。"""
    insp = inspect(migrated_db)

    kp_fks = {fk["referred_table"] for fk in insp.get_foreign_keys("knowledge_points")}
    assert {"sections", "chapters", "materials", "material_blocks"} <= kp_fks

    edge_fks = [fk for fk in insp.get_foreign_keys("kp_prerequisites")]
    assert len(edge_fks) == 2
    assert all(fk["referred_table"] == "knowledge_points" for fk in edge_fks)


def test_pragmas_are_active_on_migrated_db(migrated_db: Engine) -> None:
    """迁移跑完后，连接上的 pragma 仍然要生效（它们是连接级的，容易被忽略）。"""
    with migrated_db.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert str(conn.exec_driver_sql("PRAGMA journal_mode").scalar()).lower() == "wal"
