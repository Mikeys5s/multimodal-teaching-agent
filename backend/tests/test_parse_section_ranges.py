"""`ParsedSection` 的**区间边界语义**不变量（P2 review 建议③）。

为什么单独为一个 dataclass 写一整个文件
--------------------------------------
区间是 `[start_seq, end_seq]` 这一个约定撑起的东西：下游按它切"节级输入片段"，
知识点就挂在这片段上。它差一个块**不会让任何地方报错** —— 只会让某个知识点
悄悄挂到相邻的节上，而"KP 挂对节"是硬验收指标。所以这里把语义逐条钉死成用例：

  1. **左闭右闭**，切片 `blocks[start_seq : end_seq + 1]`，且 `start_seq <= end_seq`
     —— 永远拿不到空列表；
  2. **标题块归属**：叶子标题块**属于**本节（`start_seq == heading_seq`）；
     容器（有子标题的标题）的导语节**不含**容器标题块
     （`start_seq == heading_seq + 1`）→ 不变量 `heading_seq - start_seq ∈ {-1, 0}`；
  3. **相邻节不重叠**：`前一节.end_seq < 后一节.start_seq`，且按文档顺序排列；
  4. **"空节"**（标题下没有正文）表示为 `start_seq == end_seq == heading_seq`、
     `block_count == 1` —— 切片得到**那一行标题**本身，不是 `[]`；
  5. **节内 `page_no` 单调不减**。

另外两段：非法构造必须**当场** `ValueError`（而不是产出一个错位的区间），
以及骨架的跨节不变量检查器本身真的会拦住重叠。
"""

from __future__ import annotations

import pytest

from app.parse.blocks import ParsedBlock, ParsedDocument
from app.parse.sections import (
    ParsedSection,
    _assert_range_contract,
    split_sections,
)


def _h(text: str, level: int, page: int | None = 1) -> ParsedBlock:
    return ParsedBlock(block_type="heading", content_md=text, heading_level=level, page_no=page)


def _p(text: str, page: int | None = 1) -> ParsedBlock:
    return ParsedBlock(block_type="paragraph", content_md=text, page_no=page)


def _doc(*blocks: ParsedBlock) -> ParsedDocument:
    return ParsedDocument(source_type="pdf_text", blocks=list(blocks))


def _slice(doc: ParsedDocument, section: ParsedSection) -> list[str]:
    """按 docstring 写死的方式切片 —— 用例一律用这一种切法，别再自己写 +1。"""
    return [b.content_md for b in doc.blocks[section.start_seq : section.end_seq + 1]]


# ---------------------------------------------------------------------------
# 1. 左闭右闭 + 区间非空（切片永远不会是 []）
# ---------------------------------------------------------------------------


def test_ranges_are_closed_on_both_ends() -> None:
    """★ 区间左闭右闭：块的集合恰好是 `blocks[start : end+1]`，不多不少一个。"""
    doc = _doc(_h("1 Alpha", 1), _p("alpha body"), _h("2 Beta", 1), _p("beta body"))
    sections = split_sections(doc)

    assert [(s.start_seq, s.end_seq) for s in sections] == [(0, 1), (2, 3)]
    assert _slice(doc, sections[0]) == ["1 Alpha", "alpha body"]
    assert _slice(doc, sections[1]) == ["2 Beta", "beta body"]
    # 若区间是左闭右开，下面这两条会少最后一块
    assert doc.blocks[sections[0].end_seq].content_md == "alpha body"
    assert doc.blocks[sections[1].end_seq].content_md == "beta body"


def test_no_section_has_an_inverted_or_empty_range() -> None:
    """★ 实现里**不存在** `end_seq < start_seq` 的空区间写法 —— 切片不会是 []。"""
    docs = [
        _doc(_h("1 Alpha", 1), _p("body"), _h("2 Beta", 1), _p("body")),
        _doc(_h("1 A", 1), _h("1.1 B", 2), _p("body")),
        _doc(_h("1 A", 1), _p("intro"), _h("1.1 B", 2), _p("body")),
        _doc(_h("1 A", 1), _h("2 B", 1), _p("body")),
        _doc(_p("no heading at all")),
        _doc(_h("1 Only", 1)),
    ]
    checked = 0
    for doc in docs:
        for section in split_sections(doc):
            checked += 1
            assert section.start_seq <= section.end_seq
            assert section.block_count == section.end_seq - section.start_seq + 1
            assert section.block_count >= 1
            assert _slice(doc, section) != []
    assert checked >= 7, f"取样的节太少（{checked}），用例没覆盖到几条分支"


# ---------------------------------------------------------------------------
# 2. 标题块归属 + heading_seq / start_seq 不变量
# ---------------------------------------------------------------------------


