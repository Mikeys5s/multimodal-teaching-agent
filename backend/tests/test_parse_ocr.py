"""图片 / 扫描页 OCR 的测试（归属：P1 · D3 **补充路径**）。

守的是这几条：
  · **F1.2** 扫描版 PDF 在 OCR 可用时要**真的产出内容**（`source_type="pdf_scan"`、
    `parse_method="ocr"`），不是只报一句"识别到扫描件"；
  · **图片材料**（`.png` 等）走 OCR 产块，落在 `source_type="image"` / `page_no=1`；
  · 每个 OCR 块都要带 `ocr_confidence` 与 `bbox`（前端角标与溯源都靠它）；
  · **OCR 不可用时必须降级**：扫描版 PDF 仍返回"0 块 + 中文说明"（不崩、不判失败），
    图片材料给一句可操作的中文报错 —— 没装 `[ocr]` 的机器上不能整条链路都废掉；
  · **进度回调**（P2 的异步 job 接口）：每页开始前回调一次，参数是 `(当前页, 总页数)`；
  · **A2-7 可复现**：同一输入两次结果一致；
  · 性能：实测每页耗时 → **外推** 20 页是否满足 P2 拍的 ≤8 min 门限。

跑这个文件很贵（Ocr ≈19–160 s/页，取决于页面密度）
----------------------------------------------------
所以：3 页真实扫描件**只跑一次**（`scan_run` 夹具），#2 / #3 / #6 / #7 共用；
其余用例只用程序化生成的小图与小 PDF。**永远不要**在这里跑 20 页。

素材在仓库之外，缺了整文件 skip
-------------------------------
与 `test_qa_parse_real_material.py` 同一约定：素材在 `.learnbuddy/materials/`
（不进版本库），可用 `QA_MATERIALS_DIR` 指向别处。
额外再加一条：**本机没装 `[ocr]` 可选依赖时也整文件 skip** —— 这个文件的所有用例
都建立在"OCR 能用"之上（降级路径由用例 4 用 monkeypatch 单独守）。
"""

from __future__ import annotations

import importlib
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import pytest

from app.core.errors import ApiError, ErrorCode
from app.parse import ocr, parse_material, parse_pdf
from app.parse.blocks import ParsedDocument

# ---------------------------------------------------------------------------
# 素材定位与跳过策略
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
MATERIALS_DIR = Path(os.environ.get("QA_MATERIALS_DIR", _REPO_ROOT / ".learnbuddy" / "materials"))
#: 真实扫描件样本（3 页、无文本层、含整页图）
SCAN_SAMPLE_PDF = MATERIALS_DIR / "ComputerNetworks-SystemsApproach-6e-扫描件样本.pdf"

#: P2 拍板的口径（Issue #22）：扫描件 OCR 单份 ≤20 页 ≤8 min。
PERF_GATE_20_PAGES_SEC = 8 * 60
#: 回归上限（秒/页）。本机实测 159 s/页（见 `app/parse/ocr.py` 模块 docstring），
#: 取约 1.9× 余量：**再慢一倍就是回归**，而不会被机器负载抖动误报。
REGRESSION_PER_PAGE_SEC = 300.0

_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
#: 程序化画中文用的字体（本机常见几种；都没有就 skip 那条用例）
_CJK_FONTS = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)
_IMAGE_LINES = (
    "网络层负责分组转发与路由选择。",
    "传输层提供端到端的可靠交付。",
    "应用层定义了进程间交换报文的格式。",
    "本课程重点讨论 TCP/IP 五层模型。",
)


def _skip_reason() -> str | None:
    if not SCAN_SAMPLE_PDF.is_file():
        return f"缺少真实扫描件样本，跳过（可用 QA_MATERIALS_DIR 指定素材目录）：{SCAN_SAMPLE_PDF}"
    if not ocr.ocr_available():
        return '未安装 OCR 可选依赖，跳过（pip install -e ".[ocr]"）'
    return None


_REASON = _skip_reason()
pytestmark = pytest.mark.skipif(_REASON is not None, reason=_REASON or "")


# ---------------------------------------------------------------------------
# 夹具与工具
# ---------------------------------------------------------------------------


@dataclass
class ScanRun:
    """3 页真实扫描件的一次 OCR 结果 + 观测数据（给 #2 / #3 / #6 / #7 共用）。

    时间全部用 `time.monotonic()` 的**绝对读数**（不是时长），差值才是每页耗时 ——
    混用"绝对读数"和"时长"会算出负数（这个坑踩过一次，见 `test_scan_run_timing_math`）。
    """

    doc: ParsedDocument
    calls: list[tuple[int, int]] = field(default_factory=list)
    started: float = 0.0
    page_starts: list[float] = field(default_factory=list)
    end: float = 0.0

    @property
    def wall_sec(self) -> float:
        """整段解析耗时（含一次性引擎构造）—— 用户实际等的时间。"""
        return self.end - self.started

    @property
    def per_page_sec(self) -> list[float]:
        """每页耗时：页起点之差（末页用解析结束时刻收尾）。"""
        marks = [*self.page_starts, self.end]
        return [round(marks[i + 1] - marks[i], 2) for i in range(len(self.page_starts))]

    @property
    def mean_page_sec(self) -> float:
        per_page = self.per_page_sec
        return sum(per_page) / len(per_page) if per_page else 0.0

    @property
    def extrapolated_20_pages_sec(self) -> float:
        return self.mean_page_sec * 20


