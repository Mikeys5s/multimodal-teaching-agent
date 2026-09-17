"""数据模型的约束测试（归属：P2）。

为什么这些测试值得写
--------------------
它们验证的是**数据库层的硬不变量**，而这些不变量正是验收指标的载体：
  · `knowledge_points.section_id` NOT NULL  → A2-1 三级结构完整率 100%
  · `knowledge_points.source_quote` NOT NULL → A2-3 溯源覆盖率 100%
  · `kp_prerequisites.reason` NOT NULL      → B1-5 边理由完备率
  · `kp_prerequisites.no_self_loop`         → B1-2 依赖图无环（自环是环的最简形式）

一旦约束，测试立刻失败 —— 而不是等到跑验收时才发现"这一列原来可以空"。
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Chapter,
    KnowledgePoint,
    KpPrerequisite,
    Material,
    MaterialBlock,
    Section,
    utc_now_iso,
)

# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

HASH = "a" * 64  # 假的 sha256 全串


def make_material(mat_id: str = "mat_aaaaaaaa", file_hash: str = HASH, **over) -> Material:
    data = {
        "id": mat_id,
        "filename": "第5章.pdf",
        "file_hash": file_hash,
        "stored_path": "2026/09/abc.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
        "source_type": "pdf_text",
        "status": "done",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    data.update(over)
    return Material(**data)


def make_chapter(mat_id: str, seq: int = 0, **over) -> Chapter:
    data = {
        "id": f"ch_aaaaaaaa_{seq:03d}",
        "material_id": mat_id,
        "title": "传输层",
        "number": "5",
        "seq": seq,
    }
    data.update(over)
    return Chapter(**data)


def make_section(mat_id: str, chapter_id: str, seq: int = 0, **over) -> Section:
    data = {
        "id": f"sec_aaaaaaaa_{0:03d}_{seq:03d}",
        "material_id": mat_id,
        "chapter_id": chapter_id,
        "title": "可靠数据传输",
        "number": "5.2",
        "seq": seq,
    }
    data.update(over)
    return Section(**data)


def make_kp(section_id: str, chapter_id: str, mat_id: str, seq: int = 0, **over) -> KnowledgePoint:
    data = {
        "id": f"kp_aaaaaaaa_{0:03d}_{0:03d}_{seq:03d}",
        "section_id": section_id,
        "chapter_id": chapter_id,
        "material_id": mat_id,
        "name": f"知识点 {seq}",
        "summary_md": "一句话说明",
        "difficulty": 3,
        "kp_type": "concept",
        "source_material_id": mat_id,
        "source_quote": "原文片段",
        "seq": seq,
        "created_at": utc_now_iso(),
    }
    data.update(over)
    return KnowledgePoint(**data)


def must_fail(session: Session, obj: object) -> None:
    """断言写入被数据库拒绝，然后回滚以免污染后续断言。"""
    with pytest.raises(IntegrityError):
        session.add(obj)
        session.flush()
    session.rollback()


# ---------------------------------------------------------------------------
# 夹具：一份材料 -> 一章 -> 一节 -> 两个知识点
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded(session: Session) -> dict[str, str]:
    mat = make_material()
    session.add(mat)
    session.flush()

    ch = make_chapter(mat.id)
    session.add(ch)
    session.flush()

    sec = make_section(mat.id, ch.id)
    session.add(sec)
    session.flush()

    kps = [make_kp(sec.id, ch.id, mat.id, seq=i) for i in range(2)]
    session.add_all(kps)
    session.commit()

    return {
        "material_id": mat.id,
        "chapter_id": ch.id,
        "section_id": sec.id,
        "kp0": kps[0].id,
        "kp1": kps[1].id,
    }


# ---------------------------------------------------------------------------
# materials
# ---------------------------------------------------------------------------


def test_file_hash_must_be_unique(session: Session) -> None:
    """成本控制 C2：同一文件重复上传不重复抽取 —— 靠这个唯一索引兜住。"""
    session.add(make_material())
    session.commit()
    must_fail(session, make_material(mat_id="mat_bbbbbbbb"))  # 同 hash，不同 id


def test_source_type_must_be_in_whitelist(session: Session) -> None:
    must_fail(session, make_material(source_type="excel"))


def test_status_must_be_in_whitelist(session: Session) -> None:
    must_fail(session, make_material(status="finished"))


# ---------------------------------------------------------------------------
# material_blocks
# ---------------------------------------------------------------------------


def test_block_seq_unique_within_material(session: Session) -> None:
    session.add(make_material())
    session.flush()
    session.add(
        MaterialBlock(
            id="blk_aaaaaaaa_00000",
            material_id="mat_aaaaaaaa",
            seq=0,
            block_type="paragraph",
            content_md="内容",
        )
    )
    session.commit()
    must_fail(
        session,
        MaterialBlock(
            id="blk_aaaaaaaa_00001",
            material_id="mat_aaaaaaaa",
            seq=0,  # 同 seq
            block_type="paragraph",
            content_md="另一段",
        ),
    )


def test_heading_level_range_is_enforced(session: Session) -> None:
    session.add(make_material())
    session.flush()
    must_fail(
        session,
        MaterialBlock(
            id="blk_aaaaaaaa_00000",
            material_id="mat_aaaaaaaa",
            seq=0,
            block_type="heading",
            content_md="标题",
            heading_level=9,  # 超过 1–6
        ),
    )


# ---------------------------------------------------------------------------
# knowledge_points —— A2-1 / A2-3 的载体
# ---------------------------------------------------------------------------


def test_kp_requires_existing_section(session: Session, seeded: dict[str, str]) -> None:
    """★ 这条同时验证两件事：
    ① section_id 非空（三级结构完整率 100%）；
    ② **外键约束真的生效** —— 如果 db.py 的 pragma 监听被去掉，这里会静默通过。
    """
    must_fail(session, make_kp("sec_not_exist", seeded["chapter_id"], seeded["material_id"], seq=9))


def test_kp_source_quote_cannot_be_blank(session: Session, seeded: dict[str, str]) -> None:
    """A2-3 溯源覆盖率 100%：空白的 source_quote 不得入库。"""
    must_fail(
        session,
        make_kp(
            seeded["section_id"],
            seeded["chapter_id"],
            seeded["material_id"],
            seq=9,
            source_quote="   ",
        ),
    )


def test_kp_source_quote_is_mandatory(session: Session, seeded: dict[str, str]) -> None:
    must_fail(
        session,
        make_kp(
            seeded["section_id"],
            seeded["chapter_id"],
            seeded["material_id"],
            seq=9,
            source_quote=None,
        ),
    )


@pytest.mark.parametrize("bad_difficulty", [0, 6, -1, 99])
def test_kp_difficulty_range(session: Session, seeded: dict[str, str], bad_difficulty: int) -> None:
    must_fail(
        session,
        make_kp(
            seeded["section_id"],
            seeded["chapter_id"],
            seeded["material_id"],
            seq=9,
            difficulty=bad_difficulty,
        ),
    )


def test_kp_type_must_be_known(session: Session, seeded: dict[str, str]) -> None:
    must_fail(
        session,
        make_kp(
            seeded["section_id"],
            seeded["chapter_id"],
            seeded["material_id"],
            seq=9,
            kp_type="vibes",
        ),
    )


def test_kp_name_unique_within_section(session: Session, seeded: dict[str, str]) -> None:
    """同节内重名会让依赖边指向"哪个重名的？"，无法解释 —— 必须拒绝。"""
    must_fail(
        session,
        make_kp(
            seeded["section_id"],
            seeded["chapter_id"],
            seeded["material_id"],
            seq=9,
            name="知识点 0",  # 与已存在的重名
        ),
    )


# ---------------------------------------------------------------------------
# kp_prerequisites —— ★ B1-2 / B1-4 / B1-5 的载体
# ---------------------------------------------------------------------------


def test_edge_reason_is_mandatory(session: Session, seeded: dict[str, str]) -> None:
    """B1-5 要求边理由 100% 完备 —— 数据库层直接堵死空理由。"""
    must_fail(
        session,
        KpPrerequisite(
            kp_id=seeded["kp1"],
            prereq_kp_id=seeded["kp0"],
            relation_type="hard",
            reason=None,
            created_at=utc_now_iso(),
        ),
    )


def test_edge_reason_cannot_be_blank(session: Session, seeded: dict[str, str]) -> None:
    must_fail(
        session,
        KpPrerequisite(
            kp_id=seeded["kp1"],
            prereq_kp_id=seeded["kp0"],
            relation_type="hard",
            reason="  ",
            created_at=utc_now_iso(),
        ),
    )


def test_self_loop_is_rejected(session: Session, seeded: dict[str, str]) -> None:
    """自环是环的最简形式。B1-2 要求环数为 0，最底层的防线就在这里。"""
    must_fail(
        session,
        KpPrerequisite(
            kp_id=seeded["kp0"],
            prereq_kp_id=seeded["kp0"],  # 自己依赖自己
            relation_type="hard",
            reason="自己依赖自己",
            created_at=utc_now_iso(),
        ),
    )


def test_relation_type_must_be_hard_or_soft(session: Session, seeded: dict[str, str]) -> None:
    must_fail(
        session,
        KpPrerequisite(
            kp_id=seeded["kp1"],
            prereq_kp_id=seeded["kp0"],
            relation_type="medium",
            reason="理由",
            created_at=utc_now_iso(),
        ),
    )


def test_source_channel_must_be_known(session: Session, seeded: dict[str, str]) -> None:
    must_fail(
        session,
        KpPrerequisite(
            kp_id=seeded["kp1"],
            prereq_kp_id=seeded["kp0"],
            relation_type="hard",
            reason="理由",
            source_channel="guess",
            created_at=utc_now_iso(),
        ),
    )


def test_valid_edge_round_trips_with_defaults(session: Session, seeded: dict[str, str]) -> None:
    """一条合法边应当能写入，且默认值符合预期（soft 不阻塞、未剪枝、无冲突）。"""
    session.add(
        KpPrerequisite(
            kp_id=seeded["kp1"],
            prereq_kp_id=seeded["kp0"],
            relation_type="hard",
            reason="不懂前置就无法推导后置",
            created_at=utc_now_iso(),
        )
    )
    session.commit()

    edge = session.get(KpPrerequisite, (seeded["kp1"], seeded["kp0"]))
    assert edge is not None
    assert edge.source_channel == "semantic"
    assert edge.pruned == 0  # 默认未剪枝
    assert edge.needs_review == 0
    assert edge.confidence is None


def test_pruned_flag_accepts_only_boolean(session: Session, seeded: dict[str, str]) -> None:
    """pruned 是软删除标记，只能是 0/1 —— 防止有人塞进时间戳之类的值。"""
    must_fail(
        session,
        KpPrerequisite(
            kp_id=seeded["kp1"],
            prereq_kp_id=seeded["kp0"],
            relation_type="hard",
            reason="理由",
            pruned=2,
            created_at=utc_now_iso(),
        ),
    )


# ---------------------------------------------------------------------------
# 级联删除
# ---------------------------------------------------------------------------


def test_deleting_material_cascades_to_knowledge_points(
    session: Session, seeded: dict[str, str]
) -> None:
    """删素材必须把整棵树带走，否则会留下指向不存在材料的孤儿知识点。"""
    session.delete(session.get(Material, seeded["material_id"]))
    session.commit()

    assert session.get(KnowledgePoint, seeded["kp0"]) is None
    assert session.get(Section, seeded["section_id"]) is None
    assert session.get(Chapter, seeded["chapter_id"]) is None
