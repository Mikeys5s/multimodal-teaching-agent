"""图片 / 扫描页 OCR（归属：P1 · D3 **补充路径**）。

口径由 P2 拍板（Issue #22），本模块照此执行、不自行放宽：

| 路径 | 定位 | 门限 |
|---|---|---|
| 文本层 PDF（`pdf.py` 的文本 API） | **主路径** | 单份 ≤20 页 ≤90 s |
| **扫描件 / 图片 OCR（本模块）** | **补充路径** | 单份 ≤20 页 ≤8 min，且能报进度、可中断 |

文本层 PDF **一行 OCR 都不跑**（A1-2 要求抽取准确率 ≥98%，OCR 是"识别"做不到）；
只有"没有文本层"的扫描件与图片材料才走这里。

依赖是可选组，必须惰性导入
--------------------------
`[parse]` 只装 pymupdf / python-docx / python-pptx；OCR 依赖（paddleocr + paddlepaddle）
在 `[ocr]` 组，几个 GB。所以本模块顶层**不 import paddleocr / numpy / PIL**：
  · `ocr_available()` 只探测一次并缓存结果；
  · 探测失败（没装、或"装了但坏了"）**不抛给用户**，而是让调用方走降级路径 ——
    没装 OCR 不该把整份材料判失败（`pdf.py` 的扫描版分支就是这么用的）；
  · 真要 OCR 才 import，失败时给**中文** `ApiError` + 可操作建议。

引擎实例缓存与释放
------------------
构造一次要 2–5 s（还要加载 ~133 MB 模型），所以同一进程内复用（`get_engine`）；
长任务收尾要能显式松手（`release_engine`），不然 OCR 引擎会一直占着几百 MB 内存。

按页进度回调（P2 接异步 job 用）
--------------------------------
`parse_scan_pdf(doc, on_page=...)` / `parse_image(path, on_page=...)` 的 `on_page`
签名是 `(当前页序号 1-based, 总页数)`，**每页开始前**调用一次：
  · P2 的异步 job 靠它写 `jobs.progress`、让前端看到"第 3/20 页"；
  · 回调里想中断就直接抛异常 —— `ApiError` 会原样透传，其他异常会被 `parse_pdf`
    的兜底收敛成中文 `ApiError`（`parse_material` 对外承诺"失败一律 ApiError"）；
  · 默认 `None`，对现有调用零影响。

本机实测（Windows / 8 核 / paddle 3.3.1 + paddleocr 3.7.0 / PP-OCRv6_medium_det+rec）
-------------------------------------------------------------------------------------
· 一页 A4 扫描件（1700×2200 px、41 行正文）：**≈159 s**（det 15.3 s + rec ≈144 s）；
· ⇒ 20 页外推 ≈53 min，**未达 8 min 门限（差约 6.6×）**。根因是**本机 oneDNN 不可用**：
  `enable_mkldnn=True` 会在第一个 det 前向就抛
  `NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support
  [pir::ArrayAttribute<pir::DoubleAttribute>]（onednn_instruction.cc:118）`，
  只能 `enable_mkldnn=False`（run_mode=paddle），CPU 上没有算子加速（`MKLDNN_ENABLED` 记着这个事实）。
  本机**无法**测出 mkldnn 的加速比（一开就崩），所以这里不给"快了 N 倍"的假数字。
· det 侧已按经典 PP-OCR 口径压输入：`text_det_limit_type="max"` + 960 px。
  实测 det 从 77.7 s 降到 15.3 s，且**框数与均分完全不变**（41 框 / 均分 0.995）。
· rec 侧是瓶颈（逐行重构图：每行宽度不同 → 每个新形状都要重新构图）。
  固定成 `[3,48,960]` 能快 2.1×（75 s），但**均分从 0.995 掉到 0.576**（长行被压糊，
  识别成 `Faleuu` 这类乱码）——宁可慢、不可错，**不采用**。
"""

from __future__ import annotations

import contextlib
import importlib
import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from app.core.errors import ApiError, ErrorCode
from app.parse.blocks import BBox, ParsedBlock, ParsedDocument, UncertainNote

#: 进度回调：`(当前页序号 1-based, 总页数)`。
PageCallback = Callable[[int, int], None]

#: 能走 OCR 的图片扩展名（`__init__.parse_material` 用同一份清单分派）。
IMAGE_SUFFIXES: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")

#: 模型缓存目录名（**项目外**）与环境变量覆盖点。本机有清理程序删项目内文件，
#: 模型放项目里第二天就没了，所以固定放用户目录下。
MODEL_DIR_NAME = ".xizhi-ocr-models"
MODEL_DIR_ENV = "XIZHI_OCR_MODEL_DIR"

#: 引擎要用的两个模型（det 59.41 MB + rec 73.30 MB ≈ 133 MB）。
MODEL_NAMES: tuple[str, ...] = ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")

