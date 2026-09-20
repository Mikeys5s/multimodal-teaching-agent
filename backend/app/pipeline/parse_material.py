"""解析任务（归属：P2）—— 把 P1 的解析链与数据库**接起来**。

## 这个模块为什么存在

P1 的 `app.parse` 已经能"给一个文件路径，返回 `ParsedDocument`"；
`persist_blocks` 已经能"把块写进 `material_blocks`"。
**但没有任何 API 文件 import 过 `app.parse`** —— 整条解析链路从来没被调用过。

**每个零件都做好了，只是没有接在一起。** 本模块就是那根线。

## 事务边界（这是本模块最要紧的职责）

`persist_blocks` 的 docstring 把边界写得很清楚，本模块必须照办：

**① 只追加不删除** → 「重新解析」的清理**由本模块负责**，且
**清理与落库必须在同一事务** —— 否则会出现"旧块删了、新块没落"的**空材料**。

**② 不 commit** → 事务边界在这里。而且
**`materials.status` 的更新必须与落库同一事务** ——
否则会出现"**状态是 done，但块没落**"的**假成功**。
那种状态最坏：界面显示解析完成、点进去什么都没有，而没人知道为什么。

**③ `ocr_confidence` 不写** → 「本批次没有一行 OCR，写了就是假账」。

## 解析失败怎么处理

**必须把 `status` 设成 `failed` 并记下 `error_message`**，不能只是抛异常。
一份素材解析失败后卡在 `parsing`，界面上会永远转圈 —— **"卡住"比"失败"难查得多**。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Chapter, Job, Material, MaterialBlock, Section, utc_now_iso
from app.models.ids import block_id, chapter_id, section_id
from app.parse import parse_material, persist_blocks, split_outline


def clear_derived(session: Session, mat_id: str) -> dict[str, int]:
    """清掉该材料的**派生数据**（块 / 节 / 章）。

    ⚠️ **只删派生数据，不删 `materials` 那一行** —— 素材本身还在，
    只是"解析结果"作废重来。删素材是另一个动作（`DELETE /materials/{id}`）。

    ⚠️ **本函数不 commit**：调用方必须让"清理 + 落库 + 改状态"处在同一事务里。
    单独 commit 一次清理，就等于把材料置于"空的"中间态 ——
    那一刻进程挂掉，得到的是一份**看起来正常但没有任何内容的素材**。
    """
    counts = {
        "sections": session.execute(
            delete(Section).where(Section.material_id == mat_id)
        ).rowcount
        or 0,
        "chapters": session.execute(
            delete(Chapter).where(Chapter.material_id == mat_id)
        ).rowcount
        or 0,
        "blocks": session.execute(
            delete(MaterialBlock).where(MaterialBlock.material_id == mat_id)
        ).rowcount
        or 0,
    }
    return counts


def persist_outline(session: Session, mat_id: str, doc: Any) -> tuple[int, int]:
    """把章 / 节落库。返回（章数, 节数）。

    这一层**归 P2** —— `persist_blocks` 只写块，节与章的落库是调用方的责任
    （见 `app/parse/persist.py` 的职责边界说明）。

    id 由 `ids.chapter_id` / `ids.section_id` 生成，**不自己拼字符串** ——
    素材 id 与章/节的编号规则都是既有的，自己拼就会和别处不一致。
    """
    chapters = split_outline(doc)
    n_sections = 0

    for ch in chapters:
        session.add(
            Chapter(
                id=chapter_id(mat_id, ch.seq),
                material_id=mat_id,
                number=ch.number,
                title=ch.title,
                seq=ch.seq,
                # 章标题块的位置 —— 让"这一章从原文哪一块开始"可回溯
                # ⚠️ 用 `block_id()` 生成，不自己拼字符串 ——
                #    我自己先在注释里写了"不自己拼"，然后又拼了一遍（当场抓到）。
                #    锚点格式只要和 `blocks.py` 不一致，A1-6 的"锚点可定位"就悄悄失效。
                source_block_id=block_id(mat_id, ch.heading_seq),
            )
        )
        for sec in ch.sections:
            session.add(
                Section(
                    id=section_id(mat_id, ch.seq, sec.seq),
                    material_id=mat_id,
                    chapter_id=chapter_id(mat_id, ch.seq),
                    number=sec.number,
                    title=sec.title,
                    seq=sec.seq,
                    source_block_id=block_id(mat_id, sec.heading_seq),
                )
            )
            n_sections += 1

    return len(chapters), n_sections


def run_parse(session: Session, mat_id: str) -> dict[str, Any]:
    """完整跑一遍"解析 → 落库 → 回填统计"，**事务边界在这里**。

    成功返回统计字典；失败会把 `status` 置为 `failed` 并**抛出异常**
    （让调用方/任务层也能看到失败，不是静默）。
    """
    mat = session.get(Material, mat_id)
    if mat is None:
        raise ValueError(f"素材不存在：{mat_id}")

    mat.status = "parsing"
    mat.error_message = None
    session.flush()

    try:
        doc = parse_material(mat.stored_path)

        # ★ 清理与落库在同一事务里（见模块 docstring ①）
        cleared = clear_derived(session, mat_id)
        persist_blocks(session, mat_id, doc)
        n_chapters, n_sections = persist_outline(session, mat_id, doc)

        # ★ 统计与状态和落库同一事务（见模块 docstring ②）
        mat.source_type = doc.source_type
        mat.parse_method = doc.parse_method
        mat.page_count = doc.page_count
        mat.char_count = doc.char_count
        mat.uncertain_notes = json.dumps(
            [asdict(n) for n in doc.uncertain_notes], ensure_ascii=False
        )
        mat.status = "done" if doc.blocks else "partial"
        mat.updated_at = utc_now_iso()

        session.commit()
        return {
            "material_id": mat_id,
            "blocks": len(doc.blocks),
            "chapters": n_chapters,
            "sections": n_sections,
            "cleared": cleared,
        }

    except Exception as exc:  # noqa: BLE001
        # 把失败**写进状态**，而不是只抛异常。
        #
        # 只抛异常的话，素材会永远停在 `parsing` ——
        # 界面上就是无限转圈，而"卡住"比"失败"难查得多。
        session.rollback()
        mat = session.get(Material, mat_id)
        if mat is not None:
            mat.status = "failed"
            mat.error_message = f"{type(exc).__name__}: {exc}"[:500]
            mat.updated_at = utc_now_iso()
            session.commit()
        raise


def run_parse_job(session: Session, job_id: str, mat_id: str) -> dict[str, Any]:
    """任务层入口：跑解析并维护 `jobs` 行的状态与进度。

    **进度字段是给用户看的**，所以 `stage_detail` 必须是**人类可读中文**
    （api-spec §6 的约定：前端直接展示，不加工）。
    """
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"任务不存在：{job_id}")

    job.status = "running"
    job.progress = 10
    job.stage_detail = "正在解析文档结构"
    job.started_at = utc_now_iso()
    session.commit()

    try:
        result = run_parse(session, mat_id)
    except Exception as exc:  # noqa: BLE001
        job = session.get(Job, job_id)
        if job is not None:
            job.status = "failed"
            job.progress = 100
            job.stage_detail = "解析失败"
            job.error_message = f"{type(exc).__name__}: {exc}"[:500]
            job.finished_at = utc_now_iso()
            session.commit()
        raise

    job = session.get(Job, job_id)
    if job is not None:
        job.status = "done"
        job.progress = 100
        job.stage_detail = (
            f"解析完成：{result['blocks']} 个块、"
            f"{result['chapters']} 章 {result['sections']} 节"
        )
        job.result_json = json.dumps(result, ensure_ascii=False)
        job.finished_at = utc_now_iso()
        session.commit()
    return result
