"""图谱、学习路径、卡点回溯的契约（归属：P2）。对应 docs/api-spec.md §4.4（端点 16、17、28）。

★ 本文件承载**创新点的对外呈现**：
  · `stats.cycle_count` 必须能被前端展示为 0 —— 把「DAG 无环」这个工程指标变成评委可见的信任信号；
  · `pruned_count` / `conflict_count` 让"检出了 N 条成环边并已剪除"可展示 ——
    这比只写"环数 0"更有说服力，因为它证明系统真的在检查，而不只是恰好没出错。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 4.4 知识图谱（GET /api/knowledge-graph）
# ---------------------------------------------------------------------------


class GraphNodeOut(BaseModel):
    """图节点。`difficulty` 供前端做颜色映射，`needs_review` 供高亮。"""

    id: str
    name: str
    difficulty: int
    chapter_id: str | None = None
    section_id: str | None = None
    needs_review: bool = False


class GraphEdgeOut(BaseModel):
    """图边。注意方向语义：`source` 是**前置**，`target` 是**后置**。

    即「要学会 target，得先会 source」。前端画箭头时不要搞反。
    """

    source: str = Field(description="前置知识点 id")
    target: str = Field(description="后置知识点 id")
    relation_type: str = Field(description="hard / soft")


class GraphStatsOut(BaseModel):
    """图谱统计。**这几个数字是给评委看的工程指标**，不是内部调试信息。"""

    node_count: int = 0
    edge_count: int = 0
    cycle_count: int = Field(default=0, description="★ 必须为 0 —— 依赖图无环是工程不变量")
    pruned_count: int = Field(
        default=0, description="★ 因成环被剪除的边数。展示它比只报「环数 0」更有说服力"
    )
    conflict_count: int = Field(
        default=0, description="★ 结构-语义冲突边数（needs_review=1），冲突不静默采纳"
    )
    hard_edge_count: int = 0
    soft_edge_count: int = 0


class GraphOut(BaseModel):
    material_id: str | None = None
    nodes: list[GraphNodeOut] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)
    stats: GraphStatsOut = Field(default_factory=GraphStatsOut)


# ---------------------------------------------------------------------------
# 4.4 学习路径（GET /api/learning-path）
# ---------------------------------------------------------------------------


class LearningPathStepOut(BaseModel):
    """路径中的一步。`reason` **必须来自依赖边上的 reason**（P10 产出）。

    这样"为什么这个排在前面"是可解释的，而不是黑盒拓扑排序的结果。
    """

    order: int = Field(description="从 1 开始的序号")
    kp_id: str
    name: str
    difficulty: int
    reason: str | None = Field(
        default=None, description="排在这一步的理由，源自前置边的 reason；起点为 null"
    )
    is_start_point: bool = Field(default=False, description="没有硬前置 = 起点")


class LearningPathOut(BaseModel):
    target_kp_id: str
    steps: list[LearningPathStepOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 4.4 卡点根因回溯（GET /api/knowledge-points/{id}/gap-analysis）
# ---------------------------------------------------------------------------


class KpBriefOut(BaseModel):
    kp_id: str
    name: str


class HardPrereqOut(BaseModel):
    """硬前置。"depth" 表示离目标知识点几步可达（1 = 直接前置）。"""

    kp_id: str
    name: str
    depth: int
    reason: str | None = None


class GapSourceOut(BaseModel):
    """断层的溯源位置 —— 让"建议你回第 88 页"这句话有据可依。"""

    material_id: str | None = None
    page: int | None = None


class LikelyGapOut(BaseModel):
    """最可能的断层。`evidence` 是**说人话的判据**，不是内部分数。"""

    kp_id: str
    name: str
    evidence: str = Field(
        description="为什么判断卡在这里，如「本轮命中误区『把拥塞窗口与接收窗口混为一谈』」"
    )
    source: GapSourceOut | None = None


class GapAnalysisOut(BaseModel):
    """卡点根因回溯。

    三件产出里的「学生卡在哪一步」由它承载：不是简单说"你这题错了"，
    而是沿 hard 边反向回溯，指出**更可能的根因**。
    """

    target_kp: KpBriefOut
    hard_prerequisites: list[HardPrereqOut] = Field(default_factory=list)
    likely_gap: LikelyGapOut | None = Field(
        default=None, description="找不到明显断层时为 null，前端应降级展示"
    )
    suggestion: str = Field(description="给学生的下一步建议，中文，可含页码指引")