def test_leaf_section_includes_its_own_heading_block() -> None:
    """★ 叶子标题（无子标题）：标题块**属于本节**，切片第一块就是标题。"""
    doc = _doc(_h("1 Alpha", 1), _p("alpha body"))
    (section,) = split_sections(doc)

    assert section.heading_seq == 0
    assert section.start_seq == 0, "叶子节的标题块必须落在区间内"
    assert _slice(doc, section) == ["1 Alpha", "alpha body"]


def test_container_intro_section_excludes_the_container_heading_block() -> None:
    """★ 容器标题（有子标题）：它的导语节**不含**容器标题块（start = heading_seq + 1）。"""
    doc = _doc(_h("1 Alpha", 1), _p("intro"), _h("1.1 One", 2), _p("one body"))
    sections = split_sections(doc)

    intro, leaf = sections
    assert (intro.number, intro.title) == ("1", "Alpha"), "容器标题的编号/标题由导语节继承"
    assert intro.heading_seq == 0
    assert intro.start_seq == 1, "导语节必须跳过容器标题块"
    assert intro.end_seq == 1
    assert "1 Alpha" not in _slice(doc, intro), "容器标题块不该出现在导语节里"

    assert leaf.heading_seq == 2
    assert leaf.start_seq == 2
    assert _slice(doc, leaf) == ["1.1 One", "one body"]


def test_every_section_satisfies_heading_seq_offset_invariant() -> None:
    """★ 不变量：`heading_seq - start_seq ∈ {-1, 0}`（-1 = 容器导语节，0 = 叶子）。"""
    doc = _doc(
        _h("1 A", 1),
        _p("a intro"),
        _h("1.1 B", 2),
        _p("b intro"),
        _h("1.1.1 C", 3),
        _p("c body"),
        _h("2 D", 1),
        _p("d body"),
    )
    sections = split_sections(doc)
    assert sections, "样本没产出任何节"
    for section in sections:
        assert section.heading_seq - section.start_seq in (-1, 0), (
            f"sec{section.seq} 的 heading_seq={section.heading_seq} / "
            f"start_seq={section.start_seq} 不满足不变量"
        )


def test_placeholder_sections_have_no_real_heading_block() -> None:
    """★ 占位节（`全文` / `前言`）没有真实标题块，`blocks[0]` 不保证是 heading。"""
    no_heading = _doc(_p("第一段"), _p("第二段"))
    (section,) = split_sections(no_heading)
    assert section.title == "全文"
    assert section.heading_seq == 0
    assert not no_heading.blocks[0].is_heading, "本用例的前提：块 0 不是标题块"

    preamble = _doc(_p("封面文字"), _h("1 Alpha", 1), _p("body"))
    first, second = split_sections(preamble)
    assert first.title == "前言"
    assert (first.start_seq, first.end_seq) == (0, 0)
    assert second.start_seq == 1

    # 占位节自身仍要满足同一条不变量
    for section in (first, second):
        assert section.heading_seq - section.start_seq in (-1, 0)


# ---------------------------------------------------------------------------
# 3. 相邻节不重叠 + 文档顺序
# ---------------------------------------------------------------------------


def test_adjacent_sections_never_overlap() -> None:
    """★ 相邻节 `prev.end_seq < next.start_seq` —— 同一个块不会被投喂给两个节。"""
    doc = _doc(
        _h("1 A", 1),
        _p("a intro"),
        _h("1.1 B", 2),
        _p("b body"),
        _h("1.2 C", 2),
        _p("c body"),
        _h("2 D", 1),
        _p("d body"),
    )
    sections = split_sections(doc)
    assert len(sections) >= 4, f"样本产出的节太少（{len(sections)}），覆盖不到相邻关系"

    for prev, nxt in zip(sections, sections[1:], strict=False):
        assert prev.end_seq < nxt.start_seq, (
            f"sec{prev.seq}[{prev.start_seq},{prev.end_seq}] 与 "
            f"sec{nxt.seq}[{nxt.start_seq},{nxt.end_seq}] 重叠"
        )

    # 顺序：既按 start_seq 也按 heading_seq 递增
    assert [s.start_seq for s in sections] == sorted(s.start_seq for s in sections)
    assert [s.heading_seq for s in sections] == sorted(s.heading_seq for s in sections)


