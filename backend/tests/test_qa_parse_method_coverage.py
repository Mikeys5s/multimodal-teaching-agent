"""QA 独立验证 · A1-4「解析方式（`parse_method`） + 存疑处（`uncertain_notes`）」。

为什么单独开一份文件
--------------------
`parse_method` 与 `uncertain_notes` 是**给用户看的两个"交代"**：
  · `parse_method` 说明"这份材料是怎么读出来的"（文本层抽取 / OCR / 多模态 LLM / ASR）；
  · `uncertain_notes` 说明"哪里没把握、哪里没读到"。

两者最重要的性质是**不能同时缺席**：一份材料要么给出**结论**（`parse_method`
不是 None），要么给出**存疑说明**（`uncertain_notes` 非空）—— 既没结论又没说明，
用户看到的就是"解析成功"却一片空白，还会拿着同一个文件反复重试。

本文件按"素材形态"逐类钉住这条性质，夹具**全部现场生成**（pymupdf /
python-docx / python-pptx），不依赖任何外部素材文件 —— 素材进不了版本库，
靠它写的测试在队友机器上必然红。

⚠️ 与任务书的口径出入（如实记录，见对应用例）
--------------------------------------------
任务书假设 `app/parse/ocr.py` 与 `conftest.py::ocr_unavailable` **已存在**。
实测两者**都不存在**：本批次**连 OCR 模块都没有**（扫描版 PDF 只识别不解析），
`ocr_unavailable` 也是本次新增的夹具。因此：
  · 扫描版 PDF 走的是 `app/parse/pdf.py::parse_pdf` 里的扫描分支，不是 OCR 模块；
  · 图片（`.png`）**不会**走任何 OCR 通道，而是在 `parse_material` 的扩展名
    分派里就以 `UNSUPPORTED_FORMAT` 被拒（文案点名「图片」，但**没有** `[ocr]`
    字样）。任务书期望的 `[ocr]` 字样用 `xfail(strict=False)` 钉住，
    见 `test_image_error_points_to_ocr_extra`。
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf
import pytest
from docx import Document as DocxDocument
from pptx import Presentation

from app.core.errors import ApiError, ErrorCode
from app.models._common import PARSE_METHODS
from app.parse import parse_material
from app.parse.blocks import UNCERTAIN_KINDS, UNCERTAIN_SEVERITIES

CJK_FONT = "china-s"  # PyMuPDF 内置中文字体，保证中文进得了文本层
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")


# ---------------------------------------------------------------------------
# 夹具生成（六类素材，全部程序化）
# ---------------------------------------------------------------------------


def _write_cjk(page: pymupdf.Page, x: float, y: float, text: str, size: float = 10.0) -> None:
    page.insert_text((x, y), text, fontname=CJK_FONT, fontsize=size)


def make_text_layer_pdf(path: Path) -> Path:
    """文本层 PDF：有字、无图 —— 必须走文本抽取。"""
    doc = pymupdf.open()
    page = doc.new_page()
    _write_cjk(page, 72, 72, "第1章 网络层", 18)
    _write_cjk(page, 72, 110, "1.1 路由基础", 13)
    _write_cjk(page, 72, 140, "路由是把分组从源送到目的的过程。")
    doc.save(str(path))
    doc.close()
    return path


def make_scan_pdf(path: Path) -> Path:
    """只有一张整页图、没有任何文本层 —— 模拟扫描件（OCR 不可用的前提）。"""
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 200))
    pix.clear_with(180)
    page.insert_image(pymupdf.Rect(50, 50, 350, 250), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return path


def make_docx(path: Path) -> Path:
    """标题 + 段落：走文本抽取。"""
    document = DocxDocument()
    document.add_heading("第1章 网络层", level=1)
    document.add_paragraph("路由是把分组从源送到目的的过程。")
    document.save(str(path))
    return path


def make_pptx(path: Path) -> Path:
    """2 张幻灯片（标题 + 正文）：走文本抽取。"""
    prs = Presentation()
    layout = prs.slide_layouts[1]  # Title and Content
    first = prs.slides.add_slide(layout)
    first.shapes.title.text = "第1章 网络层"
    first.placeholders[1].text = "路由是把分组从源送到目的的过程。"
    second = prs.slides.add_slide(layout)
    second.shapes.title.text = "1.1 路由基础"
    second.placeholders[1].text = "路由器根据路由表决定下一跳。"
    prs.save(str(path))
    return path


def make_png(path: Path) -> Path:
    """合法的小 PNG（用 pymupdf 出图，免得为测试引入 Pillow）。"""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 40))
    pix.clear_with(200)
    pix.save(str(path))
    return path


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    return make_text_layer_pdf(tmp_path / "text.pdf")


@pytest.fixture
def scan_pdf(tmp_path: Path) -> Path:
    return make_scan_pdf(tmp_path / "scan.pdf")


@pytest.fixture
def docx_file(tmp_path: Path) -> Path:
    return make_docx(tmp_path / "notes.docx")


@pytest.fixture
def pptx_file(tmp_path: Path) -> Path:
    return make_pptx(tmp_path / "deck.pptx")


def _assert_chinese(message: str) -> None:
    assert _HAN_RE.search(message), f"给用户的文案必须含中文：{message!r}"


# ---------------------------------------------------------------------------
# 能真解析的三类：parse_method 必须是 text_extract（而且绝不能是 ocr）
# ---------------------------------------------------------------------------


def test_text_layer_pdf_reports_text_extract(text_pdf: Path) -> None:
    """★ A1-2 / A1-4：文本层 PDF 的解析方式是文本抽取，绝不是 OCR。"""
    doc = parse_material(text_pdf)
    assert doc.source_type == "pdf_text"
    assert doc.parse_method == "text_extract"
    assert doc.parse_method != "ocr"
    assert doc.blocks, "文本层 PDF 抽出 0 个块，说明走到了扫描分支"


def test_docx_reports_text_extract(docx_file: Path) -> None:
    doc = parse_material(docx_file)
    assert doc.source_type == "docx"
    assert doc.parse_method == "text_extract"
    assert doc.parse_method != "ocr"


def test_pptx_reports_text_extract(pptx_file: Path) -> None:
    doc = parse_material(pptx_file)
    assert doc.source_type == "pptx"
    assert doc.parse_method == "text_extract"
    assert doc.parse_method != "ocr"


@pytest.mark.parametrize("fixture_name", ["text_pdf", "docx_file", "pptx_file"])
def test_text_extract_is_a_legal_enum_value(request: pytest.FixtureRequest, fixture_name: str) -> None:
    """`parse_method` 落库前要过 CHECK 约束 —— 值必须取自 `PARSE_METHODS`。"""
    doc = parse_material(request.getfixturevalue(fixture_name))
    assert doc.parse_method in PARSE_METHODS


# ---------------------------------------------------------------------------
# 扫描版 PDF（OCR 不可用）：不许写假账，但必须留一条 high 级中文说明
# ---------------------------------------------------------------------------


def test_scan_pdf_is_identified_without_claiming_ocr(scan_pdf: Path, ocr_unavailable: None) -> None:
    """★ F1.2 + A1-4：扫描版被**识别**出来（`pdf_scan`），但结果里**不含块**。

    `parse_method` 必须是 `None` —— 本批次一行 OCR 都没跑，写 `"ocr"` 就是假账，
    而假账比"没有结论"更坏：下游会以为"识别过了，只是没识别出内容"。
    """
    doc = parse_material(scan_pdf)
    assert doc.source_type == "pdf_scan"
    assert doc.blocks == []
    assert doc.parse_method is None
    assert doc.parse_method != "ocr"


def test_scan_pdf_explains_itself_with_one_high_chinese_note(
    scan_pdf: Path, ocr_unavailable: None
) -> None:
    """★ A1-4「存疑处」：没有结论时**必须**给出说明，且是 high 级中文。"""
    doc = parse_material(scan_pdf)
    assert len(doc.uncertain_notes) == 1, "扫描版必须且只给一条说明，多了是噪声"
    note = doc.uncertain_notes[0]
    assert note.severity == "high", "扫描版等于整份材料零产物，必须是最高的存疑等级"
    assert note.kind in UNCERTAIN_KINDS
    assert note.severity in UNCERTAIN_SEVERITIES
    _assert_chinese(note.message)
    assert "扫描" in note.message, "说明里要点明「这是扫描版」，用户才知道为什么没内容"
    assert "OCR" in note.message, "说明里要点明「是 OCR 没接」，而不是文件本身有问题"


def test_scan_pdf_note_message_is_not_empty_and_is_showable(
    scan_pdf: Path, ocr_unavailable: None
) -> None:
    """说明要能**直接展示**：不含英文堆栈、不以空白收尾。"""
    note = parse_material(scan_pdf).uncertain_notes[0]
    assert note.message.strip() == note.message
    assert "Traceback" not in note.message
    assert len(note.message) >= 20


# ---------------------------------------------------------------------------
# 图片（OCR 不可用）：拒绝，但要说人话
# ---------------------------------------------------------------------------


def test_image_is_rejected_with_chinese_reason(tmp_path: Path, ocr_unavailable: None) -> None:
    """★ 图片（合法 PNG）→ 中文 `ApiError`，文案点名「图片」并给出替代做法。

    这条与"扫描版 PDF 只识别不解析"同源：本批次没有 OCR，图片里的字读不出来，
    所以**在扩展名分派阶段就拒绝**，而不是产出一份空的 `image` 材料。
    """
    target = make_png(tmp_path / "photo.png")
    with pytest.raises(ApiError) as excinfo:
        parse_material(target)

    err = excinfo.value
    assert err.code == ErrorCode.UNSUPPORTED_FORMAT
    assert err.status_code == 400
    _assert_chinese(err.message)
    assert "图片" in err.message
    assert "PDF" in err.message and "DOCX" in err.message, "必须给出替代做法"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "任务书期望图片的报错文案点到 [ocr] 这个可选依赖组；实测文案是"
        "「图片 格式本批次暂不支持解析，请转为 PDF 或 DOCX 后再上传」，没有 [ocr] 字样。"
        "这属于「文案里没把可选的 OCR 通道指出来」的表述缺口，不是功能缺陷"
        "（用户上传图片本来就没有可用的替代动作，指路「等 OCR 上线」更诚实）。"
        "strict=False：哪天文案补上 [ocr] 就会 XPASS，不算失败。"
    ),
)
def test_image_error_points_to_ocr_extra(tmp_path: Path, ocr_unavailable: None) -> None:
    """任务书期望（当前**未满足**）：图片的拒绝文案里点到 `[ocr]` 通道。"""
    target = make_png(tmp_path / "photo.png")
    with pytest.raises(ApiError) as excinfo:
        parse_material(target)
    assert "[ocr]" in excinfo.value.message


def test_image_rejection_names_the_png_extension_indirectly(tmp_path: Path, ocr_unavailable: None) -> None:
    """现状：文案点名的是**类别**（「图片」）而不是扩展名（`.png`）。

    `.xlsx` 这类"见都没见过"的扩展名会被原样回显（见
    `test_qa_parse_robustness.py::test_unknown_extension_is_echoed_back`）；
    图片/音频/旧版 doc 这类**认得出**的格式走的是另一条分支，点名的是类别。
    这是有意的粒度差异（"图片"比"`.png`"更能覆盖 jpg/webp 一起说清楚），
    所以这里断言现状而不是当成缺陷。
    """
    target = make_png(tmp_path / "photo.png")
    with pytest.raises(ApiError) as excinfo:
        parse_material(target)
    message = excinfo.value.message
    assert "图片" in message
    assert ".png" not in message, "一旦改成点名扩展名，这条断言就该跟着改（不是 bug）"


# ---------------------------------------------------------------------------
# 不支持的格式：点名格式，而不是笼统的"不支持"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "required_fragments"),
    [
        # 旧版 .ppt 只差一次"另存为"，所以文案必须给出这条**具体**出路
        ("讲义.ppt", (".ppt", "另存为", ".pptx")),
        # 音频是整类不支持，点名类别（"音频"）并给出统一替代做法
        ("录音.m4a", ("音频", "PDF", "DOCX")),
    ],
)
def test_unsupported_format_names_the_concrete_format(
    tmp_path: Path, filename: str, required_fragments: tuple[str, ...]
) -> None:
    """★ A1-4：认得出但本批次没接的格式 → `UNSUPPORTED_FORMAT` 且点名格式。

    "暂不支持" 这种笼统说法会让用户反复重试；点名格式 + 给出出路才有用。
    """
    target = tmp_path / filename
    target.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 placeholder")

    with pytest.raises(ApiError) as excinfo:
        parse_material(target)

    err = excinfo.value
    assert err.code == ErrorCode.UNSUPPORTED_FORMAT
    assert err.status_code == 400
    _assert_chinese(err.message)
    for fragment in required_fragments:
        assert fragment in err.message, f"文案缺少 {fragment!r}：{err.message!r}"


def test_unsupported_formats_never_silently_succeed(tmp_path: Path) -> None:
    """反向断言：不支持的格式**必须拒绝**，不能返回一份空的成功结果。

    "解析成功但零产物"是本模块最坏的失败模式 —— 用户会以为材料读进去了。
    """
    target = tmp_path / "讲义.ppt"
    target.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1x")
    with pytest.raises(ApiError):
        parse_material(target)


# ---------------------------------------------------------------------------
# 总括断言：要么给结论、要么给存疑说明，不能两样都没有
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", ["text_pdf", "docx_file", "pptx_file"])
def test_parseable_material_always_has_method_and_explicit_notes(
    request: pytest.FixtureRequest, fixture_name: str
) -> None:
    """★ A1-4 总括：每种**能解析**的素材都必须给出结论 + 显式产出的存疑字段。

    · `parse_method` 一定不是 None（有结论）；
    · `uncertain_notes` 一定被**显式产出**（哪怕是空列表）—— 不是"字段不存在"，
      而是"检查过了、没有要说的"。两者的区别在于：字段缺失时前端无从区分
      "没问题"与"这一版还没实现"，而空列表是一个明确的答复。
    """
    doc = parse_material(request.getfixturevalue(fixture_name))

    assert doc.parse_method is not None, "能解析的素材必须给出 parse_method"
    assert doc.parse_method in PARSE_METHODS
    assert doc.uncertain_notes is not None, "uncertain_notes 必须被显式产出"
    assert isinstance(doc.uncertain_notes, list)
    for note in doc.uncertain_notes:
        assert note.kind in UNCERTAIN_KINDS
        assert note.severity in UNCERTAIN_SEVERITIES
        assert note.message.strip(), "空说明等于没标，前端会显示空卡片"

    assert doc.blocks, "能解析的素材不该产出空块表"


def test_scan_material_gives_doubt_because_it_has_no_conclusion(
    scan_pdf: Path, ocr_unavailable: None
) -> None:
    """★ A1-4 总括的另一半：没有结论的素材，`uncertain_notes` **必须**非空。

    "要么给结论、要么给存疑说明，不能两样都没有" —— 扫描版就是"没结论"的情形，
    它拿不出 `parse_method`，就必须拿得出说明。
    """
    doc = parse_material(scan_pdf)
    assert doc.parse_method is None
    assert doc.uncertain_notes, "没有结论又不说为什么 —— 用户只会反复重试同一个文件"


@pytest.mark.parametrize("fixture_name", ["text_pdf", "docx_file", "pptx_file"])
def test_parseable_material_is_reproducible_across_calls(
    request: pytest.FixtureRequest, fixture_name: str
) -> None:
    """A2-7 的相邻性质：`parse_method` / `uncertain_notes` 也要可复现，不能抖。"""
    path = request.getfixturevalue(fixture_name)
    first = parse_material(path)
    second = parse_material(path)
    assert first.parse_method == second.parse_method
    assert first.uncertain_notes == second.uncertain_notes
