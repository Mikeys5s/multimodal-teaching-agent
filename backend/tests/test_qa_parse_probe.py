"""QA 独立验证 · 场景 9：页眉 / 页脚 / 页码行的噪声块。

本文件钉住的是**当前**的版式噪声行为（页眉页脚去噪还没做，属于后续批次）：

    实测：每页的页眉短行（"网络原理讲义"）与页码行（单独一行的 "12"）都会
    各自产出一个 `paragraph` 块 —— 3 页的材料因此产出 9 块（3 页 × 3 行）。

影响：这些块会进入 Markdown、进库、被当成"节内容"投喂给抽取模型，
可能被误当成知识点来源（例如"1"、"2"、"3" 这种页码行）。当前实现没有任何
页眉/页脚识别或过滤 —— 断言如实反映这一点，等去噪落地后随新预期一起更新。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.parse import parse_pdf

CJK_FONT = "china-s"


def _w(page: pymupdf.Page, x: float, y: float, text: str, size: float = 10) -> None:
    page.insert_text((x, y), text, fontname=CJK_FONT, fontsize=size)


def make_paged_pdf(path: Path, pages: int = 3) -> Path:
    """每页 = 页眉短行 + 一行正文 + 页脚纯数字页码。"""
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        _w(page, 72, 60, "网络原理讲义", 8)  # 页眉
        _w(page, 72, 120, f"第{i + 1}页的正文内容，这一页讲了一些具体的东西。")
        _w(page, 300, 780, f"{i + 1}", 9)  # 页码
    doc.save(str(path))
    doc.close()
    return path


def test_repeated_header_and_page_number_lines_become_blocks(tmp_path: Path) -> None:
    """★ 场景 9：页眉与页码行都会变成独立的 `paragraph` 块（当前无去噪）。"""
    doc = parse_pdf(make_paged_pdf(tmp_path / "noise.pdf", pages=3))

    contents = [b.content_md for b in doc.blocks]
    assert contents == [
        "网络原理讲义",
        "第1页的正文内容，这一页讲了一些具体的东西。",
        "1",
        "网络原理讲义",
        "第2页的正文内容，这一页讲了一些具体的东西。",
        "2",
        "网络原理讲义",
        "第3页的正文内容，这一页讲了一些具体的东西。",
        "3",
    ]
    assert len(doc.blocks) == 9, "3 页 × 3 行：噪声行没有被任何规则过滤掉"


def test_pure_number_line_is_kept_as_a_paragraph_not_a_heading(tmp_path: Path) -> None:
    """★ 场景 9：单独一行的 "12" 会落成 `paragraph`。

    页码是纯数字，`split_heading_number` 能把它拆成编号（depth=1），但因为
    单级编号要过"字号不小于正文字号"这道闸（页码通常更小），它没被误判成标题 ——
    这一点是好的；但它仍然是一个内容块，会进 Markdown 与库。
    """
    doc = parse_pdf(make_paged_pdf(tmp_path / "noise.pdf", pages=3))
    page_number_blocks = [b for b in doc.blocks if b.content_md.strip().isdigit()]
    assert [b.content_md for b in page_number_blocks] == ["1", "2", "3"]
    for block in page_number_blocks:
        assert block.block_type == "paragraph"
        assert block.heading_level is None


def test_noise_lines_keep_their_own_page_no(tmp_path: Path) -> None:
    """噪声块至少要被正确钉到所在页（否则溯源会指向别处）。"""
    doc = parse_pdf(make_paged_pdf(tmp_path / "noise.pdf", pages=2))
    header_blocks = [b for b in doc.blocks if b.content_md == "网络原理讲义"]
    assert [b.page_no for b in header_blocks] == [1, 2]
    assert doc.page_count == 2


def test_header_noise_does_not_break_paragraph_order(tmp_path: Path) -> None:
    """噪声插在中间时，正文块的相对顺序仍然正确（页码不回跳）。"""
    doc = parse_pdf(make_paged_pdf(tmp_path / "noise.pdf", pages=3))
    body_pages = [b.page_no for b in doc.blocks if "正文内容" in b.content_md]
    assert body_pages == [1, 2, 3]
