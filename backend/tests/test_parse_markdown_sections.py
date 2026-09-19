"""带锚点 Markdown 与章 / 节骨架的测试（归属：P1）。SPEC §5.1。

守的是这几条契约：
  · **A1-6** `to_markdown()` 里页码与块 ID 都能被定位到 —— `<!-- page: N -->`
    只在**跨页处**出现一次，`<!-- block: blk_xxx -->` 每个块之前都有一条；
  · **A1-6** 锚点里的块 ID 由 `app.models.ids.block_id` 现算，与库里的主键同源；
  · **`split_sections()` 的章节号与标题保持材料原貌**（不归一化、不补编号）；
  · **A2-7** 同输入可复现 —— 同一份文件解析两次，Markdown 与块序列逐字段一致。

锚点格式是**稳定契约**（下游按它解析），所以这里断言的是字面量，不是"能跑就行"。
"""

from __future__ import annotations

from pathlib import Path

import docx
import pymupdf
import pytest

from app.models.ids import block_id, hash_bytes, material_id
from app.parse import (
    ParsedBlock,
    ParsedDocument,
    block_anchor,
    parse_docx,
    parse_material,
    section_markdown,
    split_outline,
    split_sections,
    to_markdown,
)

CJK_FONT = "china-s"  # PyMuPDF 内置中文字体，保证中文能进文本层
MAT_ID = material_id(hash_bytes(b"markdown fixture"))
OTHER_MAT_ID = material_id(hash_bytes(b"another fixture"))


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def make_pdf(path: Path) -> Path:
    """两页文本层 PDF：第 1 页两节，第 2 页一章，用来验证"跨页才插页锚点"。"""
    doc = pymupdf.open()

    p1 = doc.new_page()
    p1.insert_text((72, 72), "第1章 网络层", fontname=CJK_FONT, fontsize=18)
    p1.insert_text((72, 110), "1.1 路由基础", fontname=CJK_FONT, fontsize=13)
    p1.insert_text((72, 140), "路由是把分组从源送到目的的过程。", fontname=CJK_FONT, fontsize=10)

    p2 = doc.new_page()
    p2.insert_text((72, 110), "第2章 应用层", fontname=CJK_FONT, fontsize=18)
    p2.insert_text((72, 140), "应用层协议定义了报文格式与次序。", fontname=CJK_FONT, fontsize=10)

    doc.save(str(path))
    doc.close()
    return path


def make_docx(path: Path) -> Path:
    """DOCX 夹具（page_no 全为 None），用来验证"不该有页锚点"。"""
    document = docx.Document()
    document.add_heading("第1章 网络层", level=1)
    document.add_paragraph("路由是把分组从源送到目的的过程。")
    document.save(str(path))
    return path


def hand_made_doc() -> ParsedDocument:
    """手工搭一份产物：page_no 明确，便于把页锚点/块锚点的行为钉死。"""
    return ParsedDocument(
        source_type="pdf_text",
        page_count=2,
        blocks=[
            ParsedBlock(block_type="heading", content_md="第1章 网络层", page_no=1, heading_level=1),
            ParsedBlock(block_type="paragraph", content_md="本章介绍网络层。", page_no=1),
            ParsedBlock(
                block_type="heading", content_md="1.1 路由基础", page_no=1, heading_level=2
            ),
            ParsedBlock(
                block_type="paragraph",
                content_md="路由是把分组从源送到目的的过程。",
                page_no=2,
            ),
            ParsedBlock(block_type="heading", content_md="第2章 应用层", page_no=2, heading_level=1),
            ParsedBlock(
                block_type="paragraph", content_md="应用层协议定义了报文格式。", page_no=2
            ),
        ],
    )


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "text.pdf")


@pytest.fixture
def docx_file(tmp_path: Path) -> Path:
    return make_docx(tmp_path / "讲义.docx")


# ---------------------------------------------------------------------------
# Markdown 锚点（A1-6）
# ---------------------------------------------------------------------------