#: 页面渲染 dpi。200 是扫描件 OCR 的常用档位：再高 rec 更慢、再低小字会糊。
RENDER_DPI = 200

#: det 输入边长上限（`max` = 长边压到 960 以内）。见模块 docstring 实测一节。
DET_LIMIT_TYPE = "max"
DET_LIMIT_SIDE_LEN = 960
#: rec 批大小。实测本机 16 与 6 差别不大（瓶颈在逐行构图），保留一个显式值便于调。
REC_BATCH_SIZE = 16

#: 低于此置信度的行**不写块**，只统计数量并在存疑说明里报出来（不静默丢内容）。
#: 为什么需要这道闸：OCR 在纯图 / 空白区域会"认出"毫无意义的东西 —— 实测把一张
#: 整页灰底图识别成一个 0.39 置信度的全页 `█`。那不是内容，写进块表就是编造。
#: 阈值取 0.5 的依据：真实扫描教材页的正文行均分 0.995（最低行也在 0.9 以上），
#: 噪声在 0.4 以下，中间留了足够宽的隔离带。
MIN_CONFIDENCE = 0.5

#: 本机 oneDNN 是否可用。paddle 3.3.1 打开 mkldnn 会在 det 前向直接抛
#: `NotImplementedError`（见模块 docstring），所以只能关。换 paddle 版本后若
#: mkldnn 恢复正常，把这里改成 True 并在 `ENGINE_KWARGS` 里去掉 `enable_mkldnn=False`
#: 即可（`test_parse_ocr.py` 的 8 min 门限断言会随这个开关自动启用）。
MKLDNN_ENABLED = False

#: 引擎构造参数：**唯一来源**，prefetch 脚本与运行时共用同一份，避免两边跑不同模型。
ENGINE_KWARGS: dict[str, Any] = {
    "lang": "ch",
    # 关掉 3 个可选分类器 → 只需 det + rec 两个模型（≈133 MB），也省掉两次额外前向。
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_textline_orientation": False,
    "text_det_limit_type": DET_LIMIT_TYPE,
    "text_det_limit_side_len": DET_LIMIT_SIDE_LEN,
    "text_recognition_batch_size": REC_BATCH_SIZE,
    "enable_mkldnn": MKLDNN_ENABLED,
}

#: 依赖缺失时的中文文案。要点：说清"缺什么""怎么补"，并提到模型缓存目录 ——
#: 离线环境只有装了包、没预取模型时，用户照第一句装完仍然跑不起来。
_MISSING_DEPS_MESSAGE = (
    "未安装 OCR 依赖，图片与扫描件暂时解析不了。请在服务器上执行 "
    'pip install -e ".[ocr]"（paddleocr>=3.7,<4 + paddlepaddle>=3.3,<4）后重试；'
    "离线环境还需要预先取回模型，并把 PADDLE_PDX_CACHE_HOME 指向模型目录"
    "（可用 scripts/prefetch-ocr-models.py，默认目录 ~/.xizhi-ocr-models）。"
)


@dataclass(frozen=True)
class OcrLine:
    """一行识别结果 —— 块的三要素（文本 / 置信度 / 版面坐标）在 OCR 层的载体。"""

    text: str
    confidence: float
    bbox: BBox | None = None


@dataclass
class ScanOcrResult:
    """扫描版 PDF 逐页 OCR 的产物（存疑说明的措辞留给 `pdf.py` 统一写）。"""

    blocks: list[ParsedBlock] = field(default_factory=list)
    pages_ok: int = 0
    failed_pages: list[int] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    dropped_lines: int = 0

    @property
    def mean_confidence(self) -> float:
        return sum(self.confidences) / len(self.confidences) if self.confidences else 0.0


# ---------------------------------------------------------------------------
# 惰性导入 / 可用性探测
# ---------------------------------------------------------------------------


def model_dir() -> Path:
    """模型缓存目录（**项目外**）。`XIZHI_OCR_MODEL_DIR` 可覆盖。"""
    override = os.environ.get(MODEL_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / MODEL_DIR_NAME


def apply_model_cache_env() -> Path:
    """把 `PADDLE_PDX_CACHE_HOME` 指到项目外缓存目录（**必须在 import paddleocr 之前**）。

    已显式设过就不覆盖：部署方可能有自己的模型仓，尊重它。
    """
    target = model_dir()
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(target))
    return target


_PaddleOcrClass: Any | None = None
_AVAILABLE: bool | None = None