def test_only_the_container_heading_blocks_fall_outside_every_section_range() -> None:
    """★ 把"空洞"钉死：不落在任何节区间里的块，**恰好**是有子标题的容器标题块。

    这条是"不丢块"的精确表述 —— 容器标题块不进任何节区间（它是骨架节点），
    但它在骨架里有唯一归属（容器 + 它的导语节/子节）。除此之外不该再有空洞。
    """
    doc = _doc(
        _h("1 A", 1),  # 容器（有 1.1 / 1.2）→ 空洞
        _p("a intro"),
        _h("1.1 B", 2),  # 容器（有 1.1.1）→ 空洞
        _p("b intro"),
        _h("1.1.1 C", 3),  # 叶子 → 属于节
        _p("c body"),
        _h("1.2 D", 2),  # 叶子 → 属于节
        _p("d body"),
    )
    sections = split_sections(doc)
    covered = {seq for s in sections for seq in range(s.start_seq, s.end_seq + 1)}
    holes = sorted(set(range(len(doc.blocks))) - covered)

    assert holes == [0, 2], f"空洞应恰好是两个容器标题块，实际 {holes}"
    assert [doc.blocks[h].content_md for h in holes] == ["1 A", "1.1 B"]
    assert all(doc.blocks[h].is_heading for h in holes), "空洞必须都是标题块"
    assert [s.start_seq for s in sections] == [1, 3, 4, 6]


def test_sections_are_contiguous_within_a_chapter_except_container_headings() -> None:
    """★ 同一章内，相邻节除了"容器标题造成的 1 块空洞"外应当无缝相接。"""
    doc = _doc(
        _h("1 A", 1),
        _p("a body"),
        _h("1.1 B", 2),
        _p("b body"),
        _h("1.2 C", 2),
        _p("c body"),
    )
    sections = split_sections(doc)
    assert len(sections) == 3, f"预期 3 节，实际 {len(sections)}"
    for prev, nxt in zip(sections, sections[1:], strict=False):
        gap = nxt.start_seq - prev.end_seq - 1
        assert gap in (0, 1), f"相邻节之间的空洞异常：{gap} 块（只允许 0 或 1）"


# ---------------------------------------------------------------------------
# 4. "空节" / 只有标题的节 / 单块节
# ---------------------------------------------------------------------------


def test_section_with_heading_only_is_represented_as_start_equals_end() -> None:
    """★ "空节"（标题下没有正文）= `start_seq == end_seq == heading_seq`、
    `block_count == 1`，切片拿到的是**那一行标题**，不是 `[]`。"""
    doc = _doc(_h("1 Alpha", 1), _h("2 Beta", 1), _p("beta body"))
    alpha, beta = split_sections(doc)

    assert (alpha.start_seq, alpha.end_seq, alpha.heading_seq) == (0, 0, 0)
    assert alpha.block_count == 1
    assert _slice(doc, alpha) == ["1 Alpha"], "空节仍含标题块本身，切片不是 []"

    assert (beta.start_seq, beta.end_seq) == (1, 2)
    assert _slice(doc, beta) == ["2 Beta", "beta body"]


def test_single_block_document_produces_a_single_block_section() -> None:
    """★ 单块节：整份材料只有一行标题。"""
    doc = _doc(_h("1 Only", 1))
    (section,) = split_sections(doc)

    assert (section.start_seq, section.end_seq) == (0, 0)
    assert section.block_count == 1
    assert section.heading_seq == 0
    assert _slice(doc, section) == ["1 Only"]


def test_empty_document_has_no_sections_at_all() -> None:
    """真正的空输入**不产出占位节**（区别于"空节"，后者仍产出一节）。"""
    assert split_sections(_doc()) == []


# ---------------------------------------------------------------------------
# 5. 节内 page_no 单调不减
# ---------------------------------------------------------------------------


def test_page_no_is_non_decreasing_inside_every_section() -> None:
    """★ 区间是文档顺序上的连续切片 → 节内 `page_no` 不可能来回跳页。"""
    doc = _doc(
        _h("1 A", 1, page=1),
        _p("a1", page=1),
        _p("a2", page=2),
        _h("1.1 B", 2, page=2),
        _p("b1", page=2),
        _p("b2", page=3),
    )
    sections = split_sections(doc)
    assert len(sections) == 2

    for section in sections:
        pages = [
            b.page_no
            for b in doc.blocks[section.start_seq : section.end_seq + 1]
            if b.page_no is not None
        ]
        assert pages == sorted(pages), f"sec{section.seq} 的 page_no 不单调：{pages}"
        assert pages, "本用例的每个节都应当至少有一个带页码的块"

    # 钉具体值，避免上面的断言在"所有 page_no 都是 None"时空转通过
    # ch0 sec0 = 容器 A 的导语节 [1,2]（a1/a2）；ch0 sec1 = 叶子 1.1 B [3,5]
    assert [(s.start_seq, s.end_seq) for s in sections] == [(1, 2), (3, 5)]
    assert [
        b.page_no for b in doc.blocks[sections[0].start_seq : sections[0].end_seq + 1]
    ] == [1, 2]
    assert [
        b.page_no for b in doc.blocks[sections[1].start_seq : sections[1].end_seq + 1]
    ] == [2, 2, 3]


