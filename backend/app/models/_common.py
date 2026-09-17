"""模型层共用工具与取值集合（归属：P2）。

取值集合与 docs/data-model.md §2 一一对应。**改这里必须同步改规格** ——
这些元组同时被 ORM 的 CHECK 约束和上层校验用到，两处不同步就会出现
"应用层放过了、数据库拒绝了"这类难查的问题。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import TextClause, text

# ---------------------------------------------------------------------------
# 时间
# ---------------------------------------------------------------------------

# 库里时间字段的唯一合法格式（UTC，带 +00:00 偏移）。
#
# 为什么必须收敛到「唯一格式」：字段是 TEXT，排序靠字符串字典序。
# 只要混进一个带本地偏移的时间（如 2026-09-17T20:34:56+08:00），
# 字典序就会把一个"实际更早"的时间排到后面 —— **而且全程不报错**。
# 统一 UTC 单一格式后，字典序才等价于时间序。
UTC_ISO_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"


def utc_now_iso() -> str:
    """当前时间的 UTC ISO8601 字符串，格式与 `UTC_ISO_FORMAT` 严格一致。"""
    return datetime.now(UTC).strftime(UTC_ISO_FORMAT)


def utc_iso_check(column: str) -> str:
    """生成校验时间字段格式的 CHECK 表达式。

    做法：把存进去的字符串**再走一遍 strftime 归一化**，再比对是否与原文一致。

    为什么不用 GLOB 模式匹配：GLOB 只校验"形状"。实测
    `2026-13-17T12:34:56+00:00`（13 月）能骗过 GLOB，但会被 strftime
    归一化成 NULL 从而被拒。此外它还会拒绝带本地时区偏移的时间，
    强制全库统一 UTC。
    """
    return f"{column} IS strftime('{UTC_ISO_FORMAT}', {column})"


def utc_server_default() -> TextClause:
    """时间列的数据库默认值 —— 绕过 ORM 直接写库时也是正确格式。

    与 `utc_now_iso()`（ORM 默认值）一起构成两层防护，CHECK 再兜底。
    三层下来，"时间格式写错"这件事基本不可能发生。
    """
    return text(f"(strftime('{UTC_ISO_FORMAT}','now'))")


# ---------------------------------------------------------------------------
# 取值集合（对应 docs/data-model.md §2）
# ---------------------------------------------------------------------------

# materials.source_type —— audio 保留但初赛不启用（SPEC §6.1 D-08）
SOURCE_TYPES: tuple[str, ...] = ("pdf_text", "pdf_scan", "docx", "pptx", "image", "audio")
# materials.parse_method —— asr 同上，保留不启用
PARSE_METHODS: tuple[str, ...] = ("text_extract", "multimodal_llm", "ocr", "asr")
MATERIAL_STATUSES: tuple[str, ...] = ("pending", "parsing", "done", "failed", "partial")

BLOCK_TYPES: tuple[str, ...] = (
    "heading",
    "paragraph",
    "table",
    "code",
    "formula",
    "image_caption",
    "question",
    "other",
)

KP_TYPES: tuple[str, ...] = ("concept", "skill", "theorem", "method", "fact")

# kp_prerequisites: hard = 不会就学不动；soft = 会了更好懂
RELATION_TYPES: tuple[str, ...] = ("hard", "soft")
# 这条边由哪条线索产生（双通道融合，SPEC §1.5）
SOURCE_CHANNELS: tuple[str, ...] = ("structure", "semantic", "both")


# ---------------------------------------------------------------------------
# CHECK 约束辅助
# ---------------------------------------------------------------------------


def sql_in(values: Iterable[str]) -> str:
    """把取值集合渲染成 SQL 的 IN 列表，供 CHECK 约束使用。

    ⚠️ 只在**建模期**由本模块的常量生成，不接受任何外部/用户输入 ——
    这里做的是字符串拼接，虽然取值都是我们自己写死的字面量，
    但保持"永不接受外部输入"这条纪律很重要。
    """
    return ", ".join(f"'{v}'" for v in values)
