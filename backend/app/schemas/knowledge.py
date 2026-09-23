"""知识点相关的契约（归属：P2）。对应 docs/api-spec.md §4.2 / §4.3（端点 14、15）。

★ 这里的 `PrerequisiteOut.reason` 与 `KpDetailOut.source.quote` 是**创新点的对外呈现**：
"为什么这个知识点要排在前面"和"这句话是从材料哪一页来的"，都必须能在前端逐条展示。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 4.2 列表项（GET /api/knowledge-points）
# ---------------------------------------------------------------------------


class ChapterRefOut(BaseModel):
    """知识点所属章节的引用（列表页只需展示，不需要展开）。"""

    id: str
    number: str | None = None
    title: str


class SectionRefOut(BaseModel):
    id: str
    number: str | None = None
    title: str


class SourceRefOut(BaseModel):
    """溯源信息 —— **A2-3 溯源覆盖率 100% 的对外体现**。

    `quote` 在数据库层是 NOT NULL，所以这里也非空：拿不到原文的知识点根本不允许入库。
    """

    material_id: str
    material_name: str = Field(description="文件名，直接展示给用户")
    page: int | None = None
    block_id: str | None = None
    quote: str = Field(description="原文片段，非空；前端的「看原文」跳转就定位到这里")


class KpItemOut(BaseModel):
    """知识点列表项。字段与 api-spec §4.2 逐字对应。"""

    id: str
    name: str
    summary_md: str = Field(description="一句话讲清楚「这是什么」")
    difficulty: int = Field(description="1–5，前端据此做颜色映射")
    difficulty_reason: str | None = Field(
        default=None, description="为什么是这个难度 —— 难度判定要可解释，不是黑盒打分"
    )
    kp_type: str = Field(description="concept / skill / theorem / method / fact")

    chapter: ChapterRefOut
    section: SectionRefOut
    source: SourceRefOut

    prerequisite_count: int = 0
    example_count: int = 0
    misconception_count: int = 0

    needs_review: bool = Field(description="待核实标记，前端应显著提示")
    confidence: float | None = None


# ---------------------------------------------------------------------------
# 4.3 详情（GET /api/knowledge-points/{id}）
# ---------------------------------------------------------------------------


class PrerequisiteOut(BaseModel):
    """一条前置依赖边。

    `reason` 是**关系型字段**（在数据库层 NOT NULL），不是装饰 ——
    「为什么这个要排在前面」必须能说清楚，否则学习路径就成了黑盒拓扑排序。
    """

    kp_id: str
    name: str
    relation_type: str = Field(description="hard=不会就学不动；soft=会了更好懂")
    reason: str = Field(description="依赖理由：不学懂前置会卡在哪")
    confidence: float | None = None


class ExampleOut(BaseModel):
    """典型例题（`kp_examples`）。"""

    id: str
    question_type: str
    stem_md: str
    options_json: str | None = Field(default=None, description="选项数组 JSON 字符串")
    answer_md: str
    analysis_md: str | None = None
    difficulty: int | None = None
    source_page: int | None = None
    source: str | None = Field(default=None, description="human / derived")


class MisconceptionOut(BaseModel):
    """常见误区（`kp_misconceptions`）。

    `source` 必须如实反映来源 —— **LLM 推断的不得伪装成人类确认过的结论**。
    前端应据此用不同样式展示（例如 `llm_inferred` 加"待核实"提示）。
    """

    id: str
    description: str = Field(description="学生的错误理解是什么")
    cause: str | None = None
    remedy: str | None = Field(default=None, description="怎么纠正 —— 答疑提示语的素材")
    source: str | None = Field(default=None, description="material / llm_inferred / human")
    confidence: float | None = None


class KpDetailOut(KpItemOut):
    """知识点详情 = 列表项 + 三段展开。

    继承而不是重复定义，是为了保证**同一字段在列表与详情里语义一致**。
    """

    prerequisites: list[PrerequisiteOut] = Field(default_factory=list)
    examples: list[ExampleOut] = Field(default_factory=list)
    misconceptions: list[MisconceptionOut] = Field(default_factory=list)