def test_page_no_check_tolerates_documents_without_pages() -> None:
    """DOCX 类材料的 `page_no` 全为 None —— 不应被当成"页码倒置"。"""
    doc = _doc(_h("1 A", 1, page=None), _p("body", page=None))
    (section,) = split_sections(doc)
    assert (section.start_seq, section.end_seq) == (0, 1)
    assert all(b.page_no is None for b in doc.blocks)


# ---------------------------------------------------------------------------
# 6. 非法构造当场报错（不是产出一个错位的区间）
# ---------------------------------------------------------------------------


def _make_section(**overrides: int) -> ParsedSection:
    fields = dict(
        chapter_seq=0,
        chapter_number="1",
        chapter_title="Alpha",
        chapter_heading_seq=0,
        seq=0,
        number="1",
        title="Alpha",
        heading_seq=0,
        start_seq=0,
        end_seq=0,
    )
    fields.update(overrides)
    return ParsedSection(**fields)  # type: ignore[arg-type]


def test_inverted_range_is_rejected_at_construction() -> None:
    """★ `end_seq < start_seq` 必须在构造时炸掉 —— 这是"差一个块"最危险的形式。"""
    _make_section(start_seq=1, end_seq=1, heading_seq=1)  # 合法，先确认基线不报
    with pytest.raises(ValueError, match="区间必须非空"):
        _make_section(start_seq=2, end_seq=1, heading_seq=2)


def test_heading_seq_outside_the_two_legal_offsets_is_rejected() -> None:
    """★ `heading_seq` 只能是 `start_seq`（叶子）或 `start_seq - 1`（容器导语）。"""
    _make_section(start_seq=1, end_seq=1, heading_seq=0)  # 容器导语节
    with pytest.raises(ValueError, match="heading_seq"):
        _make_section(start_seq=2, end_seq=3, heading_seq=0)
    with pytest.raises(ValueError, match="heading_seq"):
        _make_section(start_seq=2, end_seq=3, heading_seq=3)


def test_negative_seq_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="非负"):
        _make_section(start_seq=0, end_seq=0, heading_seq=-1)


# ---------------------------------------------------------------------------
# 7. 跨节不变量检查器真的会拦住重叠
# ---------------------------------------------------------------------------


def test_contract_checker_rejects_overlapping_ranges() -> None:
    """★ 反向验证：`_assert_range_contract` 对重叠区间必须报错。

    没有这一条，"加断言"就只是加了一句永远不执行的装饰 —— 构造方式现在是对的，
    不代表断言本身有效。
    """
    blocks = [_h("1 A", 1), _p("a body"), _p("b body")]
    overlapping = [
        _make_section(seq=0, start_seq=0, end_seq=2, heading_seq=0),
        _make_section(seq=1, start_seq=2, end_seq=2, heading_seq=2),
    ]
    with pytest.raises(ValueError, match="重叠"):
        _assert_range_contract(blocks, overlapping)


def test_contract_checker_rejects_out_of_order_and_out_of_bounds() -> None:
    blocks = [_h("1 A", 1), _p("a body"), _p("b body")]

    out_of_order = [
        _make_section(seq=0, start_seq=2, end_seq=2, heading_seq=2),
        _make_section(seq=1, start_seq=0, end_seq=0, heading_seq=0),
    ]
    with pytest.raises(ValueError, match="文档顺序"):
        _assert_range_contract(blocks, out_of_order)

    out_of_bounds = [_make_section(seq=0, start_seq=0, end_seq=3, heading_seq=0)]
    with pytest.raises(ValueError, match="越界"):
        _assert_range_contract(blocks, out_of_bounds)


def test_contract_checker_rejects_non_monotonic_page_no() -> None:
    blocks = [_h("1 A", 1, page=2), _p("back to page 1", page=1)]
    bad = [_make_section(seq=0, start_seq=0, end_seq=1, heading_seq=0)]
    with pytest.raises(ValueError, match="page_no"):
        _assert_range_contract(blocks, bad)


def test_contract_checker_accepts_a_normal_outline() -> None:
    """正例：真实骨架能通过检查（证明上面的报错不是"一律报错"）。"""
    doc = _doc(
        _h("1 A", 1, page=1),
        _p("a intro", page=1),
        _h("1.1 B", 2, page=1),
        _p("b body", page=2),
    )
    sections = split_sections(doc)
    _assert_range_contract(doc.blocks, sections)