@pytest.fixture(scope="module")
def scan_run() -> ScanRun:
    """★ 真实扫描件**只跑一次** OCR（很贵），把进度回调与耗时一并记下来。

    计时起点在 `on_page` 回调里取 —— 回调是"每页开始前"触发的，所以第 1 页的
    计时**不含**引擎构造（那 2–5 s 属于一次性成本，不该摊进每页耗时里）。
    """
    calls: list[tuple[int, int]] = []
    starts: list[float] = []

    def on_page(current: int, total: int) -> None:
        calls.append((current, total))
        starts.append(time.monotonic())

    started = time.monotonic()
    doc = parse_material(SCAN_SAMPLE_PDF, on_page=on_page)
    end = time.monotonic()
    ocr.release_engine()
    return ScanRun(doc=doc, calls=calls, started=started, page_starts=starts, end=end)


def test_scan_run_timing_math() -> None:
    """夹具的"每页耗时"必须由**绝对读数之差**算出（不是把时长当读数用）。

    这个用例挡的是一次真实踩过的坑：`marks = [*page_starts, wall_sec]` 把"时长"
    当成了"时刻"，于是末页耗时变成一个大负数，外推值直接变成负的 —— 而所有断言
    仍然会通过（负数当然小于门限）。**算错的时间比没有时间更危险。**
    """
    run = ScanRun(
        doc=ParsedDocument(source_type="pdf_scan"),
        started=100.0,
        page_starts=[105.0, 200.0, 300.0],
        end=380.0,
    )
    assert run.wall_sec == 280.0
    assert run.per_page_sec == [95.0, 100.0, 80.0]
    assert run.mean_page_sec == pytest.approx(91.67, abs=0.01)
    assert run.extrapolated_20_pages_sec > 0


def _cjk_font_path() -> str | None:
    return next((p for p in _CJK_FONTS if Path(p).is_file()), None)


def make_chinese_image(path: Path) -> Path:
    """画一张 4 行中文的小图（程序化生成，不依赖任何素材文件）。"""
    from PIL import Image, ImageDraw, ImageFont

    font_path = _cjk_font_path()
    if font_path is None:
        pytest.skip("本机没有可用的中文字体，无法程序化画中文测试图")

    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, 34)
    for i, text in enumerate(_IMAGE_LINES):
        draw.text((30, 30 + i * 65), text, fill="black", font=font)
    image.save(path)
    return path