def test_markdown_contains_one_page_anchor_per_page_turn() -> None:
    """★ 页码锚点是**事件式**的：同一页只出现一次，跨页才插一行。"""
    md = to_markdown(hand_made_doc(), MAT_ID)
    assert md.count("<!-- page: 1 -->") == 1
    assert md.count("<!-- page: 2 -->") == 1
    assert md.index("<!-- page: 1 -->") < md.index("<!-- page: 2 -->")
    # 第 1 页有 3 块，但页码锚点只该有 1 个
    assert block_anchor(MAT_ID, 2) in md.split("<!-- page: 2 -->")[0]


def test_markdown_contains_a_block_anchor_for_every_block() -> None:
    """★ 每个块之前都要有块锚点，且 ID 与 `block_id(mat_id, seq)` 逐字一致。"""
    doc = hand_made_doc()
    md = to_markdown(doc, MAT_ID)
    for seq in range(len(doc.blocks)):
        assert block_anchor(MAT_ID, seq) in md
        assert block_id(MAT_ID, seq) in md
    # 锚点顺序 = 文档顺序
    positions = [md.index(block_anchor(MAT_ID, seq)) for seq in range(len(doc.blocks))]
    assert positions == sorted(positions)


def test_block_anchor_sits_right_before_its_content() -> None:
    """锚点被模型/人工用来回指原文，必须紧贴内容而不是飘在别处。"""
    md = to_markdown(hand_made_doc(), MAT_ID)
    assert f"{block_anchor(MAT_ID, 0)}\n# 第1章 网络层" in md
    assert f"{block_anchor(MAT_ID, 1)}\n本章介绍网络层。" in md
    assert f"{block_anchor(MAT_ID, 2)}\n## 1.1 路由基础" in md


def test_page_anchor_follows_the_first_block_of_that_page() -> None:
    md = to_markdown(hand_made_doc(), MAT_ID)
    # 第 2 页的第一块是 seq=3，页码锚点应出现在它的块锚点之前
    assert md.index("<!-- page: 2 -->") < md.index(block_anchor(MAT_ID, 3))


def test_separator_and_heading_prefix_are_rendered_once() -> None:
    """标题的 `#` 只从 `heading_level` 渲染一次，`content_md` 里不带 `#`。"""
    lines = to_markdown(hand_made_doc(), MAT_ID).splitlines()
    assert "# 第1章 网络层" in lines
    assert "## 1.1 路由基础" in lines
    assert "# 1.1 路由基础" not in lines
    assert "### 1.1 路由基础" not in lines
    assert all(not line.startswith("# #") for line in lines)


def test_block_ids_are_stable_across_documents_with_different_mat_id() -> None:
    """换一个材料 ID，锚点随之变化（不是硬编码的假 ID）。"""
    doc = hand_made_doc()
    assert block_anchor(MAT_ID, 0) != block_anchor(OTHER_MAT_ID, 0)
    assert block_anchor(MAT_ID, 0) in to_markdown(doc, MAT_ID)
    assert block_anchor(MAT_ID, 0) not in to_markdown(doc, OTHER_MAT_ID)


def test_start_seq_keeps_anchors_pointing_at_global_position() -> None:
    """切片重新从 0 编号会让锚点指向别的块 —— 比没有锚点更糟。"""
    doc = hand_made_doc()
    sliced = to_markdown(doc.blocks[3:5], MAT_ID, start_seq=3)
    assert block_anchor(MAT_ID, 3) in sliced
    assert block_anchor(MAT_ID, 4) in sliced
    assert block_anchor(MAT_ID, 0) not in sliced


def test_docx_markdown_has_no_page_anchor(docx_file: Path) -> None:
    """DOCX 的 page_no 全为 None：一个 `<!-- page: -->` 都不该冒出来。"""
    md = to_markdown(parse_docx(docx_file), MAT_ID)
    assert "<!-- page:" not in md
    assert "<!-- block:" in md


# ---------------------------------------------------------------------------
# 章 / 节骨架
# ---------------------------------------------------------------------------


