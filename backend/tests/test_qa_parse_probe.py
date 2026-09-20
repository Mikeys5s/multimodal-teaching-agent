"""QA 独立验证 · 场景 9：页眉 / 页脚 / 页码行的噪声块。

本文件原先钉住的是**第一批**的版式噪声行为（页眉短行与页码行都会各自产出一个
块 —— 3 页的材料因此产出 9 块）。**去噪已落地，期望已更新**为去噪后的正确行为：

    3 页 × (页眉 + 正文 + 页码) 的材料，只应产出 **3 个正文块**：
    页眉（跨页重复的书名短行）与页码（页脚带里的纯数字行）都被去噪规则去掉，
    不再进 Markdown、不再进库、也不会再被当成知识点来源（"1"、"2"、"3" 这种页码行）。

同时保留两条**不随去噪变化**的结构要求：页眉页脚不改变正文的先后顺序与页码归属。

去噪的判定是"多信号合取"（页边距带 + 版心外 + 跨页重复 + 与相邻内容隔离），
详见 `app/parse/pdf.py` 模块 docstring 与 `tests/test_parse_denoise.py` 的对抗性用例。
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


def test_repeated_header_and_page_number_lines_are_denoised(tmp_path: Path) -> None:
    """★ 场景 9（去噪已落地）：页眉与页码行都被去掉，只剩 3 个正文块。

    页眉 `网络原理讲义` 在 3 页上出现在同一垂直位置（跨页重复 ≥ 50% 的页）、
    在页边距带里、且在版心之外、又与正文有明显空隙 —— 四条信号同时成立，判为页眉。
    页码 `1`／`2`／`3` 同理（页脚带），并且它们**再也不会变成 heading**。
    """
    doc = parse_pdf(make_paged_pdf(tmp_path / "noise.pdf", pages=3))

    contents = [b.content_md for b in doc.blocks]
    assert contents == [
        "第1页的正文内容，这一页讲了一些具体的东西。",
        "第2页的正文内容，这一页讲了一些具体的东西。",
        "第3页的正文内容，这一页讲了一些具体的东西。",
    ]
    assert len(doc.blocks) == 3, "3 页 × 3 行：页眉与页码应当被去噪，只剩正文"
    assert all(b.block_type == "paragraph" for b in doc.blocks)


def test_page_numbers_are_removed_and_never_become_headings(tmp_path: Path) -> None:
    """★ 场景 9（去噪已落地）：页码行**整块消失**，更不会成为一级标题。

    第一批里单独一行的 `12` 会落成一个块；成因是 `blocks.split_heading_number`
    把纯数字当成 depth=1 的编号。现在有两道拦截：
      · **heading 否决规则** —— 整行只有编号、没有标题文字的单级编号不作 heading；
      · **去噪** —— 页脚带里的纯数字行直接不进块表。
    """
    doc = parse_pdf(make_paged_pdf(tmp_path / "noise.pdf", pages=3))
    assert [b.content_md for b in doc.blocks if b.content_md.strip().isdigit()] == []
    assert all(b.block_type != "heading" for b in doc.blocks)


def test_denoise_is_reported_as_an_uncertain_note(tmp_path: Path) -> None:
    """★ 去噪**不静默丢内容**：删掉的块数与分类必须如实登记在存疑说明里。"""
    doc = parse_pdf(make_paged_pdf(tmp_path / "noise.pdf", pages=3))
    notes = [n for n in doc.uncertain_notes if "页眉" in n.message]
    assert len(notes) == 1, f"去噪没有留下可核对的说明：{doc.uncertain_notes}"
    note = notes[0]
    assert note.kind == "other"
    assert note.severity == "low"
    assert "6 个" in note.message, f"删了 6 块（3 页眉 + 3 页码）却没报准数：{note.message!r}"
    assert "页眉 3 块" in note.message
    assert "页码 3 块" in note.message


def test_header_noise_does_not_break_paragraph_order(tmp_path: Path) -> None:
    """去噪后正文块的相对顺序仍然正确（页码不回跳）。"""
    doc = parse_pdf(make_paged_pdf(tmp_path / "noise.pdf", pages=3))
    body_pages = [b.page_no for b in doc.blocks if "正文内容" in b.content_md]
    assert body_pages == [1, 2, 3]


def test_body_lines_keep_their_own_page_no_after_denoise(tmp_path: Path) -> None:
    """正文块至少要被正确钉到所在页（否则溯源会指向别处）。"""
    doc = parse_pdf(make_paged_pdf(tmp_path / "noise.pdf", pages=2))
    body_blocks = [b for b in doc.blocks if "正文内容" in b.content_md]
    assert [b.page_no for b in body_blocks] == [1, 2]
    assert doc.page_count == 2


def test_short_two_page_document_keeps_its_edge_lines(tmp_path: Path) -> None:
    """★ 两页的文档**不做**页眉页脚去噪 —— 重复页数不够，宁可漏删。

    "跨页重复"这条信号要求覆盖 ≥ 50% 的页面且**不少于 3 页**
    （`app.parse.pdf.RUNNING_BAND_MIN_PAGES`）。2 页的重复不足以证明"每页都来一遍"，
    这时方向取"宁可漏删"：留下几个噪声块，也不能拿"碰巧重了两页"的正文冒险。
    """
    doc = parse_pdf(make_paged_pdf(tmp_path / "noise2.pdf", pages=2))
    contents = [b.content_md for b in doc.blocks]
    assert contents == [
        "网络原理讲义",
        "第1页的正文内容，这一页讲了一些具体的东西。",
        "1",
        "网络原理讲义",
        "第2页的正文内容，这一页讲了一些具体的东西。",
        "2",
    ]
