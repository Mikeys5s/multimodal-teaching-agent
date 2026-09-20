"""素材解析链路（归属：P1 · DakerDack）。

规格：SPEC §5.1 / §4.4；验收项 A1-2 / A1-5 / A1-6 / F1.2。

本批次的范围
------------
已实现：文本层 PDF（PyMuPDF 文本 API）、DOCX（python-docx）、PPTX（python-pptx）、
扫描版 PDF **识别**、块落库、带页锚点的 Markdown、章/节骨架推断。
未实现：OCR（扫描版只识别不解析）、图片、音频（D-08 保留不启用）。

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
| `pdf.py` | 文本层 PDF 逐页抽块、扫描版判定 |
| `docx.py` | DOCX 段落/表格抽块 |
| `pptx.py` | PPTX 逐张幻灯片抽块（含表格与演讲者备注） |
| `markdown.py` | 块 → 带页锚点/块锚点的 Markdown |
| `sections.py` | 章/节骨架推断、节级片段切分 |
| `persist.py` | 落 `material_blocks` |

⚠️ 依赖装在可选组，**分成轻重两组**：
  · `pip install -e ".[parse]"`  —— 轻量解析依赖（pymupdf / python-docx /
    python-pptx，几十 MB）。**要复现本模块的用例只装这一组就够**。
  · `pip install -e ".[ocr]"`    —— paddleocr + paddlepaddle，**几个 GB**。
    本批次不需要它们：A1-2 的口径就是"文本层 PDF 不走 OCR"，扫描版只识别不解析。
    （下限锁在 paddleocr 3.x / paddlepaddle 3.x：PyPI 上 `paddlepaddle` 只有
    3.0.0 起才有 win + cp313 wheel，2.x 在 Python 3.13 上装不上；而
    `paddleocr 2.9.1` 又依赖 numpy<2.0，与本环境的 numpy 2.x 冲突。）
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
from app.parse.pdf import MAX_PAGES, parse_pdf
from app.parse.persist import persist_blocks
from app.parse.pptx import parse_pptx
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
    "ParsedBlock",
    "ParsedChapter",
    "ParsedDocument",
    "ParsedSection",
    "UncertainNote",
    "block_anchor",
    "page_anchor",
    "parse_docx",
    "parse_material",
    "parse_pdf",
    "parse_pptx",
    "persist_blocks",
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
    ".pptx": parse_pptx,
}

#: 认得出、但本批次还没接的扩展名 → 给用户一句**说明原因**的中文，而不是
#: 笼统的"不支持"。用户看到"暂不支持"会反复重试，看到"本批次暂不支持图片"
#: 才知道要么等、要么转格式。
_PENDING_SUFFIXES = {
    ".ppt": "PPT",
    ".doc": "旧版 .doc",
    ".png": "图片",
    ".jpg": "图片",
    ".jpeg": "图片",
    ".webp": "图片",
    ".mp3": "音频",
    ".wav": "音频",
    ".m4a": "音频",
}

#: 少数格式有比"换个格式"更具体的建议，单独给整句文案。
#: 旧版 `.ppt` 与 `.pptx` 只差一次"另存为"，用户自己就能解决；这时让他"转为
#: PDF 或 DOCX"是白丢一遍版式，所以单独说清楚该存成什么。
_PENDING_MESSAGES = {
    ".ppt": (
        "旧版 .ppt（PPT 97-2003）格式不支持解析，"
        "请用 PowerPoint 另存为 .pptx 后再上传，或转为 PDF / DOCX"
    ),
}


def parse_material(path: str | Path) -> ParsedDocument:
    """按扩展名分派到对应解析器 —— 解析链路的稳定入口。

    失败一律是带中文文案的 `ApiError`，**单文件失败不会影响其他文件**
    （A1-7 失败隔离：调用方逐个文件调用本函数，捕获 `ApiError` 记到
    `materials.error_message` 即可，批次继续跑）。

    · `.pdf` → `parse_pdf`（含扫描版判定、加密/损坏/超页数报错）
    · `.docx` → `parse_docx`
    · `.pptx` → `parse_pptx`（一张幻灯片一页；旧版 `.ppt` 仍不支持，提示另存为）
    · 其余 → `UNSUPPORTED_FORMAT`，消息里点出具体扩展名与替代做法
    """
    p = Path(path)
    if not p.is_file():
        raise ApiError(ErrorCode.NOT_FOUND, "找不到这个文件，请重新上传后再试")

    suffix = p.suffix.lower()
    parser = _PARSERS.get(suffix)
    if parser is not None:
        return parser(p)

    specific = _PENDING_MESSAGES.get(suffix)
    if specific is not None:
        raise ApiError(ErrorCode.UNSUPPORTED_FORMAT, specific)

    pretty = _PENDING_SUFFIXES.get(suffix)
    if pretty is not None:
        raise ApiError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"{pretty} 格式本批次暂不支持解析，请转为 PDF 或 DOCX 后再上传",
        )
    shown = suffix or "无扩展名"
    raise ApiError(
        ErrorCode.UNSUPPORTED_FORMAT,
        f"暂不支持 {shown} 格式，请转为 PDF 或 DOCX 后再上传",
    )
