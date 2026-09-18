"""块落库（归属：P1）。写的是 P2 的 `material_blocks` 表。

职责边界（重要）
----------------
· 本模块**只追加**，不删除、不 upsert。"重新解析"要先把该材料已有的块清掉，
  那是调用方（P2 的解析任务）的事 —— 一个叫 `persist_blocks` 的函数顺手删表，
  是最容易造成数据意外丢失的设计。跨领域删数据的后果由删除方承担。
  P2 的清库动作必须在**同一事务**里：删完就落，中途失败要整体回滚，
  否则会出现"旧块删了、新块没落"的空材料。
· 不 commit。事务边界属于调用方 —— 落库与 `materials.status` 的更新必须同一
  事务，不然会出现"状态 done 但块没落"的假成功。

seq 从哪来
----------
只从 `ParsedDocument.numbered()` 来。它与 `markdown.to_markdown` 是同一个入口，
所以**块锚点里的 seq 与库里的 seq 不可能不一致**（A1-6 的地基）。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.ids import block_id
from app.models.material import MaterialBlock
from app.parse.blocks import ParsedDocument


def bbox_to_json(bbox: tuple[float, float, float, float] | None) -> str | None:
    """版面坐标 → `[x1,y1,x2,y2]` JSON 串（紧凑分隔符，与列注释同形）。"""
    if bbox is None:
        return None
    return json.dumps([float(v) for v in bbox], separators=(",", ":"))


def persist_blocks(session: Session, mat_id: str, doc: ParsedDocument) -> list[str]:
    """把解析产物写成 `material_blocks` 行，返回写入的主键列表（按 seq 顺序）。

    · `id = block_id(mat_id, seq)`，`seq` 整份材料内**全局连续、从 0 开始**；
    · `ts_start_ms` / `ts_end_ms` 是音频字段，**本批次不写**（保留不启用，D-08）；
    · `ocr_confidence` 逐块照抄解析产物：走 OCR 的块带上真实置信度，
      文本层 PDF / DOCX 的块是 `None`（没跑过 OCR，填数字就是假账）；
    · 只 `flush` 不 `commit`，事务边界交给调用方。
    """
    ids: list[str] = []
    for seq, block in doc.numbered():
        row_id = block_id(mat_id, seq)
        session.add(
            MaterialBlock(
                id=row_id,
                material_id=mat_id,
                seq=seq,
                page_no=block.page_no,
                line_start=block.line_start,
                line_end=block.line_end,
                block_type=block.block_type,
                heading_level=block.heading_level,
                content_md=block.content_md,
                image_path=block.image_path,
                bbox=bbox_to_json(block.bbox),
                ocr_confidence=block.ocr_confidence,
            )
        )
        ids.append(row_id)

    # flush 而不是 commit：让 UNIQUE(material_id, seq) 之类的约束**当场**报错，
    # 而不是拖到调用方 commit 时才炸（那时调用方已经以为写入成功了）。
    session.flush()
    return ids
