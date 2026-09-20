"""质量报告与导出的契约（归属：P2）。对应 docs/api-spec.md §4.5 / §4.6（端点 18、19）。

★ 质量报告页是 Demo 视频里的一个亮点镜头 —— **把工程严谨度可视化**。
所以这里的每个比率都对应一条验收指标，字段名不为了"好看"而简化。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 4.6 质量报告（GET /api/report/quality）
# ---------------------------------------------------------------------------


class MaterialStatsOut(BaseModel):
    total: int = 0
    done: int = 0
    failed: int = 0
    avg_quality_score: float | None = Field(default=None, description="解析质量自评均值 0–1")


class KnowledgePointStatsOut(BaseModel):
    total: int = 0
    structure_complete_rate: float = Field(
        default=0.0, description="★ 三级结构完整率，目标 1.0（A2-1）"
    )
    five_field_complete_rate: float = Field(
        default=0.0, description="五要素完备率（名称/摘要/难度/类型/溯源）"
    )
    grounding_rate: float = Field(default=0.0, description="★ 溯源覆盖率，目标 1.0（A2-3）")
    needs_review_count: int = 0


class GraphStatsReportOut(BaseModel):
    """图谱层面的工程指标 —— **这几个数字是给评委看的**。"""

    edge_count: int = 0
    cycle_count: int = Field(default=0, description="★ 必须为 0（B1-2）")
    pruned_count: int = Field(default=0, description="因成环被剪除的边数（软删除，留痕）")
    conflict_count: int = Field(default=0, description="结构-语义冲突边数（B1-4）")
    reason_complete_rate: float = Field(default=0.0, description="★ 边理由完备率，目标 1.0（B1-5）")
    prerequisite_sampling_pass_rate: float | None = Field(
        default=None, description="人工抽检的前置依赖正确率，暂缺时为 null"
    )


class QaStatsOut(BaseModel):
    session_count: int = 0
    turn_count: int = 0
    grounded_rate: float = Field(default=0.0, description="★ 接地率，目标 1.0（幻觉率 0）")
    refuse_count: int = Field(default=0, description="越界拒答次数 —— 拒答是能力，不是缺陷")


class AcceptanceRowOut(BaseModel):
    """一条验收指标的**实测结果**。

    ★ 报告页的「红线映射」就是它 —— 把"我们声称达标"变成"可当场核对"。

    `kind` 必须显式给出（`rate` / `count`）：
    **不能靠"期望值 ≤ 1.0 就当比率"来猜** —— 环数期望是 0，但它是**计数**，
    用百分比显示会变成「0.00%」，读者会以为在说比率。
    """

    label: str = Field(description="验收条目名，如「B1-2 依赖图环数」")
    expected: float = Field(description="期望值")
    kind: str = Field(description="`rate`（比率，按百分比展示）或 `count`（计数，按整数展示）")
    actual: float | None = Field(default=None, description="实测值；取不到时为 null")
    passed: bool | None = Field(
        default=None,
        description=(
            "是否达标。**取不到值一律算不达标**（false）；"
            "**样本为 0 时为 null** —— 那是「无从判定」，不是「不达标」，"
            "两者不能混为一谈，否则会出现「0 个数据也五项全绿」的真空满足"
        ),
    )
    sample_size: float | None = Field(
        default=None,
        description="该指标的样本量。**为 0 时 passed 必为 null** —— 让评审一眼看得出数据量",
    )


class QualityReportOut(BaseModel):
    """`GET /api/report/quality` 的四段式统计。"""

    materials: MaterialStatsOut = Field(default_factory=MaterialStatsOut)
    knowledge_points: KnowledgePointStatsOut = Field(default_factory=KnowledgePointStatsOut)
    graph: GraphStatsReportOut = Field(default_factory=GraphStatsReportOut)
    qa: QaStatsOut = Field(default_factory=QaStatsOut)
    acceptance: list[AcceptanceRowOut] = Field(
        default_factory=list,
        description=(
            "★ 验收指标的逐条实测（v1.5 新增）。与四段式统计**同源** —— "
            "都来自 `app/quality.py::compute()`，不存在'报告页一套、验收另一套'。"
        ),
    )


# ---------------------------------------------------------------------------
# 4.5 导出（GET /api/export/knowledge-points）
# ---------------------------------------------------------------------------

# 导出支持两种格式：
#   format=json -> 全字段 JSON（结构同 `ExportKpOut` 的数组）
#   format=csv  -> 扁平 CSV，含溯源列
#
# ⚠️ 两者都是**非 JSON 响应**或非包封响应，`request_id` 走 `X-Request-ID` 响应头
#    （api-spec §1.1 的非 JSON 例外条款）。


class ExportKpOut(BaseModel):
    """导出条目 —— 扁平结构，**含溯源列**，便于用 Excel 直接核对。"""

    id: str
    name: str
    summary_md: str
    difficulty: int
    difficulty_reason: str | None = None
    kp_type: str

    chapter_number: str | None = None
    chapter_title: str
    section_number: str | None = None
    section_title: str

    source_material_id: str
    source_material_name: str
    source_page: int | None = None
    source_quote: str

    prerequisite_count: int = 0
    needs_review: bool = False


class ExportHashOut(BaseModel):
    """导出请求的响应（当 `format` 需要异步生成时使用）。

    初赛数据量为千级，直接同步返回文件流即可 —— 这个模型保留给"将来导出很大"的情况。
    """

    job_id: str
