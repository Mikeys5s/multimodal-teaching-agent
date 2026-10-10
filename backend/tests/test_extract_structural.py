"""`_section_ranges` 的区间推导测试（归属：P2）。

## 为什么单独给这个函数写测试

它是**结构线索抽取里最容易静默出错**的一步。

`#2` 的评审里我追问过队友：`ParsedSection` 的块区间是左闭右闭还是半开？
差一个块会怎样？——答案是：**不会报错，只会让知识点悄悄挂到相邻的节上**，
而"三级结构完整率 100%"这个硬指标**照样通过**，内容却是错的。

`ParsedSection.__post_init__` 用构造期不变量挡住了那一类问题。
**但那个不变量没有跟着落库** —— `sections` 表里只有 `source_block_id`（标题块），
没有 start/end。所以在读侧要**再推一次**，而推导逻辑没有任何保护。

**这个文件就是那个保护。** 它测的不是"能不能跑"，是边界对不对：

| 场景 | 期望 |
|---|---|
| 两个节 | 前一节到"下一节标题块 - 1"为止（**不吞掉下一节的标题**） |
| 最后一个节 | 一直延伸到最后一个块 |
| 只有一个节 | 从它的标题块覆盖到文件末尾 |
| 标题块缺失（`source_block_id` 为空） | **退化但不崩**（start=0），且仍不重叠 |

**"不吞掉下一节的标题"是这里最关键的一条** ——
它错了不会报错，只会让下一节的标题块被算进上一节，
于是那一节少了一个块、上一节多了一个块。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extract.structural import _chapter_seq_of, _section_ranges  # noqa: E402
from app.models import MaterialBlock, Section  # noqa: E402


def _block(seq: int, btype: str = "paragraph") -> MaterialBlock:
    return MaterialBlock(
        id=f"blk_test_{seq:05d}",
        material_id="mat_test",
        seq=seq,
        page_no=1,
        line_start=seq + 1,
        line_end=seq + 1,
        block_type=btype,
        heading_level=1 if btype == "heading" else None,
        content_md=f"块 {seq}",
        image_path=None,
        ocr_confidence=None,
    )


def _section(seq: int, heading_block_id: str | None, chapter_seq: int = 0) -> Section:
    """造一个节。

    `chapter_seq` 默认 0（保持原有用例不变）。**多章场景必须显式传它** ——
    这正是下面那条回归用例的关键：`Section.seq` 是**章内**序号，
    两个不同的章会各有自己的 `seq=0`。
    """
    return Section(
        id=f"sec_test_{chapter_seq:03d}_{seq:03d}",
        material_id="mat_test",
        chapter_id=f"ch_test_{chapter_seq:03d}",
        number=str(seq),
        title=f"第 {chapter_seq}.{seq} 节",
        seq=seq,
        source_block_id=heading_block_id,
    )


def test_two_sections_do_not_swallow_next_heading() -> None:
    """★ 前一节**不能吞掉**下一节的标题块 —— 这是本文件最要紧的一条。

    块布局：
        0 标题A   1 正文A   2 标题B   3 正文B

    期望：
        节A -> [0, 1]（**到 2 之前为止**）
        节B -> [2, 3]

    如果这里错了（比如节A拿到 [0,2]），节A会多一个块、节B会少一个块 ——
    **而不会有任何报错。**
    """
    blocks = [
        _block(0, "heading"),
        _block(1),
        _block(2, "heading"),
        _block(3),
    ]
    sections = [_section(0, "blk_test_00000"), _section(1, "blk_test_00002")]

    got = [(sec.seq, lo, hi) for sec, lo, hi in _section_ranges(sections, blocks)]

    assert got == [(0, 0, 1), (1, 2, 3)], f"区间推导错了：{got}"


def test_last_section_extends_to_end_of_document() -> None:
    """最后一个节一直延伸到最后一个块 —— 否则尾部内容会没有归属。"""
    blocks = [_block(0, "heading"), _block(1), _block(2), _block(3), _block(4)]
    sections = [_section(0, "blk_test_00000")]

    got = [(sec.seq, lo, hi) for sec, lo, hi in _section_ranges(sections, blocks)]

    assert got == [(0, 0, 4)], f"末节没有延伸到文件末尾：{got}"


def test_single_section_covers_whole_document() -> None:
    """只有一个节时，它覆盖整份材料（含标题块自身）。"""
    blocks = [_block(0, "heading"), _block(1)]
    sections = [_section(0, "blk_test_00000")]

    (_, lo, hi), = _section_ranges(sections, blocks)
    assert (lo, hi) == (0, 1)


def test_missing_heading_block_does_not_crash_and_claims_nothing() -> None:
    """标题块缺失时：**不崩、不认领任何块、不影响别的节**。

    ★ **契约变更**（原文写作「退化但不崩（start=0），且仍不重叠」）：
    原先退化成"从 0 开始"，等于让这个**定位不到**的节把文档开头整段认领过去 ——
    而那段往往已经属于第一个正常节，于是同一批块被认领两次、**又生成重复知识点**
    （这正是「629 条里 462 条副本」的成因之一）。

    现在改为：定位不到的节**返回空区间**（`lo > hi`，放在列表末尾），
    知识点数为 0 而**不是**把别人的内容复制一份。
    这是**可见的**损失（那一节空了，一眼能看出来），
    比"静默复制别人的内容"好 —— 在这个项目里，静默的错数据比缺失更贵。

    ⇒ 所以本用例现在断言的是**更强**的性质：每个块**至多**被一个节覆盖。
    """
    blocks = [_block(0), _block(1), _block(2)]
    sections = [_section(0, None), _section(1, "blk_test_00002")]

    got = _section_ranges(sections, blocks)

    assert len(got) == 2
    # 按「节的标题块」索引，不依赖返回顺序
    by_head = {sec.source_block_id: (lo, hi) for sec, lo, hi in got}
    assert set(by_head) == {None, "blk_test_00002"}, f"节的集合不对：{sorted(map(str, by_head))}"

    lo_bad, hi_bad = by_head[None]
    assert lo_bad > hi_bad, f"定位不到的节不该认领块，却拿到了 [{lo_bad},{hi_bad}]"
    assert by_head["blk_test_00002"] == (2, 2), (
        f"正常节的区间不对：{by_head['blk_test_00002']}"
    )

    # ★ 更强的不变量：没有任何块被两个节同时认领
    import collections

    cover: collections.Counter[int] = collections.Counter()
    for _, lo, hi in got:
        for s in range(lo, hi + 1):
            cover[s] += 1
    duplicated = sorted(s for s, n in cover.items() if n > 1)
    assert not duplicated, f"这些块被多个节同时覆盖（会产生重复知识点）：{duplicated}"


# ---------------------------------------------------------------------------
# ★ 多章材料：区间必须**按文档顺序**推，不能按 Section.seq 推
# ---------------------------------------------------------------------------


def test_multi_chapter_sections_do_not_overlap() -> None:
    """★ 回归用例：多章材料里，**每个块只能归属一个节**。

    这是「629 条里 462 条副本」的根因 —— 原先按 `Section.seq` 排序，
    而它是**章内**序号（唯一键 `(chapter_id, seq)`），多章材料里不同章的节 seq 相同，
    排序后**章与章交错**，"下一节的标题块"取到的根本不是文档里的下一节，
    推出来的区间互相重叠 ⇒ 同一批块被多个节各抽一遍。

    块布局（`MaterialBlock.seq` 在一份材料内**全局唯一且递增**）：

        0 章A标题   1 正文A1   2 正文A2   3 正文A3   4 节A2标题   5 正文A4
        6 章B标题   7 正文B1   8 正文B2   9 正文B3  10 节B2标题  11 正文B4

    四个节（注意 seq 是**章内**的：A 有 0/1，B 也有 0/1）：

        sec A-0 -> blk 0     sec A-1 -> blk 4
        sec B-0 -> blk 6     sec B-1 -> blk 10

    期望（按文档顺序、互不重叠、且**覆盖每个块恰好一次**）：

        A-0 -> [0,3]   A-1 -> [4,5]   B-0 -> [6,9]   B-1 -> [10,11]
    """
    blocks = [
        _block(0, "heading"), _block(1), _block(2), _block(3),
        _block(4, "heading"), _block(5),
        _block(6, "heading"), _block(7), _block(8), _block(9),
        _block(10, "heading"), _block(11),
    ]
    sections = [
        _section(0, "blk_test_00000", chapter_seq=0),   # A-0
        _section(1, "blk_test_00004", chapter_seq=0),   # A-1
        _section(0, "blk_test_00006", chapter_seq=1),   # B-0
        _section(1, "blk_test_00010", chapter_seq=1),   # B-1
    ]

    got = _section_ranges(sections, blocks)
    spans = [(sec.chapter_id, sec.seq, lo, hi) for sec, lo, hi in got]

    assert spans == [
        ("ch_test_000", 0, 0, 3),
        ("ch_test_000", 1, 4, 5),
        ("ch_test_001", 0, 6, 9),
        ("ch_test_001", 1, 10, 11),
    ], f"区间推导错了（应按文档顺序）：{spans}"

    # ★ 核心不变量：每个块**恰好**被一个节覆盖 —— 重叠就是"副本"的来源
    import collections

    cover: collections.Counter[int] = collections.Counter()
    for _, lo, hi in got:
        for s in range(lo, hi + 1):
            cover[s] += 1
    duplicated = sorted(s for s, n in cover.items() if n > 1)
    assert not duplicated, f"这些块被多个节同时覆盖（会产生重复知识点）：{duplicated}"
    missing = sorted({b.seq for b in blocks} - set(cover))
    assert not missing, f"这些块没有归属（内容会丢）：{missing}"


def test_old_sort_key_would_have_overlapped() -> None:
    """★ 对照实验：**证明上面那条用例是有牙的**。

    在同一条布局上，按**旧的排序键**（`Section.seq`）推一遍 —— 它必须产生重叠。
    否则说明这条布局照不到那个 bug，上面的用例就是"假绿"。
    """
    blocks = [
        _block(0, "heading"), _block(1), _block(2), _block(3),
        _block(4, "heading"), _block(5),
        _block(6, "heading"), _block(7), _block(8), _block(9),
        _block(10, "heading"), _block(11),
    ]
    sections = [
        _section(0, "blk_test_00000", chapter_seq=0),
        _section(1, "blk_test_00004", chapter_seq=0),
        _section(0, "blk_test_00006", chapter_seq=1),
        _section(1, "blk_test_00010", chapter_seq=1),
    ]
    heading_seq = {b.id: b.seq for b in blocks}
    max_seq = max(b.seq for b in blocks)

    # ↓ 旧实现（按 Section.seq 排序）原样复刻，只用于对照
    ordered = sorted(sections, key=lambda s: s.seq)
    old: list[tuple[int, int]] = []
    for i, sec in enumerate(ordered):
        start = heading_seq.get(sec.source_block_id or "", 0)
        if i + 1 < len(ordered):
            nxt = heading_seq.get(ordered[i + 1].source_block_id or "", max_seq + 1)
            end = max(start, nxt - 1)
        else:
            end = max_seq
        old.append((start, end))

    import collections

    cover: collections.Counter[int] = collections.Counter()
    for lo, hi in old:
        for s in range(lo, hi + 1):
            cover[s] += 1
    dup = sorted(s for s, n in cover.items() if n > 1)
    assert dup, (
        "旧排序键在这条布局上没有产生重叠 —— 这条回归用例照不到那个 bug，"
        f"需要换布局。旧区间={old}"
    )


def test_kp_id_uses_the_sections_chapter_seq() -> None:
    """★ 回归用例：知识点 id 的「章」段必须是**章**的序号，不是节的。

    原先调用处传的是 `knowledge_point_id(mat_id, sec.seq, sec.seq, n)` ——
    两个段都填 `sec.seq`，于是 id 的章段恒等于节段。线上 629 条里这一对段
    只有 `000_000 / 001_001 / 002_002 / 003_003` 四种，而单是 Ch03 就有 104 个节 ——
    **光看 id 定位不到具体的章和节**。
    """
    from app.models.ids import knowledge_point_id

    # B 章（chapter_id = ch_test_002）的第一个节（章内 seq = 0）
    sec = _section(0, "blk_test_00006", chapter_seq=2)
    assert _chapter_seq_of(sec) == 2, "章序号取错了 —— 又把节的 seq 当成章的了"

    kp_id = knowledge_point_id("mat_a1b2c3d4", _chapter_seq_of(sec), sec.seq, 7)
    assert kp_id.endswith("_002_000_007"), (
        f"id 形状不对（期望 <hash>_002_000_007）：{kp_id}"
    )
    # 对照：旧的调用口径会给出 _000_000_007 —— 章段丢失
    assert not kp_id.endswith("_000_000_007"), "章段仍然丢失（又退化成了 sec.seq, sec.seq）"


def test_chapter_seq_of_falls_back_to_relationship() -> None:
    """`chapter_id` 解析不出来时，退回关系属性；都没有就显式报错。"""
    import pytest

    class _Ch:
        seq = 5

    class _Sec:
        id = "sec_test_x"
        chapter_id = "坏掉的 id"
        chapter = _Ch()

    assert _chapter_seq_of(_Sec()) == 5  # type: ignore[arg-type]

    class _SecNoChapter:
        id = "sec_test_y"
        chapter_id = ""
        chapter = None

    with pytest.raises(ValueError, match="无法确定节的章序号"):
        _chapter_seq_of(_SecNoChapter())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ★ 端到端：`extract_material` 不得对同一个块抽出两条知识点
# ---------------------------------------------------------------------------


def test_extract_material_extracts_each_block_once(session) -> None:  # noqa: ANN001
    """★ 真正的验收：**一个块只出一个知识点**，且四个节都有内容。

    这是「629 条里 462 条副本」的直接验收条件 —— 副本在数据上的特征就是
    **两条 KP 指向同一个 `source_block_id`**。这里用一份两章四节的合成材料跑完整抽取，
    断言这个特征为 0。

    注意全部用 **heading** 块：`_name_from_block` 对 heading 一定会给出名字
    （段落需要定义句式才成），这样"块数 == KP 数"是可以硬断言的，
    不会因为名字抽取规则变动而假绿。
    """
    from collections import Counter

    from app.extract.structural import extract_material
    from app.models import Chapter, Material, utc_now_iso

    session.add(
        Material(
            id="mat_dup",
            filename="dup.pdf",
            file_hash="dup".ljust(64, "0")[:64],
            stored_path="x.pdf",
            mime_type="application/pdf",
            size_bytes=1,
            source_type="pdf_text",
            status="done",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
    )
    # 两个章，每章两个节 —— **节的 seq 是章内的**，两章都有 seq 0/1
    session.add(Chapter(id="ch_test_000", material_id="mat_dup", title="章 A", seq=0))
    session.add(Chapter(id="ch_test_001", material_id="mat_dup", title="章 B", seq=1))
    session.commit()

    layout = [
        # (块 seq, 章 seq, 节 seq, 是否节标题)
        (0, 0, 0, True), (1, 0, 0, False), (2, 0, 0, False), (3, 0, 0, False),
        (4, 0, 1, True), (5, 0, 1, False),
        (6, 1, 0, True), (7, 1, 0, False), (8, 1, 0, False), (9, 1, 0, False),
        (10, 1, 1, True), (11, 1, 1, False),
    ]

    session.add_all([
        MaterialBlock(
            id=f"blk_dup_{s:05d}", material_id="mat_dup", seq=s, page_no=1,
            line_start=s + 1, line_end=s + 1, block_type="heading", heading_level=2,
            content_md=f"知识点名称 {s} 号", image_path=None, ocr_confidence=None,
        )
        for s, _, _, _ in layout
    ])
    for chapter_seq in (0, 1):
        for sec_seq in (0, 1):
            head = next(s for s, c, k, is_head in layout
                        if c == chapter_seq and k == sec_seq and is_head)
            session.add(
                Section(
                    id=f"sec_dup_{chapter_seq:03d}_{sec_seq:03d}",
                    material_id="mat_dup",
                    chapter_id=f"ch_test_{chapter_seq:03d}",
                    title=f"第 {chapter_seq}.{sec_seq} 节",
                    seq=sec_seq,
                    source_block_id=f"blk_dup_{head:05d}",
                )
            )
    session.commit()

    result = extract_material(session, "mat_dup")
    session.commit()

    from sqlalchemy import select

    from app.models import KnowledgePoint

    kps = session.scalars(
        select(KnowledgePoint).where(KnowledgePoint.material_id == "mat_dup")
    ).all()

    assert result["knowledge_points"] == len(layout), (
        f"返回的 KP 数应等于块数（每个块一个），实际 {result['knowledge_points']} / {len(layout)}"
    )
    assert len(kps) == len(layout), (
        f"落库的 KP 数应等于块数，实际 {len(kps)} / {len(layout)} —— "
        "多了就是同一个块被多个节各抽了一遍"
    )

    by_block = Counter(kp.source_block_id for kp in kps)
    duplicated = sorted(b for b, n in by_block.items() if n > 1)
    assert not duplicated, f"这些块被抽出了多条知识点（副本）：{duplicated}"

    # 四个节都有内容 —— 修复不能靠"少抽"来实现
    assert {kp.section_id for kp in kps} == {
        "sec_dup_000_000", "sec_dup_000_001", "sec_dup_001_000", "sec_dup_001_001",
    }, "有节一个知识点都没拿到（内容丢了）"

    # id 的「章 / 节」两段必须真的对应（而不是章段 == 节段）
    for kp in kps:
        section = session.get(Section, kp.section_id)
        chapter_seq = int(section.chapter_id.rsplit("_", 1)[-1])
        parts = kp.id.split("_")
        assert len(parts) == 5, f"id 形状不对：{kp.id}"
        assert parts[2] == f"{chapter_seq:03d}" and parts[3] == f"{section.seq:03d}", (
            f"id 的章/节段不对：{kp.id}"
            f"（应为 kp_<hash>_{chapter_seq:03d}_{section.seq:03d}_<seq>）"
        )
