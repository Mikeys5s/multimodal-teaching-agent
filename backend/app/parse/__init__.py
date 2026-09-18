"""素材解析链路（归属：P1 · DakerDack）。

规格：SPEC §5.1 / §4.4；验收项 A1-2 / A1-5 / A1-6 / F1.2。

本批次的范围
------------
已实现：文本层 PDF（PyMuPDF 文本 API）、DOCX（python-docx）、
**图片材料与扫描版 PDF 的 OCR（`[ocr]` 可选依赖）**、块落库、带页锚点的 Markdown、
章/节骨架推断。
未实现：PPTX、音频（D-08 保留不启用）。

产物：带块锚点的 Markdown + `material_blocks` 行。**不写** chapters / sections
表 —— 那是 P2 的 outline 领域，本批次只产出骨架结构供其落库（见 `sections.py`）。

横向流转
--------
    path ──parse_material──▶ ParsedDocument ──┬─▶ persist_blocks  → material_blocks
                                              ├─▶ to_markdown     → 带锚点 Markdown
                                              └─▶ split_sections  → 节骨架（供按节投喂）

模块划分
--------
| 文件 | 职责 |
|---|---|
| `blocks.py` | 与存储无关的数据结构 + 章节号识别（共用词汇表） |
| `pdf.py` | 文本层 PDF 逐页抽块、扫描版判定与（OCR 可用时的）扫描版解析 |
| `ocr.py` | OCR 引擎封装与惰性导入：扫描版 PDF 逐页 OCR、图片材料解析 |
| `docx.py` | DOCX 段落/表格抽块 |
| `markdown.py` | 块 → 带页锚点/块锚点的 Markdown |
| `sections.py` | 章/节骨架推断、节级片段切分 |
| `persist.py` | 落 `material_blocks` |

依赖分两组，**不要混装**
------------------------
· `pip install -e ".[parse]"` → pymupdf / python-docx / python-pptx（轻量，日常开发）
· `pip install -e ".[ocr]"`   → paddleocr + paddlepaddle（几个 GB，只有真要跑 OCR 才需要）

`ocr.py` 对 paddleocr 是**惰性导入**：没装 `[ocr]` 的机器上，文本层 PDF / DOCX
照常解析，只有"图片材料"会得到一句可操作的中文报错、扫描版 PDF 退回
"0 块 + 中文说明"的降级路径（**不会**把整份材料判失败）。
"""

from __future__ import annotations

from pathlib import Path

from app.core.errors import ApiError, ErrorCode
from app.parse.blocks import (
    BBox,
    HeadingNumber,
    ParsedBlock,
    ParsedDocument,
    UncertainNote,
    split_heading_number,
)
from app.parse.docx import parse_docx
from app.parse.markdown import block_anchor, page_anchor, render_block, to_markdown
from app.parse.ocr import IMAGE_SUFFIXES, OcrLine, PageCallback, parse_image, release_engine
from app.parse.pdf import MAX_PAGES, parse_pdf
from app.parse.persist import persist_blocks
from app.parse.sections import (
    ParsedChapter,
    ParsedSection,
    section_markdown,
    split_outline,
    split_sections,
)

__all__ = [
    "MAX_PAGES",
    "BBox",
    "HeadingNumber",
    "IMAGE_SUFFIXES",
    "OcrLine",
    "ParsedBlock",
    "ParsedChapter",
    "ParsedDocument",
    "ParsedSection",
    "UncertainNote",
    "block_anchor",
    "page_anchor",
    "parse_docx",
    "parse_image",
    "parse_material",
    "parse_pdf",
    "persist_blocks",
    "release_engine",
    "render_block",
    "section_markdown",
    "split_heading_number",
    "split_outline",
    "split_sections",
    "to_markdown",
]

#: 本批次能真解析的扩展名 → 解析器
_PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
}

#: 认得出、但本批次还没接的扩展名 → 给用户一句**说明原因**的中文，而不是
#: 笼统的"不支持"。用户看到"暂不支持"会反复重试，看到"本批次暂不支持 PPTX"
#: 才知道要么等、要么转格式。
_PENDING_SUFFIXES = {
    ".pptx": "PPTX",
    ".ppt": "PPT",
    ".doc": "旧版 .doc",
    ".mp3": "音频",
    ".wav": "音频",
    ".m4a": "音频",
}


def parse_material(
    path: str | Path,
    on_page: PageCallback | None = None,
) -> ParsedDocument:
    """按扩展名分派到对应解析器 —— 解析链路的稳定入口。

    失败一律是带中文文案的 `ApiError`，**单文件失败不会影响其他文件**
    （A1-7 失败隔离：调用方逐个文件调用本函数，捕获 `ApiError` 记到
    `materials.error_message` 即可，批次继续跑）。

    · `.pdf` → `parse_pdf`（含扫描版判定、加密/损坏/超页数报错；
      扫描版在 OCR 可用时逐页 OCR）
    · `.docx` → `parse_docx`
    · `.png` / `.jpg` / `.jpeg` / `.webp` / `.tif` / `.tiff` → `parse_image`（OCR，
      需要 `[ocr]` 可选依赖）
    · 其余 → `UNSUPPORTED_FORMAT`，消息里点出具体扩展名与替代做法

    `on_page(当前页序号, 总页数)` 是 P2 的异步 job 用来报进度的钩子，只有真正
    按页解析的路径（扫描版 PDF / 图片）会回调；默认 `None`，对现有调用零影响。
    """
    p = Path(path)
    if not p.is_file():
        raise ApiError(ErrorCode.NOT_FOUND, "找不到这个文件，请重新上传后再试")

    suffix = p.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return parse_image(p, on_page=on_page)
    if suffix == ".pdf":
        # PDF 单独一条：只有它需要 `on_page`（扫描版逐页 OCR 时要报进度）
        return parse_pdf(p, on_page=on_page)

    parser = _PARSERS.get(suffix)
    if parser is not None:
        return parser(p)

    pretty = _PENDING_SUFFIXES.get(suffix)
    if pretty is not None:
        raise ApiError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"{pretty} 格式本批次暂不支持解析，请转为 PDF 或 DOCX 后再上传",
        )
    shown = suffix or "无扩展名"
    raise ApiError(
        ErrorCode.UNSUPPORTED_FORMAT,
        f"暂不支持 {shown} 格式，请转为 PDF、DOCX 或图片后再上传",
    )