def _import_paddle_ocr_class() -> Any:
    """惰性导入 `paddleocr.PaddleOCR`；失败一律转成中文 `ApiError`。"""
    global _PaddleOcrClass
    if _PaddleOcrClass is not None:
        return _PaddleOcrClass

    apply_model_cache_env()
    try:
        module = importlib.import_module("paddleocr")
    except Exception as exc:  # noqa: BLE001 —— 缺包 / 装了但坏了（依赖残缺）都算"不可用"
        raise ApiError(ErrorCode.INTERNAL, _MISSING_DEPS_MESSAGE) from exc
    cls = getattr(module, "PaddleOCR", None)
    if cls is None:  # pragma: no cover —— 只可能是 paddleocr 换了 API
        raise ApiError(ErrorCode.INTERNAL, _MISSING_DEPS_MESSAGE)
    _PaddleOcrClass = cls
    return cls


def ocr_available() -> bool:
    """本进程里 OCR 能不能真正用起来（结果缓存）。

    刻意**不用** `importlib.util.find_spec`：它只能说明"包在"，装坏了（缺依赖文件、
    ABI 不匹配）照样返回 True，真跑起来才炸 —— 那样 `pdf.py` 就没机会走降级路径了。
    """
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            _import_paddle_ocr_class()
        except ApiError:
            _AVAILABLE = False
        else:
            _AVAILABLE = True
    return _AVAILABLE


def ensure_available() -> None:
    """图片材料专用：没有 OCR 就**没得退**（整份材料就是那张图），直接报中文错。"""
    if not ocr_available():
        raise ApiError(ErrorCode.INTERNAL, _MISSING_DEPS_MESSAGE)


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------

_ENGINE: Any | None = None
_ENGINE_LOCK = threading.Lock()


def get_engine() -> Any:
    """取（必要时构造）进程内复用的 OCR 引擎。构造失败给中文文案。"""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        cls = _import_paddle_ocr_class()
        try:
            _ENGINE = cls(**ENGINE_KWARGS)
        except Exception as exc:  # noqa: BLE001 —— paddlex 的异常类型不稳定
            raise ApiError(
                ErrorCode.INTERNAL,
                "OCR 引擎初始化失败（可能是模型文件缺失或损坏）。"
                "离线环境请先执行 python scripts/prefetch-ocr-models.py 预取模型，"
                "并确认 PADDLE_PDX_CACHE_HOME 指向的目录里有两个模型目录："
                + "、".join(MODEL_NAMES),
            ) from exc
        return _ENGINE


def release_engine() -> None:
    """显式释放引擎（长任务收尾别常驻占内存）。重复调用安全。

    释放失败**不影响主流程**：这是个纯优化动作，为它报错只会把已经成功的解析
    变成失败，得不偿失。
    """
    global _ENGINE
    with _ENGINE_LOCK:
        engine, _ENGINE = _ENGINE, None
    if engine is not None:
        with contextlib.suppress(Exception):
            engine.close()


# ---------------------------------------------------------------------------
# 识别（图片 → 行）
# ---------------------------------------------------------------------------


def _as_bbox(raw: Any) -> BBox | None:
    """`rec_boxes` 的一项 → `(x0, y0, x1, y1)`；形状不对就不给坐标（不编）。"""
    try:
        values = [float(v) for v in raw]
    except (TypeError, ValueError):
        return None
    if len(values) != 4:
        return None
    return (values[0], values[1], values[2], values[3])


def _lines_of_image(image: Any) -> tuple[list[OcrLine], int]:
    """跑一次 OCR，返回 `(保留的行, 因置信度过低被丢掉的行数)`。

    `rec_texts` / `rec_scores` / `rec_boxes` 是**同一 list 的下标对齐关系**（实测
    paddleocr 3.7）；长度不一致时按最短的来 —— 宁可少一行，也不能把 A 行的文字
    配 B 行的坐标。
    """
    engine = get_engine()
    try:
        results = engine.predict(image)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ApiError(
            ErrorCode.INTERNAL,
            "OCR 识别过程中出错，这一页没有识别出内容，请稍后重试或换一份更清晰的扫描件",
        ) from exc

    if not results:
        return [], 0
    item = results[0]
    texts = list(item["rec_texts"])
    scores = list(item["rec_scores"])
    boxes = list(item["rec_boxes"])
    count = min(len(texts), len(scores), len(boxes))

    lines: list[OcrLine] = []
    dropped = 0
    for i in range(count):
        text = str(texts[i]).strip()
        confidence = max(0.0, min(1.0, float(scores[i])))
        if not text:
            # 空串块会被 `ParsedDocument` 过滤掉，但"过滤点只有一个"（blocks.py 纪律 2），
            # 所以这里也跳过，免得 line_start 与最终块序列错位。
            continue
        if confidence < MIN_CONFIDENCE:
            dropped += 1
            continue
        lines.append(OcrLine(text=text, confidence=confidence, bbox=_as_bbox(boxes[i])))
    return lines, dropped


