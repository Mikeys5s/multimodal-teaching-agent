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


def _hash8(entity_id: str) -> str:
    """从 `mat_xxxxxxxx` / `ch_xxxxxxxx_000` 之类 ID 里取出材料 hash 段。

    夹具必须按真实 ID 规则生成，不能写死 —— 否则第二条链（mat_b）会撞上
    第一条链（mat_a）的主键，测试会以 UNIQUE 冲突的假象失败，掩盖真正的问题。
    """
    return entity_id.split("_")[1]


def make_chapter(mat_id: str, seq: int = 0, **over) -> Chapter:
    data = {
        "id": f"ch_{_hash8(mat_id)}_{seq:03d}",
        "material_id": mat_id,
        "title": "传输层",
        "number": "5",
        "seq": seq,
    }
    data.update(over)
    return Chapter(**data)


def make_section(mat_id: str, chapter_id: str, seq: int = 0, **over) -> Section:
    # chapter_id 形如 ch_<hash8>_<章seq>，把章 seq 带进节的 ID
    chapter_seq = chapter_id.split("_")[2]
    data = {
        "id": f"sec_{_hash8(mat_id)}_{chapter_seq}_{seq:03d}",
        "material_id": mat_id,
        "chapter_id": chapter_id,
        "title": "可靠数据传输",
        "number": "5.2",
        "seq": seq,
    }
    data.update(over)
    return Section(**data)