def test_sections_follow_headings_and_keep_original_numbers() -> None:
    """★ 章号与标题保持材料原貌：`第1章` 不许被归一化成 `1`。"""
    sections = split_sections(hand_made_doc())
    assert [s.number for s in sections] == ["第1章", "1.1", "第2章"]
    assert [s.title for s in sections] == ["网络层", "路由基础", "应用层"]


def test_chapters_are_derived_from_heading_blocks() -> None:
    chapters = split_outline(hand_made_doc())
    assert [c.number for c in chapters] == ["第1章", "第2章"]
    assert [c.title for c in chapters] == ["网络层", "应用层"]
    assert [len(c.sections) for c in chapters] == [2, 1]
    assert [c.heading_seq for c in chapters] == [0, 4]


def test_sections_carry_their_chapter_and_block_range() -> None:
    """节自带所属章信息与块区间，下游按区间切 Markdown 就是"节级输入片段"。"""
    sections = split_sections(hand_made_doc())
    assert [s.chapter_seq for s in sections] == [0, 0, 1]
    assert [(s.start_seq, s.end_seq) for s in sections] == [(1, 1), (2, 3), (4, 5)]
    assert [s.block_count for s in sections] == [1, 2, 2]
    assert [s.seq for s in sections] == [0, 1, 0]


def test_section_markdown_uses_global_seq_for_anchors() -> None:
    """节级片段里的锚点必须指回**全局**块，而不是片段内的第 0 块。"""
    doc = hand_made_doc()
    second = split_sections(doc)[1]
    md = section_markdown(doc, second, MAT_ID)
    assert block_anchor(MAT_ID, 2) in md
    assert block_anchor(MAT_ID, 3) in md
    assert block_anchor(MAT_ID, 0) not in md


def test_sections_are_ordered_by_document_order() -> None:
    sections = split_sections(hand_made_doc())
    assert [s.heading_seq for s in sections] == sorted(s.heading_seq for s in sections)
    assert [s.start_seq for s in sections] == sorted(s.start_seq for s in sections)


def test_document_without_headings_is_a_single_section() -> None:
    """推不出骨架时给一个占位节，且**不编造**章节号。"""
    doc = ParsedDocument(
        source_type="pdf_text",
        page_count=1,
        blocks=[ParsedBlock(block_type="paragraph", content_md="只有正文。", page_no=1)],
    )
    sections = split_sections(doc)
    assert len(sections) == 1
    assert sections[0].number is None
    assert (sections[0].start_seq, sections[0].end_seq) == (0, 0)


def test_empty_document_has_no_sections() -> None:
    assert split_sections(ParsedDocument(source_type="pdf_text", page_count=0)) == []


# ---------------------------------------------------------------------------
# 可复现（A2-7）
# ---------------------------------------------------------------------------


def test_same_pdf_parses_to_identical_markdown(pdf_file: Path) -> None:
    """★ A2-7：两次解析的块序列与 Markdown 必须逐字段一致。"""
    first = parse_material(pdf_file)
    second = parse_material(pdf_file)
    assert first.blocks == second.blocks
    assert list(first.numbered()) == list(second.numbered())
    assert to_markdown(first, MAT_ID) == to_markdown(second, MAT_ID)


def test_same_docx_parses_to_identical_markdown(docx_file: Path) -> None:
    first = parse_material(docx_file)
    second = parse_material(docx_file)
    assert first.blocks == second.blocks
    assert to_markdown(first, MAT_ID) == to_markdown(second, MAT_ID)


def test_anchors_are_pure_functions_of_input() -> None:
    """锚点里不能有随机数/时间戳 —— 同输入必须同输出。"""
    doc = hand_made_doc()
    assert [to_markdown(doc, MAT_ID) for _ in range(3)] == [to_markdown(doc, MAT_ID)] * 3


def test_sections_are_reproducible(pdf_file: Path) -> None:
    first = parse_material(pdf_file)
    second = parse_material(pdf_file)
    assert split_sections(first) == split_sections(second)
    assert split_outline(first) == split_outline(second)