def _blocks_of_lines(lines: Sequence[OcrLine], page_no: int) -> list[ParsedBlock]:
    """行 → 块。**一行一块**，`line_start == line_end == 页内行号`。

    为什么 OCR 出来的块一律 `paragraph`：OCR 没有字号信息，本层唯一能用的标题信号
    是"行首章节号"，而正文里"37 个节点"这种以数字开头的句子会被它误判成标题
    （`pdf.py` 的 `_classify` 有字号做第二道否决，这里没有）。凭空多出来的章/节
    会顺着 `sections.py` 污染 P2 的骨架 —— 宁缺毋错，全部记正文。
    """
    return [
        ParsedBlock(
            block_type="paragraph",
            content_md=line.text,
            page_no=page_no,
            line_start=idx,
            line_end=idx,
            bbox=line.bbox,
            ocr_confidence=line.confidence,
        )
        for idx, line in enumerate(lines, start=1)
    ]


def _page_image(page: pymupdf.Page) -> Any:
    """PDF 页 → RGB ndarray（OCR 的输入）。"""
    import numpy as np  # noqa: PLC0415 —— 可选依赖，只在真跑 OCR 时导入

    pix = page.get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csRGB)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return np.ascontiguousarray(arr[:, :, :3])


def _read_image_file(path: Path) -> Any:
    """图片文件 → RGB ndarray。读不出来 / 不是图片 → 中文 `ApiError`。"""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    try:
        with Image.open(path) as handle:
            return np.asarray(handle.convert("RGB"))
    except FileNotFoundError as exc:
        raise ApiError(ErrorCode.NOT_FOUND, "找不到这个图片文件，请重新上传后再试") from exc
    except Exception as exc:  # noqa: BLE001 —— PIL 的异常类型多（含 UnidentifiedImageError）
        raise ApiError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"这个图片读不出来（{path.name} 可能已损坏，或不是常见图片格式），"
            "请转成 PNG / JPG 后再上传",
        ) from exc


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


def parse_scan_pdf(
    doc: pymupdf.Document,
    *,
    on_page: PageCallback | None = None,
) -> ScanOcrResult:
    """**逐页** OCR 一份扫描版 PDF（`doc` 由 `pdf.py` 打开并负责关闭）。

    逐页而不是一次性整份丢进去，就是为了让 `on_page` 能报"当前页/总页"、
    让调用方在页与页之间有机会中断（一页约 159 s，等整份跑完再报进度等于没进度）。

    · 单页失败（渲染或识别出错）**不整份失败**：跳过该页、记下页码，继续下一页 ——
      与 A1-7"单文件失败不影响批次"同向，一份 20 页扫描件不该因为第 7 页坏掉而零产物；
    · `on_page` 抛异常直接向上传播（中断语义，见模块 docstring）。
    """
    result = ScanOcrResult()
    total = doc.page_count
    for index in range(total):
        page_no = index + 1
        if on_page is not None:
            on_page(page_no, total)
        try:
            lines, dropped = _lines_of_image(_page_image(doc[index]))
        except ApiError:
            result.failed_pages.append(page_no)
            continue
        result.blocks.extend(_blocks_of_lines(lines, page_no))
        result.confidences.extend(line.confidence for line in lines)
        result.dropped_lines += dropped
        result.pages_ok += 1
    return result


def parse_image(path: str | Path, *, on_page: PageCallback | None = None) -> ParsedDocument:
    """图片材料（`.png` / `.jpg` / `.jpeg` / `.webp` / `.tif` / `.tiff`）→ 一页 OCR 产块。

    图片没有页码概念，所以 `page_no=1`、`source_type="image"`、进度回调只报 `(1, 1)`。
    一个块也没识别出来时 `parse_method` 记 `None` 并给中文说明：**没产出内容就不写
    "ocr"**（写了就是"解析成功但什么都没有"的假账），与 `pdf.py` 的扫描版分支同一口径。
    """
    p = Path(path)
    ensure_available()
    if on_page is not None:
        on_page(1, 1)

    lines, dropped = _lines_of_image(_read_image_file(p))
    blocks = _blocks_of_lines(lines, 1)
    notes: list[UncertainNote] = []
    tail = (
        f"另有 {dropped} 行置信度低于 {MIN_CONFIDENCE:.2f} 没有写入（避免把噪声当正文）。"
        if dropped
        else ""
    )
    if not lines:
        notes.append(
            UncertainNote(
                kind="low_confidence_ocr",
                severity="medium",
                message=(
                    "OCR 已跑完，但这张图片里没有识别到任何文字，可能是空白图、"
                    "纯图形，或文字太小/太模糊。请人工确认这张图是否需要作为材料。"
                    + tail
                ),
            )
        )

    return ParsedDocument(
        source_type="image",
        blocks=blocks,
        page_count=1,
        parse_method="ocr" if blocks else None,
        uncertain_notes=notes,
    )
