"""QA 独立验证 · 图片处理口径：有图必须吭声、但**不许编图注**。

本批次没有图注（image_caption）识别能力，所以一条纪律是"不猜"：

  · 文本层 PDF 里出现图片时，**不能**产出任何 `image_caption` 块
    （编一个标题就是造假，而图注会被下游当成知识点来源）；
  · 但也不能不吭声 —— 必须给一条"这份材料里有 N 张图，图片内文字未纳入"
    的低优先级存疑说明，让评审和用户看得见。

本文件同时固定"图片块不参与正文抽取"与"扫描版判定优先于文本抽取"的边界。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.parse import parse_pdf

CJK_FONT = "china-s"


def _w(page: pymupdf.Page, x: float, y: float, text: str, size: float = 10) -> None:
    page.insert_text((x, y), text, fontname=CJK_FONT, fontsize=size)


def _grey_pixmap() -> pymupdf.Pixmap:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200))
    pix.clear_with(180)
    return pix


def make_text_pdf_with_image(path: Path, images: int = 1) -> Path:
    """有文本层、同时内嵌图片的 PDF（例如教材里的插图）。"""
    doc = pymupdf.open()
    page = doc.new_page()
    _w(page, 72, 72, "第1章 网络拓扑", 18)
    _w(page, 72, 110, "下图展示了典型的三层网络拓扑结构。")
    for i in range(images):
        page.insert_image(pymupdf.Rect(72, 140 + i * 120, 272, 250 + i * 120), pixmap=_grey_pixmap())
    doc.save(str(path))
    doc.close()
    return path


def test_image_never_becomes_an_image_caption_block(tmp_path: Path) -> None:
    """★ 不许编图注：图片不产出任何 `image_caption` 块。"""
    doc = parse_pdf(make_text_pdf_with_image(tmp_path / "fig.pdf"))
    assert doc.source_type == "pdf_text"
    assert all(b.block_type != "image_caption" for b in doc.blocks)
    assert all(b.image_path is None for b in doc.blocks)


def test_image_presence_is_reported_as_an_uncertain_note(tmp_path: Path) -> None:
    """★ 有图必须留一条中文存疑说明（"图片内的文字尚未纳入"）。"""
    doc = parse_pdf(make_text_pdf_with_image(tmp_path / "fig.pdf", images=1))
    image_notes = [n for n in doc.uncertain_notes if "图片" in n.message]
    assert len(image_notes) == 1
    note = image_notes[0]
    assert note.kind == "other"
    assert note.severity == "low"
    assert "1 张图片" in note.message
    assert "人工核对" in note.message


def test_image_count_is_reported_accurately(tmp_path: Path) -> None:
    """说明里的张数要和实际张数一致（两个图各自计数）。"""
    doc = parse_pdf(make_text_pdf_with_image(tmp_path / "fig2.pdf", images=2))
    note = next(n for n in doc.uncertain_notes if "图片" in n.message)
    assert "2 张图片" in note.message


def test_document_without_images_has_no_image_note(tmp_path: Path) -> None:
    """没图就别提图 —— 无端的存疑说明会让用户以为材料有问题。"""
    doc = pymupdf.open()
    page = doc.new_page()
    _w(page, 72, 100, "纯文字内容，没有任何插图。")
    path = tmp_path / "plain.pdf"
    doc.save(str(path))
    doc.close()

    parsed = parse_pdf(path)
    assert parsed.uncertain_notes == []


def test_text_layer_still_wins_when_page_has_a_large_image(tmp_path: Path) -> None:
    """★ 有文本层 + 有大图 → 仍然是文本抽取（A1-2：文本层 PDF 绝不走 OCR）。"""
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 400))
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(0, 0, 500, 500), pixmap=pix)  # 占满整页
    _w(page, 60, 520, "这张图下面还有一行完整的正文，超过每页字符阈值，应当走文本抽取。")
    path = tmp_path / "big_image_with_text.pdf"
    doc.save(str(path))
    doc.close()

    parsed = parse_pdf(path)
    assert parsed.source_type == "pdf_text"
    assert parsed.parse_method == "text_extract"
    assert any("完整的正文" in b.content_md for b in parsed.blocks)


@pytest.mark.parametrize("pages", [1, 2, 7])
def test_scan_detection_scales_with_page_count(
    ocr_unavailable: None, tmp_path: Path, pages: int
) -> None:
    """扫描版判定在 1 / 2 / 7 页下都成立（抽样边界：页数少于抽样数时全取）。

    挂 `ocr_unavailable`：D3 之后扫描版会真起 paddle 引擎（本机 ≈17 s/页，
    7 页 ≈2 min），而这条要验的是**抽样判定**与"不给假内容"，不是 OCR 认字能力。
    固定成"本机没装 `[ocr]`"（与真没装是同一条代码路径），断言一条都没放松。
    """
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(40, 40, 340, 340), pixmap=_grey_pixmap())
    path = tmp_path / f"scan{pages}.pdf"
    doc.save(str(path))
    doc.close()

    parsed = parse_pdf(path)
    assert parsed.source_type == "pdf_scan"
    assert parsed.blocks == []
    assert parsed.page_count == pages
