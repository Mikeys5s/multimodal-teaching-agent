"""苏格拉底式答疑（归属：P2）· SPEC §5.3。

## 模块划分（一条清晰的边界）

| 文件 | 负责 | 不负责 |
|---|---|---|
| `state.py` | **这一轮该走哪个状态**（R2/R3/R4 硬规则） | 文案、查库 |
| `templates.py` | **说什么**（六个 turn_type × 多变体） | 判断、查库 |
| `retrieve.py` | **材料里有没有**（R1 检索 + F3.8 根因回溯） | 状态、文案 |
| `engine.py` | **把它们接起来 + 落库** | 三者各自的内部逻辑 |

**为什么要这么切**：SPEC §5.3 说状态机必须「**显式、可测，不是"尽量引导"**」。
"可测"的前提是**判断逻辑能单独被断言** —— 如果状态流转和文案生成混在一起，
就只能"读回复觉得像引导"，测不了。

## 一句话记住这个模块的设计

> **状态流转是硬规则（可断言），文案是软表达（靠人读）。**
> 混在一起写，就会变成"看起来在引导，其实规则没生效"。
"""

from __future__ import annotations

from app.tutor.engine import (
    SessionReport,
    SessionState,
    TurnResult,
    next_seq,
    report_of_session,
    run_turn,
    state_of_session,
)
from app.tutor.state import (
    STUCK_THRESHOLD,
    Decision,
    State,
    TurnType,
    Verdict,
    judge_answer,
    next_state,
)

__all__ = [
    "Decision",
    "STUCK_THRESHOLD",
    "SessionReport",
    "SessionState",
    "State",
    "TurnResult",
    "TurnType",
    "Verdict",
    "judge_answer",
    "next_seq",
    "next_state",
    "report_of_session",
    "run_turn",
    "state_of_session",
]