def make_kp(section_id: str, chapter_id: str, mat_id: str, seq: int = 0, **over) -> KnowledgePoint:
    # section_id 形如 sec_<hash8>_<章seq>_<节seq>。
    # 有些用例故意传非法 section_id（例如 "sec_not_exist"）来验证外键，
    # 这类值解析不出序号 —— 退回占位值即可，ID 本身与链一致性无关。
    parts = section_id.split("_")
    if len(parts) == 4 and parts[0] == "sec":
        _, _, chapter_seq, section_seq = parts
    else:
        chapter_seq = section_seq = "000"
    data = {
        "id": f"kp_{_hash8(mat_id)}_{chapter_seq}_{section_seq}_{seq:03d}",
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
# 夹具：两条互不相干的链，用来验证"跨链"数据会被拒绝
#   链 A：mat_aaaaaaaa -> ch_aaaaaaaa_000 -> sec_aaaaaaaa_000_000 -> kp0 / kp1
#   链 B：mat_bbbbbbbb -> ch_bbbbbbbb_000 -> sec_bbbbbbbb_000_000
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded(session: Session) -> dict[str, str]:
    mat_a = make_material()
    mat_b = make_material(mat_id="mat_bbbbbbbb", file_hash="b" * 64)
    session.add_all([mat_a, mat_b])
    session.flush()

    ch_a = make_chapter(mat_a.id)
    ch_b = make_chapter(mat_b.id)
    session.add_all([ch_a, ch_b])
    session.flush()

    sec_a = make_section(mat_a.id, ch_a.id)
    sec_b = make_section(mat_b.id, ch_b.id)
    session.add_all([sec_a, sec_b])
    session.flush()

    kps = [make_kp(sec_a.id, ch_a.id, mat_a.id, seq=i) for i in range(2)]
    session.add_all(kps)
    session.commit()

    return {
        "material_id": mat_a.id,
        "chapter_id": ch_a.id,
        "section_id": sec_a.id,
        "kp0": kps[0].id,
        "kp1": kps[1].id,
        # 第二条链
        "material_b": mat_b.id,
        "chapter_b": ch_b.id,
        "section_b": sec_b.id,
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


# ---------------------------------------------------------------------------
# 层级链一致性 —— 复合外键（隐患 A 的修复）
#
# 单列外键只能保证"这些 id 各自存在"，保证不了"它们同属一条链"。
# 错链数据不会报错，只会让"按章查询"和质量报告悄悄算错 —— 所以必须在写入时拦住。
# ---------------------------------------------------------------------------


def test_consistent_chain_is_accepted(session: Session, seeded: dict[str, str]) -> None:
    """正常数据当然要能写进去 —— 先确认新约束没有误伤。"""
    assert session.get(KnowledgePoint, seeded["kp0"]) is not None
    assert session.get(Section, seeded["section_b"]) is not None


def test_kp_with_chapter_from_other_chain_is_rejected(
    session: Session, seeded: dict[str, str]
) -> None:
    """节属于 A 链，chapter_id 却填 B 链的章 —— 必须拒绝。"""
    must_fail(
        session,
        make_kp(seeded["section_id"], seeded["chapter_b"], seeded["material_id"], seq=50),
    )


def test_kp_with_material_from_other_chain_is_rejected(
    session: Session, seeded: dict[str, str]
) -> None:
    """节属于 A 材料，material_id 却写 B 材料 —— 必须拒绝。"""
    must_fail(
        session,
        make_kp(seeded["section_id"], seeded["chapter_id"], seeded["material_b"], seq=51),
    )


def test_kp_with_fully_crossed_chain_is_rejected(session: Session, seeded: dict[str, str]) -> None:
    """整组字段都指向 B 链，但 section_id 是 A 链的 —— 必须拒绝。"""
    must_fail(
        session,
        make_kp(seeded["section_id"], seeded["chapter_b"], seeded["material_b"], seq=52),
    )


def test_section_with_chapter_from_other_material_is_rejected(
    session: Session, seeded: dict[str, str]
) -> None:
    """节声明属于 B 材料，章却是 A 材料的 —— 必须拒绝。"""
    must_fail(session, make_section(seeded["material_b"], seeded["chapter_id"], seq=60))


def test_moving_section_within_material_cascades_to_kp(
    session: Session, seeded: dict[str, str]
) -> None:
    """把节挪到**同材料的**另一章，其下知识点应自动跟随（ON UPDATE CASCADE）。

    这条是"复合外键不会给正常运维添麻烦"的证据 —— 否则每次调整章节结构，
    都要手工同步所有下游行。
    """
    ch_a2 = Chapter(
        id="ch_aaaaaaaa_001", material_id=seeded["material_id"], title="同材料的第二章", seq=1
    )
    session.add(ch_a2)
    session.commit()

    sec = session.get(Section, seeded["section_id"])
    assert sec is not None
    sec.chapter_id = ch_a2.id
    session.commit()

    session.expire_all()  # 丢掉身份映射里的缓存，强制从库里重读
    kp = session.get(KnowledgePoint, seeded["kp0"])
    assert kp is not None
    assert kp.chapter_id == ch_a2.id, "下游知识点的 chapter_id 没有跟随更新"


# ---------------------------------------------------------------------------
# 时间字段格式 —— 三层防护（隐患 B 的修复）
#
# 时间列是 TEXT，排序靠字典序。混进一个带本地偏移的时间，排序就会静默出错。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_value",
    [
        "2026-13-17T12:00:00+00:00",  # 13 月：形状对但日历非法（GLOB 拦不住，strftime 能）
        "2026-09-17T20:00:00+08:00",  # 带本地偏移：会破坏字典序
        "2026-09-17T12:00:00Z",  # Z 结尾：格式不统一
        "2026/09/17 12:00:00",  # 另一种写法
        "2026-09-17",  # 只有日期没有时间
        "not-a-time",  # 纯垃圾
    ],
)
def test_kp_created_at_rejects_non_utc_iso(
    session: Session, seeded: dict[str, str], bad_value: str
) -> None:
    must_fail(
        session,
        make_kp(
            seeded["section_id"],
            seeded["chapter_id"],
            seeded["material_id"],
            seq=70,
            created_at=bad_value,
        ),
    )


def test_kp_created_at_is_auto_filled_when_omitted(
    session: Session, seeded: dict[str, str]
) -> None:
    """忘了传时间不该报错，而应自动填入正确格式 —— 这是 ORM 默认值的作用。"""
    kp = KnowledgePoint(
        id="kp_aaaaaaaa_000_000_080",
        section_id=seeded["section_id"],
        chapter_id=seeded["chapter_id"],
        material_id=seeded["material_id"],
        name="不传时间的知识点",
        summary_md="说明",
        difficulty=3,
        kp_type="concept",
        source_material_id=seeded["material_id"],
        source_quote="原文",
        seq=80,
        # 刻意不传 created_at
    )
    session.add(kp)
    session.commit()

    assert kp.created_at
    assert kp.created_at.endswith("+00:00"), f"自动填充的时间不是 UTC：{kp.created_at}"


def test_material_updated_at_is_maintained(session: Session, seeded: dict[str, str]) -> None:
    """`updated_at` 应当随 ORM 更新自动刷新（靠 onupdate），不需要手工赋值。"""
    mat = session.get(Material, seeded["material_id"])
    assert mat is not None
    before = mat.updated_at

    mat.filename = "改名后的文件.pdf"
    session.commit()
    session.expire_all()

    refreshed = session.get(Material, seeded["material_id"])
    assert refreshed is not None
    assert refreshed.filename == "改名后的文件.pdf"
    assert refreshed.updated_at >= before
    assert refreshed.updated_at.endswith("+00:00")
