"""QA 独立验证 · 场景 10：多栏排版 PDF 的块顺序。

程序化生成一份双栏页面（左栏 4 行、右栏 4 行，两栏行基线完全对齐），实测结果：

    左栏的 4 行合并成**一个**块、右栏的 4 行合并成**一个**块；
    块顺序是"左栏整块 → 右栏整块"，**没有出现左右交错的乱序**。

两点如实记录：
  1. 顺序正确 —— 两栏内容没有互相穿插（这是好消息）；
  2. 一栏的 4 行会合并成一个块：这 4 行既没有段落起始特征（行距是单倍、无首行
     缩进、上一行不以句末标点收尾），按 `_group_lines` 的段落判据就是"同一段的
     折行"。若这 4 行原本是 4 条并列要点，段边界会丢 —— 判据只看版式，看不出
     语义上的并列关系。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.parse import parse_pdf

CJK_FONT = "china-s"
LINE_STEP = 14.0


def _w(page: pymupdf.Page, x: float, y: float, text: str, size: float = 10) -> None:
    page.insert_text((x, y), text, fontname=CJK_FONT, fontsize=size)


def make_two_column_pdf(path: Path, rows: int = 4) -> Path:
    """两栏，行基线完全对齐（最容易触发交错乱序的排法）。"""
    doc = pymupdf.open()
    page = doc.new_page()
    for i in range(rows):
        _w(page, 60, 100 + i * LINE_STEP, f"左栏第{i + 1}行的内容")
    for i in range(rows):
        _w(page, 330, 100 + i * LINE_STEP, f"右栏第{i + 1}行的内容")
    doc.save(str(path))
    doc.close()
    return path


def test_two_column_blocks_do_not_interleave(tmp_path: Path) -> None:
    """★ 场景 10：左右两栏不得交错 —— 左栏内容必须整体出现在右栏之前。"""
    doc = parse_pdf(make_two_column_pdf(tmp_path / "columns.pdf"))
    contents = [b.content_md for b in doc.blocks]
    assert len(contents) == 2, f"预期左/右各一块，实际 {contents!r}"

    left, right = contents
    assert "左栏第1行的内容" in left and "左栏第4行的内容" in left
    assert "右栏第1行的内容" not in left
    assert "右栏第1行的内容" in right and "左栏第1行的内容" not in right


def test_two_column_left_before_right_in_markdown(tmp_path: Path) -> None:
    """Markdown 输出里同样是左栏在前、右栏在后，没有一左一右地跳。"""
    from app.parse import to_markdown

    doc = parse_pdf(make_two_column_pdf(tmp_path / "columns.pdf"))
    md = to_markdown(doc, "mat_0123abcd")
    assert md.index("左栏第1行的内容") < md.index("右栏第1行的内容")


def test_two_column_rows_keep_row_order_inside_each_column(tmp_path: Path) -> None:
    """★ 场景 10：列内 4 行必须保持 1→4 的顺序（不能倒序或乱序）。"""
    doc = parse_pdf(make_two_column_pdf(tmp_path / "columns.pdf"))
    # 每栏一块、共两块（同文件另一条用例已断言 len(doc.blocks) == 2），
    # 这里用 strict=True 把"块数与栏数一致"变成循环本身的前置检查
    for block, column in zip(doc.blocks, ("左栏", "右栏"), strict=True):
        positions = [block.content_md.index(f"{column}第{i}行") for i in range(1, 5)]
        assert positions == sorted(positions), f"{column}行序错乱：{block.content_md!r}"


def test_two_column_rows_are_merged_into_one_block_per_column(tmp_path: Path) -> None:
    """★ 场景 10：一栏的 4 行被合并成一块。

    两栏行基线完全对齐、行距 14pt（≈单倍行距），4 行既没有首行缩进、上一行也不以
    句末标点收尾 —— 按 `_group_lines` 的段落判据就是"同一段的折行"，因此合并。
    若这 4 行原本是 4 个独立要点，段边界就丢了：判据只看版式，看不出并列关系。
    """
    doc = parse_pdf(make_two_column_pdf(tmp_path / "columns.pdf"))
    assert len(doc.blocks) == 2
    assert doc.blocks[0].content_md == "".join(f"左栏第{i}行的内容" for i in range(1, 5))
    assert doc.blocks[1].content_md == "".join(f"右栏第{i}行的内容" for i in range(1, 5))


def test_two_column_page_is_not_classified_as_scan(tmp_path: Path) -> None:
    """双栏页有文本层、没有图 → 必须走文本抽取，不能被判成扫描版。"""
    doc = parse_pdf(make_two_column_pdf(tmp_path / "columns.pdf"))
    assert doc.source_type == "pdf_text"
    assert doc.blocks


def test_two_column_parse_is_reproducible(tmp_path: Path) -> None:
    """多栏页的块顺序也必须是可复现的（`sort=True` 的作用）。"""
    path = make_two_column_pdf(tmp_path / "columns.pdf")
    assert parse_pdf(path) == parse_pdf(path)