def make_image_only_pdf(path: Path, pages: int = 1) -> Path:
    """只有整页图片、没有任何文本层的 PDF —— 与既有 QA 用例同一造法。"""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 200))
        pix.clear_with(180)
        page.insert_image(pymupdf.Rect(50, 50, 350, 250), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return path


# ---------------------------------------------------------------------------
# 1. 程序化中文图：识别出**预期文本**（不是"不为空"这种松断言）
# ---------------------------------------------------------------------------


def test_chinese_image_is_recognized_with_expected_text(tmp_path: Path) -> None:
    """★ 程序化中文图 → OCR 后必须认得出预期文本子串。

    断言的是**具体子串**而不是"块数 > 0"：松断言在"OCR 只认出一堆乱码"时也会绿，
    那正好是 OCR 最需要被发现的故障。
    """
    image = make_chinese_image(tmp_path / "cn.png")
    started = time.monotonic()
    doc = parse_material(image)
    elapsed = time.monotonic() - started

    joined = "".join(block.content_md for block in doc.blocks)
    print(f"\n[OCR 图片] {elapsed:.1f}s 块数={len(doc.blocks)} 文本={joined!r}")

    assert doc.source_type == "image"
    assert doc.parse_method == "ocr"
    assert doc.page_count == 1
    assert "网络层" in joined, f"没认出预期文本：{joined!r}"
    assert "传输层" in joined, f"没认出预期文本：{joined!r}"

    for block in doc.blocks:
        assert block.page_no == 1
        assert block.ocr_confidence is not None and 0.0 < block.ocr_confidence <= 1.0
        assert block.bbox is not None and len(block.bbox) == 4


def test_image_page_number_and_line_numbers_are_one_based(tmp_path: Path) -> None:
    """图片没有页码也要给 `page_no=1`，行号从 1 起连续 —— 否则前端溯源会指错。"""
    doc = parse_material(make_chinese_image(tmp_path / "cn.png"))
    assert doc.blocks
    assert {block.page_no for block in doc.blocks} == {1}
    assert [block.line_start for block in doc.blocks] == list(range(1, len(doc.blocks) + 1))


# ---------------------------------------------------------------------------
# 2 / 3. 真实扫描件：产块 + 字段完整 + 进度回调
# ---------------------------------------------------------------------------


def test_real_scan_sample_produces_ocr_blocks(scan_run: ScanRun) -> None:
    """★ F1.2：3 页真实扫描件（无文本层）→ 逐页 OCR 产块，字段齐全。

    「字段齐全」是硬要求：`page_no` 让用户能翻回原页，`bbox` 让前端能框出位置，
    `ocr_confidence` 让角标能标"这句是机器认的，可能错"。少一个就等于丢失溯源能力。
    """
    doc = scan_run.doc
    print(
        f"\n[真实扫描件] source_type={doc.source_type} parse_method={doc.parse_method} "
        f"page_count={doc.page_count} blocks={len(doc.blocks)} "
        f"每页耗时={scan_run.per_page_sec}"
    )
    assert doc.source_type == "pdf_scan"
    assert doc.parse_method == "ocr"
    assert doc.page_count == 3
    assert doc.blocks, "OCR 可用时必须真的产出内容块"
    assert {b.page_no for b in doc.blocks} == {1, 2, 3}, "三页都要有块（抽样页与全文页）"
    assert [b.page_no for b in doc.blocks] == sorted(b.page_no for b in doc.blocks)

    for block in doc.blocks:
        assert block.ocr_confidence is not None
        assert 0.0 < block.ocr_confidence <= 1.0
        assert block.bbox is not None and len(block.bbox) == 4
        assert block.content_md.strip()
    assert all(block.block_type == "paragraph" for block in doc.blocks)


def test_progress_callback_is_called_once_per_page(scan_run: ScanRun) -> None:
    """★ 进度钩子（P2 接异步 job 用）：每页一次，参数是 `(当前页, 总页数)`。

    一页要跑 100 s 量级，所以"跑完再报进度"等于没进度 —— 回调必须在**每页开始前**
    发生，且页号 1-based、总页数恒定，P2 才能直接算出百分比。
    """
    assert scan_run.calls == [(1, 3), (2, 3), (3, 3)], scan_run.calls


def test_image_progress_callback_reports_single_page(tmp_path: Path) -> None:
    """图片只有一页，回调也要报一次 `(1, 1)`，别让 P2 的 job 永远停在 0%。"""
    calls: list[tuple[int, int]] = []
    parse_material(make_chinese_image(tmp_path / "cn.png"), on_page=lambda a, b: calls.append((a, b)))
    assert calls == [(1, 1)]


# ---------------------------------------------------------------------------
# 4. 未装 OCR 依赖时的降级（扫描版 PDF 不崩、图片给中文报错）
# ---------------------------------------------------------------------------


def _break_paddleocr_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 `import paddleocr` 抛 `ImportError`（模拟"没装 `[ocr]`"）。

    必须同时清掉两个缓存（导入结果 + 可用性结论），否则前面的用例早就把
    "能用"缓存住了，这里会假绿。
    """
    real_import = importlib.import_module

    def _fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "paddleocr":
            raise ImportError("No module named 'paddleocr'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(ocr, "_PaddleOcrClass", None)
    monkeypatch.setattr(ocr, "_AVAILABLE", None)
    monkeypatch.setattr(ocr.importlib, "import_module", _fake_import)


def test_scan_pdf_degrades_to_zero_blocks_without_ocr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """★ 没装 OCR 时扫描版 PDF **保持现状**：0 块 + 一条 high 级中文说明，不抛错。

    不能因为"缺一个可选依赖"就把整份材料判失败 —— 用户看到的是"上传失败"，
    但材料本身没坏，是服务器少装了个包。
    """
    _break_paddleocr_import(monkeypatch)
    assert ocr.ocr_available() is False

    doc = parse_pdf(make_image_only_pdf(tmp_path / "scan.pdf"))
    assert doc.source_type == "pdf_scan"
    assert doc.blocks == [], "OCR 不可用时不许编内容"
    assert doc.parse_method is None
    assert len(doc.uncertain_notes) == 1
    note = doc.uncertain_notes[0]
    assert note.severity == "high"
    assert _HAN_RE.search(note.message)
    assert "扫描" in note.message
    assert "OCR" in note.message or "ocr" in note.message


def test_image_material_without_ocr_reports_chinese_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """★ 图片材料没有 OCR 就**没得退**（材料本身就是那张图）→ 中文报错 + 怎么补。

    文案必须点出 `[ocr]` 可选依赖与模型缓存目录：只说"解析失败"用户会一直重传。
    """
    _break_paddleocr_import(monkeypatch)
    image = make_chinese_image(tmp_path / "cn.png")

    with pytest.raises(ApiError) as excinfo:
        parse_material(image)
    message = excinfo.value.message
    print(f"\n[缺依赖报错] {message}")
    assert _HAN_RE.search(message), "报错必须是中文"
    assert "[ocr]" in message
    assert "PADDLE_PDX_CACHE_HOME" in message


def test_corrupt_image_reports_chinese_error(tmp_path: Path) -> None:
    """坏掉的图片 → 中文 `UNSUPPORTED_FORMAT`（点名文件 + 给出替代做法），不崩栈。

    图片路径与 PDF 路径一样，坏输入必须收口成能直接展示的 `ApiError`。
    """
    bad = tmp_path / "坏图.png"
    bad.write_bytes(b"not an image at all")

    with pytest.raises(ApiError) as excinfo:
        parse_material(bad)
    assert excinfo.value.code == ErrorCode.UNSUPPORTED_FORMAT
    assert _HAN_RE.search(excinfo.value.message)
    assert "请" in excinfo.value.message


# ---------------------------------------------------------------------------
# 5. A2-7 可复现
# ---------------------------------------------------------------------------

def test_same_image_twice_gives_same_blocks(tmp_path: Path) -> None:
    """★ 同一输入两次 → 块序列一致（A2-7）。

    这里比的是**块数与文本列表**，不比 `ocr_confidence` / `bbox` 的浮点末位：
    文本走的是 argmax 解码，实测逐字节稳定；而置信度与框坐标是浮点计算结果，
    换 paddle 版本 / 线程调度就可能末位不同 —— 拿浮点相等当断言，会在别人的
    机器上变成假红。
    """
    image = make_chinese_image(tmp_path / "cn.png")
    first = parse_material(image)
    second = parse_material(image)

    assert len(first.blocks) == len(second.blocks)
    assert [b.content_md for b in first.blocks] == [b.content_md for b in second.blocks]
    assert [b.bbox for b in first.blocks] == [b.bbox for b in second.blocks]


# ---------------------------------------------------------------------------
# 6 / 7. 性能：3 页实测 → 20 页外推
# ---------------------------------------------------------------------------


def test_ocr_perf_is_measured_and_extrapolated(scan_run: ScanRun) -> None:
    """★ 性能：3 页实测 → 20 页外推，并守住"不许比今天更慢一倍"。

    为什么用外推而不是真跑 20 页：本机一页 ≈159 s，20 页要 50 min 以上，
    真跑会把测试套件拖到不可用 —— 而"每页耗时"本身就是个稳定量，外推足够。
    """
    per_page = scan_run.per_page_sec
    mean = scan_run.mean_page_sec
    extrapolated = scan_run.extrapolated_20_pages_sec
    print(
        f"\n[OCR 性能] 3 页实测 {per_page} s（均值 {mean:.1f} s/页，"
        f"含 3 页总耗时 {scan_run.wall_sec:.1f} s）"
        f" → 20 页外推 {extrapolated:.0f} s = {extrapolated / 60:.1f} min；"
        f"P2 门限 {PERF_GATE_20_PAGES_SEC} s = {PERF_GATE_20_PAGES_SEC / 60:.0f} min"
    )
    assert per_page, "夹具没记录到每页耗时"
    assert mean <= REGRESSION_PER_PAGE_SEC, (
        f"每页 OCR 耗时 {mean:.1f} s 超过回归上限 {REGRESSION_PER_PAGE_SEC:.0f} s —— "
        "OCR 链路明显变慢了，先看是不是模型/引擎参数被改动"
    )


@pytest.mark.skipif(
    not ocr.MKLDNN_ENABLED,
    reason=(
        "本机 paddle 3.3.1 的 oneDNN 不可用（enable_mkldnn=True 会在 det 前向抛 "
        "NotImplementedError），CPU 推理没有算子加速 → 8 min 门限在本机不可达，"
        "故不在这里做门限断言（实测值由上一个用例打印）"
    ),
)
def test_ocr_perf_meets_the_20_page_gate(scan_run: ScanRun) -> None:
    """★ P2 的门限：单份 ≤20 页 ≤8 min。

    只在 `ocr.MKLDNN_ENABLED` 为真（机器上 CPU 加速真的可用）时执行 ——
    在无加速的机器上跑这条断言，得到的是"环境不行"而不是"代码不行"，
    天天红的门限等于没有门限。
    """
    assert scan_run.extrapolated_20_pages_sec <= PERF_GATE_20_PAGES_SEC, (
        f"20 页外推 {scan_run.extrapolated_20_pages_sec:.0f} s "
        f"超过门限 {PERF_GATE_20_PAGES_SEC} s"
    )
