"""QA 独立验证 · 场景 14–16：页数边界、性能、扫描版判定。

覆盖点：
  · 场景 14：101 页 → 必须给明确中文提示**而不是静默截断**；正好 100 页 → 正常通过
  · 场景 15（A1-5）：20 页、每页有正文的 PDF，解析耗时必须 < 90 秒（实测并打印数字）
  · 场景 16（F1.2）：整页图片无文本层 → `pdf_scan`；纯文本框内容页（哪怕字很少）→ `pdf_text`；
    两个方向都要验，且要验"稀疏文本页不得被误判成扫描版"这个反向陷阱
    （误判的代价是整份材料一个块都产不出来）

性能用例的门限写死 90 秒（A1-5 的验收线），不写"当前值 + 余量" —— 后者会把
一次性能回归固化成正例。
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pymupdf
import pytest

from app.core.errors import ApiError, ErrorCode
from app.parse import parse_material, parse_pdf
from app.parse.pdf import MAX_PAGES, SCAN_MIN_CHARS_PER_PAGE

CJK_FONT = "china-s"
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")

#: A1-5 的硬门限（秒）
PERFORMANCE_BUDGET_SEC = 90.0


def _w(page: pymupdf.Page, x: float, y: float, text: str, size: float = 10) -> None:
    page.insert_text((x, y), text, fontname=CJK_FONT, fontsize=size)


def make_text_pdf(path: Path, pages: int, lines_per_page: int = 1) -> Path:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        for j in range(lines_per_page):
            _w(page, 72, 100 + j * 14, f"第{i + 1}页第{j + 1}行正文内容，用于边界与性能验证。")
    doc.save(str(path))
    doc.close()
    return path


def make_image_only_pdf(path: Path, pages: int = 1) -> Path:
    """整页一张图、没有任何文本层 —— 模拟扫描件。"""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 200))
        pix.clear_with(180)
        page.insert_image(pymupdf.Rect(40, 40, 340, 240), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return path


# ---------------------------------------------------------------------------
# 场景 14：页数边界
# ---------------------------------------------------------------------------


def test_101_pages_raises_instead_of_silently_truncating(tmp_path: Path) -> None:
    """★ 场景 14：超过上限必须报错。

    静默截断会让"这份材料的知识点怎么这么少"变成一个查不出来的问题 ——
    所以这里断言的是"抛异常"，而**不是**"返回 100 页的结果"。
    """
    path = make_text_pdf(tmp_path / "over.pdf", MAX_PAGES + 1)

    with pytest.raises(ApiError) as excinfo:
        parse_material(path)

    err = excinfo.value
    assert err.code == ErrorCode.INVALID_PARAM
    assert err.status_code == 400
    assert _HAN_RE.search(err.message)
    assert str(MAX_PAGES + 1) in err.message
    assert str(MAX_PAGES) in err.message
    assert "分批" in err.message
    assert "Traceback" not in err.message


def test_page_limit_error_is_not_a_silent_truncation_disguised_as_success(tmp_path: Path) -> None:
    """反向断言：超限时**不许**返回一个"看起来成功"的文档。

    如果实现改成了"截断到 100 页并返回"，上面那条 `pytest.raises` 就会失败，
    所以这里额外把"截断式成功"的判别条件写清楚：一旦返回，`page_count` 必须等于
    真实页数（101），否则就是静默截断。
    """
    path = make_text_pdf(tmp_path / "over2.pdf", MAX_PAGES + 1)
    try:
        doc = parse_material(path)
    except ApiError:
        return  # 期望路径：直接报错
    assert doc.page_count == MAX_PAGES + 1, (
        f"没有报错却把 {MAX_PAGES + 1} 页截断成了 {doc.page_count} 页 —— 这是静默截断"
    )
    pytest.fail("超过页数上限却没有报错，属于静默降级")


def test_exactly_100_pages_is_accepted(tmp_path: Path) -> None:
    """★ 场景 14：正好 100 页要能过（边界取闭区间，不能偷偷把上限降一页）。"""
    path = make_text_pdf(tmp_path / "at_limit.pdf", MAX_PAGES)

    doc = parse_pdf(path)
    assert doc.source_type == "pdf_text"
    assert doc.page_count == MAX_PAGES
    assert len(doc.blocks) == MAX_PAGES
    assert {b.page_no for b in doc.blocks} == set(range(1, MAX_PAGES + 1))


def test_page_limit_boundary_is_exclusive_above(tmp_path: Path) -> None:
    """100 过、101 不过 —— 边界两侧各验一次，确认门限没有漂。"""
    assert parse_pdf(make_text_pdf(tmp_path / "ok.pdf", MAX_PAGES)).page_count == MAX_PAGES
    with pytest.raises(ApiError):
        parse_pdf(make_text_pdf(tmp_path / "no.pdf", MAX_PAGES + 1))


# ---------------------------------------------------------------------------
# 场景 15：性能（A1-5）
# ---------------------------------------------------------------------------


def test_twenty_page_pdf_parses_under_90_seconds(tmp_path: Path) -> None:
    """★ 场景 15（A1-5）：20 页、每页有正文的 PDF，解析耗时 < 90 秒。

    实测耗时用 `print` 输出（跑本文件时加 `-s` 即可看到），断言只盯 A1-5 的门限。
    """
    path = make_text_pdf(tmp_path / "perf20.pdf", pages=20, lines_per_page=12)

    started = time.perf_counter()
    doc = parse_pdf(path)
    elapsed = time.perf_counter() - started

    print(
        f"\n[性能实测] 20 页 PDF：{elapsed:.3f}s"
        f"（{len(doc.blocks)} 块，门限 {PERFORMANCE_BUDGET_SEC:.0f}s）"
    )
    assert doc.page_count == 20
    # 每页的 12 行按单倍行距属于同一段 → 合并成一块，所以是 20 块；关键是每页的
    # 最后一行都在，说明 12 行一行都没丢。
    assert len(doc.blocks) == 20, f"应每页一块，实际 {len(doc.blocks)} 块"
    for page_no, block in enumerate(doc.blocks, start=1):
        assert block.page_no == page_no
        assert f"第{page_no}页第12行" in block.content_md, f"第 {page_no} 页的末行丢了"
    assert elapsed < PERFORMANCE_BUDGET_SEC, (
        f"20 页 PDF 解析耗时 {elapsed:.3f}s，超过 A1-5 的 {PERFORMANCE_BUDGET_SEC:.0f}s 门限"
    )


def test_markdown_build_is_fast_for_twenty_pages(tmp_path: Path) -> None:
    """拼 Markdown 也是链路的一部分，不能成为瓶颈（同样用 90 秒的宽松门限兜底）。"""
    from app.parse import to_markdown

    path = make_text_pdf(tmp_path / "perf20md.pdf", pages=20, lines_per_page=12)
    doc = parse_pdf(path)

    started = time.perf_counter()
    md = to_markdown(doc, "mat_0123abcd")
    elapsed = time.perf_counter() - started

    print(f"[性能实测] 20 页 PDF 拼 Markdown：{elapsed:.3f}s（{len(md)} 字符）")
    assert md
    assert elapsed < PERFORMANCE_BUDGET_SEC


# ---------------------------------------------------------------------------
# 场景 16：扫描版判定（F1.2）
# ---------------------------------------------------------------------------


def test_image_only_pdf_is_classified_as_scan(tmp_path: Path) -> None:
    """★ 场景 16：整页图片、无文本层 → `pdf_scan`。"""
    path = make_image_only_pdf(tmp_path / "scan.pdf")

    doc = parse_pdf(path)
    assert doc.source_type == "pdf_scan"
    assert doc.blocks == [], "判成扫描版就不许产出任何内容块（不能编）"
    assert doc.page_count == 1


def test_scan_document_does_not_claim_ocr_or_text_extract(tmp_path: Path) -> None:
    """扫描版既没跑 OCR、也没跑文本抽取 → `parse_method` 必须是 None。"""
    doc = parse_pdf(make_image_only_pdf(tmp_path / "scan.pdf"))
    assert doc.parse_method is None
    assert doc.parse_method not in ("ocr", "text_extract")


def test_scan_document_explains_itself_in_chinese(tmp_path: Path) -> None:
    """判成扫描版必须给出一条 high 级中文说明，否则用户只会反复重试同一个文件。"""
    doc = parse_pdf(make_image_only_pdf(tmp_path / "scan.pdf"))
    assert len(doc.uncertain_notes) == 1
    note = doc.uncertain_notes[0]
    assert note.severity == "high"
    assert _HAN_RE.search(note.message)
    assert "扫描" in note.message
    assert "OCR" in note.message or "ocr" in note.message
    assert str(SCAN_MIN_CHARS_PER_PAGE) in note.message


def test_multi_page_scan_is_detected_by_sampling(tmp_path: Path) -> None:
    """多页扫描件：抽样必须覆盖到"有图无字"的页，不能只看第一页就下结论。"""
    doc = parse_pdf(make_image_only_pdf(tmp_path / "scan8.pdf", pages=8))
    assert doc.source_type == "pdf_scan"
    assert doc.blocks == []
    assert doc.page_count == 8
    assert doc.uncertain_notes[0].page == 1


def test_sparse_text_page_without_images_is_text_not_scan(tmp_path: Path) -> None:
    """★ 场景 16：纯文本框内容页（哪怕字很少）→ `pdf_text`。

    这是反向陷阱：封面页、章节扉页常常只有几个字，判成扫描版会让整份材料
    一个块都产不出来。
    """
    doc = pymupdf.open()
    page = doc.new_page()
    _w(page, 72, 100, "网络原理课程讲义", 20)
    path = tmp_path / "cover_only.pdf"
    doc.save(str(path))
    doc.close()

    parsed = parse_pdf(path)
    assert parsed.source_type == "pdf_text"
    assert parsed.parse_method == "text_extract"
    assert parsed.blocks


def test_many_sparse_text_pages_are_still_text(tmp_path: Path) -> None:
    """★ 场景 16：连续 6 页每页都低于字符阈值、但都没有图 → 仍然是 `pdf_text`。

    只看字符数就会把这类"多页少字讲义"整份判成扫描件，代价是全篇零块。
    """
    doc = pymupdf.open()
    for i in range(6):
        page = doc.new_page()
        _w(page, 72, 100, f"第{i + 1}页只有八个字", 20)
    path = tmp_path / "sparse_six.pdf"
    doc.save(str(path))
    doc.close()

    parsed = parse_pdf(path)
    assert parsed.source_type == "pdf_text"
    assert len(parsed.blocks) == 6


def test_text_page_beats_image_only_page_in_the_same_document(tmp_path: Path) -> None:
    """一份材料里既有"整页图"又有"有字页" → 走文本抽取（有文本层就不是扫描版）。"""
    doc = pymupdf.open()
    cover = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 200))
    pix.clear_with(120)
    cover.insert_image(pymupdf.Rect(40, 40, 340, 240), pixmap=pix)
    body = doc.new_page()
    _w(body, 72, 100, "第二页有真正的文本层内容，这句话足够长，超过每页字符阈值。")
    path = tmp_path / "mixed.pdf"
    doc.save(str(path))
    doc.close()

    parsed = parse_pdf(path)
    assert parsed.source_type == "pdf_text"
    assert any("真正的文本层内容" in b.content_md for b in parsed.blocks)


def test_image_page_plus_very_short_text_page_is_classified_as_text(tmp_path: Path) -> None:
    """整页图 + 少字正文页 → `pdf_text`，且**正常产出块**。

    判决口径（见 `app/parse/pdf.py` 模块 docstring）：**只要抽样页里存在可读文本
    （哪怕十几个字），一律 `pdf_text`**。阈值 `SCAN_MIN_CHARS_PER_PAGE == 1`，
    含义是"一个可读字符都没有"——真正的扫描件不存在文本层，读出来必然是 0。

    最小复现：第 1 页整页图片无文本层；第 2 页只有 10 个字的真实正文。
    抽样页里第 2 页有文本层 → 整份走文本抽取，那 10 个字变成真实产物。
    这是刻意的"宁松勿紧"：误判成扫描版的代价是**整份材料零产物**，
    用户看到"解析成功"却拿不到任何内容（本模块最坏的失败模式）。

    反向（真正的扫描件仍然判 `pdf_scan`）由本文件里的
    `test_image_only_pdf_is_classified_as_scan`、
    `test_multi_page_scan_is_detected_by_sampling` 与
    `test_scan_document_explains_itself_in_chinese` 守住，没有被削弱。
    """
    doc = pymupdf.open()
    cover = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 200))
    pix.clear_with(120)
    cover.insert_image(pymupdf.Rect(40, 40, 340, 240), pixmap=pix)
    body = doc.new_page()
    _w(body, 72, 100, "第二页有文本层内容。")
    path = tmp_path / "mixed_short.pdf"
    doc.save(str(path))
    doc.close()

    parsed = parse_pdf(path)
    assert parsed.source_type == "pdf_text"
    assert parsed.parse_method == "text_extract"
    assert parsed.blocks, "有文本层就必须产出块"
    assert any("第二页有文本层内容" in b.content_md for b in parsed.blocks)
    assert all(b.page_no is not None for b in parsed.blocks)
    # 不该再挂着"扫描版"那条 high 级提示（它会让用户以为这份材料读不了）
    assert not any("扫描" in note.message for note in parsed.uncertain_notes)


def test_scan_document_page_count_is_reported(tmp_path: Path) -> None:
    """扫描版也要如实回报页数（用户据此判断材料规模）。"""
    doc = parse_pdf(make_image_only_pdf(tmp_path / "scan3.pdf", pages=3))
    assert doc.source_type == "pdf_scan"
    assert doc.page_count == 3
