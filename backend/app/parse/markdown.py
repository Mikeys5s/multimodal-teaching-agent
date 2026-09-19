"""块 → 带锚点的 Markdown（归属：P1）。验收项 A1-6。

为什么 Markdown 里要塞 HTML 注释锚点
------------------------------------
A1-6 要求"100% 的 block 可定位到页码"。前端的高亮定位、人工校验工作台、
以及"这个知识点引用的原文是哪一段"的核对，都需要一条**从 Markdown 文本
回到数据库行**的路。HTML 注释是个恰好合适的载体：

  · 渲染 Markdown 时它**不显示**，用户看到的是干净的教材原文；
  · 它是文本的一部分，所以复制、落盘、喂给模型都不会丢；
  · 反过来，模型输出的 `source_quote` 能贴着锚点回到具体 block。

锚点格式（下游按此解析，属稳定契约）：

    <!-- page: 12 -->                       页码变化处插入，1-based
    <!-- block: blk_a1b2c3d4_00042 -->      每个块之前插入

页码锚点是**事件式**的：page_no 与上一块相同就不重复插，只有跨页才出现一行。
这样 PDF 的 Markdown 里页码密度与真实翻页一致，DOCX（page_no 全为 NULL）
则一个页码锚点都没有 —— 不会凭空冒出一堆 `<!-- page: -->`。
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.ids import block_id
from app.parse.blocks import ParsedBlock, ParsedDocument, as_blocks

PAGE_ANCHOR_TEMPLATE = "<!-- page: {page_no} -->"
BLOCK_ANCHOR_TEMPLATE = "<!-- block: {block_id} -->"

#: 块之间、锚点与内容之间的分隔。统一用空行 —— Markdown 的段落语义靠空行。
_SEP = "\n\n"


def page_anchor(page_no: int) -> str:
    """页码锚点。`page_no` 是 1-based，与 `material_blocks.page_no` 同口径。"""
    if page_no < 1:
        raise ValueError(f"页码是 1-based，收到 {page_no}")
    return PAGE_ANCHOR_TEMPLATE.format(page_no=page_no)


def block_anchor(mat_id: str, seq: int) -> str:
    """块锚点。ID 由 `app.models.ids.block_id` 现算 —— 解析层不自己拼字符串。"""
    return BLOCK_ANCHOR_TEMPLATE.format(block_id=block_id(mat_id, seq))


def render_block(block: ParsedBlock) -> str:
    """把单个块渲染成 Markdown。

    heading 块在这里才补 `#` 前缀：层级信息**只**存在 `heading_level` 一处，
    从它渲染出 `#`，而不是在 `content_md` 里再写一遍（两处写就一定会不一致）。
    """
    if block.is_heading:
        level = block.heading_level or 1
        return f"{'#' * level} {block.content_md.strip()}"
    return block.content_md.strip()


def to_markdown(
    doc: ParsedDocument | Sequence[ParsedBlock],
    mat_id: str,
    *,
    start_seq: int = 0,
) -> str:
    """把解析产物拼成带 `page` / `block` 锚点的 Markdown。

    参数
    ----
    doc_or_blocks
        `ParsedDocument` 或直接一串 `ParsedBlock`（供只做了局部解析的场景复用）。
    mat_id
        `mat_xxxxxxxx`。块 ID 由它 + seq 现算，所以**必须**传，不能省。
        seq 走 `ParsedDocument.numbered()`，与 `persist.persist_blocks` 同源，
        锚点里的 ID 与库里的主键必然一致。
    start_seq
        第一块对应的**全局** seq。只在传入的是切片（如 `section_markdown`）
        时才需要设 —— 切片后重新从 0 编号会让锚点指向别的块，比没有锚点更糟。

    返回
    ----
    不含末尾换行的 Markdown 文本。
    """
    blocks = as_blocks(doc)

    parts: list[str] = []
    last_page: int | None = None
    for offset, block in enumerate(blocks):
        # 页码变化处插锚点。page_no 为 None（DOCX）时既不插、也不重置 last_page，
        # 免得 NULL 与某个数字来回跳导致页码锚点重复出现。
        if block.page_no is not None and block.page_no != last_page:
            parts.append(page_anchor(block.page_no))
            last_page = block.page_no

        anchored = f"{block_anchor(mat_id, start_seq + offset)}\n{render_block(block)}"
        parts.append(anchored)

    return _SEP.join(p for p in parts if p)
