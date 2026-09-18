"""文本层 PDF 解析的测试（归属：P1）。

守的是这几条验收项：
  · **A1-2** 文本层 PDF 不许走 OCR（→ `source_type == "pdf_text"`、`parse_method == "text_extract"`）
  · **A1-6** 每个块都能定位到页码（→ 块必须带 `page_no` / 页内行号）
  · **A1-7** 单文件失败要给出能直接展示的中文原因，不整批崩
  · **F1.2** 扫描版要被识别出来（`source_type == "pdf_scan"`）
  · **A2-7** 同输入可复现（两次解析结果逐字段相等）

夹具全部**现场生成**（pymupdf 直接写 PDF），不依赖任何外部素材文件 ——
素材文件进不了版本库，靠它们写的测试在队友机器上必然红。
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf
import pytest

from app.core.errors import ApiError, ErrorCode
from app.parse import parse_pdf, to_markdown
from app.parse.pdf import MAX_PAGES, SCAN_MIN_CHARS_PER_PAGE

CJK_FONT = "china-s"  # PyMuPDF 内置中文字体，保证中文能进文本层
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")


# ---------------------------------------------------------------------------
# 夹具生成
# ---------------------------------------------------------------------------


def _write_cjk(page: pymupdf.Page, x: float, y: float, text: str, size: float) -> None:
    page.insert_text((x, y), text, fontname=CJK_FONT, fontsize=size)


def _write_latin(page: pymupdf.Page, x: float, y: float, text: str, size: float) -> None:
    page.insert_text((x, y), text, fontsize=size)


def make_text_pdf(path: Path) -> Path:
    """三页文本层 PDF：章标题 18pt、节标题 13pt、正文 10pt。"""
    doc = pymupdf.open()

    p1 = doc.new_page()
    _write_cjk(p1, 72, 72, "第1章 网络层", 18)
    _write_cjk(p1, 72, 110, "1.1 路由基础", 13)
    _write_cjk(p1, 72, 140, "路由是把分组从源送到目的的过程，路由器根据路由表决定下一跳。", 10)
    _write_cjk(p1, 72, 160, "路由表里保存着到达各目的网络的下一跳地址。", 10)

    p2 = doc.new_page()
    _write_cjk(p2, 72, 110, "1.2 转发与路由选择", 13)
    _write_cjk(p2, 72, 140, "转发是本地动作，路由选择是全局动作，两者分工不同。", 10)

    p3 = doc.new_page()
    _write_cjk(p3, 72, 110, "第2章 应用层", 18)
    _write_cjk(p3, 72, 140, "应用层协议定义了进程之间交换报文的格式与次序。", 10)

    doc.save(str(path))
    doc.close()
    return path


def make_image_only_pdf(path: Path) -> Path:
    """只有一张图片、没有任何文本层的 PDF —— 模拟扫描件。"""
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 200))
    pix.clear_with(180)  # 纯灰底，像一张扫描图
    page.insert_image(pymupdf.Rect(50, 50, 350, 250), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return path


def make_encrypted_pdf(path: Path) -> Path:
    """带用户口令的加密 PDF。"""
    doc = pymupdf.open()
    page = doc.new_page()
    _write_cjk(page, 72, 72, "这是一份加密文档", 12)
    doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    doc.close()
    return path


def make_many_page_pdf(path: Path, pages: int) -> Path:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        _write_cjk(page, 72, 72, f"第{i + 1}页的正文内容，用来撑满页数。", 10)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    return make_text_pdf(tmp_path / "text.pdf")


# ---------------------------------------------------------------------------
# 文本层 PDF
# ---------------------------------------------------------------------------


def test_text_pdf_uses_text_extract_and_never_ocr(text_pdf: Path) -> None:
    """★ A1-2：文本层 PDF 必须走文本抽取，绝不能落到 ocr 上。"""
    doc = parse_pdf(text_pdf)
    assert doc.source_type == "pdf_text"
    assert doc.parse_method == "text_extract"
    assert doc.parse_method != "ocr"
    assert doc.page_count == 3
    assert doc.blocks, "文本层 PDF 一个块都没抽出来，说明走到了扫描版分支"


def test_original_text_survives_intact(text_pdf: Path) -> None:
    """★ A1-2：原文准确率 —— 文本层里的字必须一字不差地出来，不做任何"识别"。"""
    doc = parse_pdf(text_pdf)
    joined = "\n".join(b.content_md for b in doc.blocks)
    for fragment in (
        "第1章 网络层",
        "1.1 路由基础",
        "路由器根据路由表决定下一跳",
        "应用层协议定义了进程之间交换报文的格式与次序",
    ):
        assert fragment in joined


def test_every_block_is_locatable(text_pdf: Path) -> None:
    """★ A1-6：每个块都要能定位 —— 页码 1-based 且落在真实页数内，行号同样。"""
    doc = parse_pdf(text_pdf)
    assert len(doc.blocks) >= 5
    for block in doc.blocks:
        assert block.page_no is not None, "文本层 PDF 的块必须有页码"
        assert 1 <= block.page_no <= 3
        assert block.line_start is not None and block.line_end is not None
        assert 1 <= block.line_start <= block.line_end
        assert block.bbox is not None and len(block.bbox) == 4


def test_page_no_covers_every_page_in_document_order(text_pdf: Path) -> None:
    doc = parse_pdf(text_pdf)
    pages = [b.page_no for b in doc.blocks]
    assert pages == sorted(pages), "块的顺序必须与文档顺序一致，页码不能回跳"
    assert set(pages) == {1, 2, 3}


def test_seq_is_global_continuous_from_zero(text_pdf: Path) -> None:
    doc = parse_pdf(text_pdf)
    assert [seq for seq, _ in doc.numbered()] == list(range(len(doc.blocks)))


def test_heading_levels_are_valid_and_only_on_headings(text_pdf: Path) -> None:
    doc = parse_pdf(text_pdf)
    headings = [b for b in doc.blocks if b.block_type == "heading"]
    assert headings, "章标题与节标题都没认出来"
    for block in doc.blocks:
        if block.block_type == "heading":
            assert block.heading_level is not None
            assert 1 <= block.heading_level <= 6
        else:
            assert block.heading_level is None


def test_chapter_and_section_headings_get_their_own_levels(text_pdf: Path) -> None:
    """章 18pt 比节 13pt 大 → 层级必须是 1 与 2，不能两个都平级。"""
    doc = parse_pdf(text_pdf)
    by_text = {b.content_md: b for b in doc.blocks if b.block_type == "heading"}
    assert by_text["第1章 网络层"].heading_level == 1
    assert by_text["1.1 路由基础"].heading_level == 2


def test_wrapped_lines_are_merged_into_one_paragraph(tmp_path: Path) -> None:
    """同一段的两行要合成一块 —— 否则下游按句切分时会切到半句话。"""
    path = tmp_path / "wrapped.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    _write_cjk(page, 72, 72, "这是一段很长的正文，排版时被折成了两行，", 10)
    _write_cjk(page, 72, 88, "合起来才是一句完整的话。", 10)
    doc.save(str(path))
    doc.close()

    parsed = parse_pdf(path)
    paragraphs = [b.content_md for b in parsed.blocks if b.block_type == "paragraph"]
    assert paragraphs == ["这是一段很长的正文，排版时被折成了两行，合起来才是一句完整的话。"]


def test_markdown_carries_page_and_block_anchors(text_pdf: Path) -> None:
    """A1-6 的落地形式：Markdown 里页码与块 ID 都能被定位到。"""
    doc = parse_pdf(text_pdf)
    md = to_markdown(doc, "mat_0123abcd")
    assert "<!-- page: 1 -->" in md
    assert "<!-- page: 3 -->" in md
    assert "<!-- block: blk_0123abcd_00000 -->" in md
    assert md.index("<!-- page: 1 -->") < md.index("<!-- page: 3 -->")


# ---------------------------------------------------------------------------
# 扫描版（F1.2）
# ---------------------------------------------------------------------------
# ⚠️ 下面三条挂 `ocr_unavailable`：D3 之后扫描版会**真起 paddle 引擎**（本机实测
# ≈17 s/页，真实扫描件 140 s/页），而这三条要守的是"判成扫描版就不许编内容"、
# 不是"OCR 认得多准" —— 固定成"本机没装 `[ocr]`"即可，与真没装是同一条代码路径。
# 断言一条都没放松。真跑 OCR 的用例在 `test_parse_ocr.py`（`XIZHI_RUN_OCR_SLOW=1` 开启）。


def test_image_only_pdf_is_detected_as_scan(ocr_unavailable: None, tmp_path: Path) -> None:
    """★ F1.2：没有文本层 → 判为 pdf_scan，且**不产出伪造的块**。"""
    path = make_image_only_pdf(tmp_path / "scan.pdf")
    doc = parse_pdf(path)
    assert doc.source_type == "pdf_scan"
    assert doc.blocks == []
    assert doc.page_count == 1


def test_scan_detection_does_not_claim_ocr_was_run(ocr_unavailable: None, tmp_path: Path) -> None:
    """没有可用的 OCR 时一行都没跑，`parse_method` 就必须是 None —— 写 'ocr' 是假账。"""
    path = make_image_only_pdf(tmp_path / "scan.pdf")
    doc = parse_pdf(path)
    assert doc.parse_method is None
    assert doc.parse_method != "ocr"


def test_scan_detection_explains_itself_with_chinese_note(
    ocr_unavailable: None, tmp_path: Path
) -> None:
    """判成扫描版却不告诉用户为什么，用户只会反复重试同一个文件。"""
    path = make_image_only_pdf(tmp_path / "scan.pdf")
    doc = parse_pdf(path)
    assert len(doc.uncertain_notes) == 1
    note = doc.uncertain_notes[0]
    assert note.severity == "high"
    assert _HAN_RE.search(note.message), "存疑说明必须是中文"
    assert str(SCAN_MIN_CHARS_PER_PAGE) in note.message


def test_scan_threshold_is_not_triggered_by_a_sparse_text_page(tmp_path: Path) -> None:
    """反向陷阱：只有一两行正文的封面页不能被当成扫描件 —— 误判成扫描版会
    让整份材料一个块都产不出来，代价远大于反向误判。"""
    path = tmp_path / "cover.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    _write_cjk(page, 72, 72, "网络原理课程讲义", 20)
    doc.save(str(path))
    doc.close()

    parsed = parse_pdf(path)
    assert parsed.source_type == "pdf_text"
    assert parsed.blocks


# ---------------------------------------------------------------------------
# 失败隔离（A1-7）：错误必须是中文 + 明确
# ---------------------------------------------------------------------------


def test_encrypted_pdf_raises_chinese_error(tmp_path: Path) -> None:
    path = make_encrypted_pdf(tmp_path / "enc.pdf")
    with pytest.raises(ApiError) as excinfo:
        parse_pdf(path)

    err = excinfo.value
    assert err.code == ErrorCode.INVALID_PARAM
    assert _HAN_RE.search(err.message), "报错必须是中文，不能是英文堆栈"
    assert "加密" in err.message
    assert "密码" in err.message


def test_corrupted_pdf_raises_chinese_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is definitely not a pdf body")
    with pytest.raises(ApiError) as excinfo:
        parse_pdf(path)

    err = excinfo.value
    assert err.code == ErrorCode.INVALID_PARAM
    assert _HAN_RE.search(err.message)
    assert "损坏" in err.message


def test_empty_file_raises_chinese_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    with pytest.raises(ApiError) as excinfo:
        parse_pdf(path)
    assert _HAN_RE.search(excinfo.value.message)
    assert "空文件" in excinfo.value.message


def test_too_many_pages_asks_for_batching_instead_of_truncating(tmp_path: Path) -> None:
    """★ 边界：>100 页必须报错提示分批。静默截断会让"知识点怎么这么少"无从解释。"""
    path = make_many_page_pdf(tmp_path / "big.pdf", MAX_PAGES + 1)
    with pytest.raises(ApiError) as excinfo:
        parse_pdf(path)

    err = excinfo.value
    assert err.code == ErrorCode.INVALID_PARAM
    assert str(MAX_PAGES + 1) in err.message
    assert str(MAX_PAGES) in err.message
    assert "分批" in err.message


def test_exactly_at_the_page_limit_is_allowed(tmp_path: Path) -> None:
    """边界取闭区间：正好 100 页要能过，否则是把上限偷偷降了一页。"""
    path = make_many_page_pdf(tmp_path / "atlimit.pdf", MAX_PAGES)
    doc = parse_pdf(path)
    assert doc.page_count == MAX_PAGES
    assert doc.source_type == "pdf_text"


# ---------------------------------------------------------------------------
# 可复现（A2-7）
# ---------------------------------------------------------------------------


def test_same_file_parses_identically_twice(text_pdf: Path) -> None:
    """★ A2-7：同一份文件跑两次，逐字段相等。"""
    first = parse_pdf(text_pdf)
    second = parse_pdf(text_pdf)
    assert first == second
    assert to_markdown(first, "mat_0123abcd") == to_markdown(second, "mat_0123abcd")


def test_repeated_calls_do_not_accumulate_state(text_pdf: Path) -> None:
    """解析器不能有跨调用的状态 —— 第三次跑必须和前两次一样。"""
    baseline = parse_pdf(text_pdf)
    for _ in range(3):
        assert parse_pdf(text_pdf) == baseline
