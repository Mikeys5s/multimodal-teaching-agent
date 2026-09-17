"""模型层共用工具与取值集合（归属：P2）。

取值集合与 docs/data-model.md §2 一一对应。**改这里必须同步改规格** ——
这些元组同时被 ORM 的 CHECK 约束和上层校验用到，两处不同步就会出现
"应用层放过了、数据库拒绝了"这类难查的问题。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# 时间
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    """UTC ISO8601 字符串（秒精度）。

    统一存 UTC，不存本地时间 —— 否则一旦有人在不同时区跑脚本，
    `created_at` 就没法比大小了。
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat()


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
