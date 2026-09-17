"""答疑与诊断的契约（归属：P2 定义；路由实现在 `api/qa.py`，归 P3）。

对应 docs/api-spec.md §5（端点 20–25）。

★ 这里的两个模型是**苏格拉底状态机的对外窗口**：
  · `QaStateOut` 把"看不见的引导策略"暴露成接口，让评委能看见它的存在；
  · `SseStateEvent` 让前端能在降级讲解或拒答时给出对应提示。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 5.1 会话
# ---------------------------------------------------------------------------


class SessionCreateIn(BaseModel):
    """`POST /api/qa/sessions` 的请求体。"""

    material_scope: list[str] = Field(
        default_factory=list, description="答疑范围（material_id 列表）；空数组 = 全部材料"
    )
    student_label: str | None = Field(default=None, description="演示用标签，不做登录")


class SessionCreatedOut(BaseModel):
    session_id: str


class DiagnosisKpOut(BaseModel):
    """本轮涉及的知识点。"""

    kp_id: str
    name: str
    difficulty: int


class StuckAtOut(BaseModel):
    """「学生卡在哪一步」—— 三件产出之一。"""

    step: str = Field(description="卡点的中文描述，如「尚未建立分区与最终位置的关系」")
    evidence_kp_id: str | None = None
    evidence_misconception_id: str | None = Field(
        default=None, description="若命中了已知误区，给出它的 id"
    )


class NextPracticeOut(BaseModel):
    """「下一步建议练习什么」—— 三件产出之一。"""

    kp_id: str
    task: str = Field(description="具体可执行的练习建议，不是空泛的「多复习」")


class DiagnosisOut(BaseModel):
    """每轮答疑必须输出的三件事：涉及的知识点 / 卡在哪一步 / 下一步练什么。"""

    knowledge_points: list[DiagnosisKpOut] = Field(default_factory=list)
    stuck_at: StuckAtOut | None = None
    next_practice: list[NextPracticeOut] = Field(default_factory=list)


class TurnOut(BaseModel):
    """一轮对话。`grounded` 是"是否基于材料"的标记。"""

    id: str
    seq: int
    role: str = Field(description="student / tutor")
    content_md: str
    turn_type: str | None = Field(
        default=None,
        description="probe / hint1 / hint2 / explain / confirm / refuse / "
        "student_answer / student_question",
    )
    retrieved_kp_ids: list[str] = Field(default_factory=list, description="本轮检索依据")
    retrieved_block_ids: list[str] = Field(default_factory=list, description="溯源到具体解析块")
    grounded: bool = Field(description="是否基于材料作答。**拒答轮次为 false**")
    diagnosis: DiagnosisOut | None = None
    latency_ms: int | None = None
    created_at: str


class SessionDetailOut(BaseModel):
    """会话详情 + 全部轮次（`GET /api/qa/sessions/{id}`）。"""

    id: str
    student_label: str | None = None
    material_scope: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    turns: list[TurnOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5.3 状态机查询
# ---------------------------------------------------------------------------


class QaStateOut(BaseModel):
    """`GET /api/qa/sessions/{id}/state`。

    **为什么要有这个接口**：苏格拉底状态机是核心差异化，但它是"看不见的逻辑"。
    暴露成接口 + 前端可视化（如三轮进度指示器），就能让评委**看见引导策略的存在**。
    """

    state: str = Field(description="状态机当前状态，如 S1_PROBE / S2_HINT1")
    hint_level: int = Field(description="已给出的提示级数")
    consecutive_failures: int = Field(description="连续答不上来的次数")
    current_kp_id: str | None = None
    next_action: str = Field(description="下一步动作：hint1 / hint2 / explain / …")
    explain_threshold: int = Field(
        default=2, description="连续失败达到这个次数就强制降级为直接讲解（由代码层强制）"
    )


# ---------------------------------------------------------------------------
# 5.1 会话诊断报告
# ---------------------------------------------------------------------------


class SessionReportOut(BaseModel):
    """`GET /api/qa/sessions/{id}/report` —— 汇总本会话全部卡点与建议练习。"""

    session_id: str
    turn_count: int
    grounded_rate: float = Field(description="接地率 = grounded 轮次 / 总轮次")
    stuck_points: list[StuckAtOut] = Field(default_factory=list)
    suggested_practices: list[NextPracticeOut] = Field(default_factory=list)
    summary_md: str = Field(description="给用户看的中文总结")


# ---------------------------------------------------------------------------
# 5.2 SSE 事件载荷
# ---------------------------------------------------------------------------


class AskIn(BaseModel):
    """`POST /api/qa/sessions/{id}/ask` 的请求体。"""

    question: str = Field(min_length=1, description="学生的问题")


class SseRetrievedEvent(BaseModel):
    """`event: retrieved` —— **必须先于任何 delta 发出**。

    前端据此先渲染溯源卡片，让"先检索再回答"这件事**在界面上可见**。
    """

    seq: int
    kp_ids: list[str] = Field(default_factory=list)
    block_ids: list[str] = Field(default_factory=list)
    is_out_of_scope: bool = Field(
        default=False, description="越界时为 true，此时后续 delta 必须是拒答模板"
    )


class SseStateEvent(BaseModel):
    """`event: state` —— 状态机对外可见的状态变化。"""

    seq: int
    turn_type: str = Field(description="probe / hint1 / hint2 / explain / confirm / refuse")
    state: str
    hint_level: int = 0


class SseDeltaEvent(BaseModel):
    """`event: delta` —— 增量文本。"""

    seq: int
    text: str


class SseUsageOut(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class SseDoneEvent(BaseModel):
    """`event: done` —— 本轮结束。"""

    seq: int
    turn_id: str
    latency_ms: int | None = None
    usage: SseUsageOut | None = None


class SseDiagnosisEvent(BaseModel):
    """`event: diagnosis` —— 三件产出。"""

    seq: int
    knowledge_points: list[DiagnosisKpOut] = Field(default_factory=list)
    stuck_at: StuckAtOut | None = None
    next_practice: list[NextPracticeOut] = Field(default_factory=list)
