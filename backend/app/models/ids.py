"""确定性 ID 生成（归属：P2）。

规格：docs/data-model.md §0「主键约定」

为什么不用随机 UUID
-------------------
验收项 **A2-7 要求「同输入可复现」**。抽取是离线、可反复重跑的过程（SPEC §4.8），
"这次重跑比上次改了什么"必须能回答。随机 ID 会让同一份材料重跑后得到完全不同的主键，
逐条 diff 退化成整库重灌 —— 可复现就只剩一句口号。

确定性 ID 让 A2-7 天然成立，而且 ID 自带归属信息，人工校验时好定位。

为什么用位置序号 seq 而不是章节号 number
----------------------------------------
章节号是"保留材料原貌"的展示值（`3.2` 这种）。直接拼进 ID 有两个问题：
  ① 节号若不含章前缀（有的材料节号就是 `1` / `2`），跨章会撞 ID；
  ② 需要额外的规范化规则，规则越多越容易出错。
`seq` 由解析阶段按文档顺序赋值，同一父节点下天然唯一，无歧义。

章节号仍完整存在 `number` 字段里供展示与检索，不丢信息。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

HASH_LEN = 8
_CHUNK = 1024 * 1024


# ---------------------------------------------------------------------------
# 文件内容 hash
# ---------------------------------------------------------------------------


def hash_bytes(data: bytes) -> str:
    """返回完整 SHA-256 十六进制串（64 位）。

    完整串用于 `materials.file_hash`（唯一索引，成本控制 C2）；
    取前 8 位用于生成 `material_id`。
    """
    return hashlib.sha256(data).hexdigest()


def hash_file(path: str | Path) -> str:
    """流式计算文件 SHA-256，避免把大文件整个读进内存。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 各实体 ID
# ---------------------------------------------------------------------------


def _seq(value: int, name: str, width: int) -> str:
    """把序号格式化成固定宽度；负数直接报错，不做兜底。"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} 必须是 int，收到 {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} 不能为负：{value}")
    return f"{value:0{width}d}"


def material_id(file_hash: str) -> str:
    """`mat_<sha1[:8]>`。注意：`file_hash` 是完整串（由 hash_bytes / hash_file 得到）。"""
    if not file_hash or len(file_hash) < HASH_LEN:
        raise ValueError("file_hash 看起来不是完整的 SHA-256 十六进制串")
    return f"mat_{file_hash[:HASH_LEN]}"


def material_hash_part(mat_id: str) -> str:
    """从 `mat_xxxx` 里取出 hash 部分，供下游 ID 拼接。"""
    prefix, _, rest = mat_id.partition("_")
    if prefix != "mat" or not rest:
        raise ValueError(f"不是合法的 material_id：{mat_id}")
    return rest


def block_id(mat_id: str, seq: int) -> str:
    """`blk_<材料hash8>_<seq:05d>`。"""
    return f"blk_{material_hash_part(mat_id)}_{_seq(seq, 'block.seq', 5)}"


def chapter_id(mat_id: str, chapter_seq: int) -> str:
    """`ch_<材料hash8>_<章seq:03d>`。"""
    return f"ch_{material_hash_part(mat_id)}_{_seq(chapter_seq, 'chapter.seq', 3)}"


def section_id(mat_id: str, chapter_seq: int, section_seq: int) -> str:
    """`sec_<材料hash8>_<章seq:03d>_<节seq:03d>`。"""
    return (
        f"sec_{material_hash_part(mat_id)}"
        f"_{_seq(chapter_seq, 'chapter.seq', 3)}"
        f"_{_seq(section_seq, 'section.seq', 3)}"
    )


def knowledge_point_id(mat_id: str, chapter_seq: int, section_seq: int, kp_seq: int) -> str:
    """`kp_<材料hash8>_<章seq>_<节seq>_<节内seq:03d>`。"""
    return (
        f"kp_{material_hash_part(mat_id)}"
        f"_{_seq(chapter_seq, 'chapter.seq', 3)}"
        f"_{_seq(section_seq, 'section.seq', 3)}"
        f"_{_seq(kp_seq, 'knowledge_point.seq', 3)}"
    )


# ---------------------------------------------------------------------------
# 反向解析（调试与人工校验时用）
# ---------------------------------------------------------------------------


def material_hash_of(entity_id: str) -> str:
    """从任意实体 ID 里取出所属材料的 hash8。

    用于回答"这个知识点是哪份材料来的"，不需要查库。
    """
    parts = entity_id.split("_")
    if len(parts) < 2:
        raise ValueError(f"无法解析的 ID：{entity_id}")
    return parts[1]


def describe(entity_id: str) -> dict[str, str]:
    """把 ID 拆成人类可读的组件，人工校验工作台里直接展示。"""
    parts = entity_id.split("_")
    kind = parts[0]
    out = {"kind": kind, "raw": entity_id}
    if len(parts) >= 2:
        out["material_hash"] = parts[1]
    labels = {1: "chapter_seq", 2: "section_seq", 3: "seq"}
    for idx, label in enumerate(parts[2:], start=1):
        out[labels.get(idx, f"part{idx}")] = label
    return out
