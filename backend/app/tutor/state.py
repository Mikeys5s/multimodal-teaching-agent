"""苏格拉底式答疑状态机（归属：P2）· SPEC §5.3。

## 这个模块只做一件事：**决定这一轮该走哪个状态**

它**不生成文案**（那是 `templates.py` 的事）、**不查库**（那是 `retrieve.py` 的事）。
这样分开的理由：**状态流转是硬规则，文案是软表达** —— 前者的正确性可以用断言保证，
后者只能靠人读。混在一起写，就会变成"看起来在引导，其实规则没生效"。

## SPEC §5.3 的状态图（本模块是它的直译）

                       ┌──────────────────────────┐
                       │  S0 检索与越界判定         │
                       └────────────┬─────────────┘
                             越界 ───┴─── 命中
                              │              │
                      ┌───────▼──────┐  ┌────▼─────────────────┐
                      │ REFUSE       │  │ S1 PROBE  反问答疑    │
                      └──────────────┘  └────┬─────────────────┘
                                     学生答对 ─┴─ 答错/答不上
                                          │            │
                                  ┌───────▼──┐  ┌──────▼────────┐
                                  │ CONFIRM  │  │ S2 HINT1 提示  │
                                  └──────────┘  └──────┬────────┘
                                                        │ 仍答不上
                                                ┌───────▼────────┐
                                                │ S3 HINT2 强提示 │
                                                └───────┬────────┘
                                                        │ 第 2 次答不上
                                                ┌───────▼────────┐
                                                │ S4 EXPLAIN     │
                                                └────────────────┘

## 三条**代码层强制**的硬规则（对应 SPEC §5.3 R2 / R3）

| 规则 | 怎么保证 |
|---|---|
| **R2 首轮绝不给答案** | `S1_PROBE` 是**唯一**的入口状态；`EXPLAIN` 在 `hint_level < 2` 时**不可达** |
| **R3 连续 2 次答不上 → 强制 S4** | 计数器在**这个模块**里，不依赖模型或调用方自觉 |
| **R4 检索不到必须 REFUSE** | `refuse` 是「命中为空」的唯一出口，**没有"猜一个"的分支** |

**为什么强调"代码层"**：这三个规则如果交给模型判断，就变成了"尽量引导"。
SPEC 的原话是「**显式、可测，不是"尽量引导"**」—— 所以它们必须是**状态机的转移条件**，
而不是提示词里的一句话。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# 状态与轮次类型
# ---------------------------------------------------------------------------


class State(str, Enum):
    """SPEC §5.3 的六个状态。**值就是 api-spec 里 `state` 字段的字面量。**"""

    S0_RETRIEVE = "S0_RETRIEVE"   # 检索与越界判定（不产出回复，是每轮的入口）
    REFUSE = "REFUSE"             # 越界：材料里没有
    S1_PROBE = "S1_PROBE"         # 反问
    CONFIRM = "CONFIRM"           # 答对：确认 + 巩固
    S2_HINT1 = "S2_HINT1"         # 第一次答不上：给方向
    S3_HINT2 = "S3_HINT2"         # 第二次答不上：给原文片段
    S4_EXPLAIN = "S4_EXPLAIN"     # 连续两次答不上：直接完整讲解


class TurnType(str, Enum):
    """六种回复类型 —— 与 SPEC 模板表的键一一对应。"""

    PROBE = "probe"
    HINT1 = "hint1"
    HINT2 = "hint2"
    EXPLAIN = "explain"
    REFUSE = "refuse"
    CONFIRM = "confirm"


#: 状态 -> 回复类型。**一对一是刻意的** —— 让"状态"和"用户看到什么"永远对得上。
STATE_TO_TURN: dict[State, TurnType] = {
    State.S1_PROBE: TurnType.PROBE,
    State.S2_HINT1: TurnType.HINT1,
    State.S3_HINT2: TurnType.HINT2,
    State.S4_EXPLAIN: TurnType.EXPLAIN,
    State.REFUSE: TurnType.REFUSE,
    State.CONFIRM: TurnType.CONFIRM,
}

#: 进入 S4 所需的"连续答不上"次数（SPEC R3 写死 2，这里也把它写成常量，
#: 而不是散落在判断里 —— 要改口径只改这一处）
STUCK_THRESHOLD = 2

#: `diagnosis.stuck_at` 的取值 —— 三件事里的中间那件要有个受控词表。
STUCK_REASONS = (
    "首次作答前",           # 刚提问，还没答
    "答错概念本身",         # 命中的知识点没理解
    "忽略前置知识",         # 卡点在硬前置上（根因回溯的对象）
    "答对",                 # 正常收敛
)


@dataclass
class Decision:
    """状态机对"这一轮"的判定结果。

    这是**纯数据**，不含任何文案 —— 所以它可以被断言、被记录、被回放。
    """

    state: State
    turn_type: TurnType
    #: 已经连续答不上几次（0 = 首次提问）
    stuck_count: int
    #: 这一轮该用哪个知识点的数据组装回复（REFUSE 时是最接近的那个，可为空）
    kp_id: str | None
    #: 卡点判定的**依据**（SPEC R6：必须给出依据，不能只说"你卡了"）
    stuck_at: str
    #: 依据的自然语言说明（例：引用了哪个误区 / 哪个前置没掌握）
    evidence: str = ""
    #: 根因回溯的结果（SPEC F3.8）—— 断层的前置知识点
    root_cause_kp_id: str | None = None
    notes: list[str] = field(default_factory=list[str])

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "turn_type": self.turn_type.value,
            "stuck_count": self.stuck_count,
            "kp_id": self.kp_id,
            "stuck_at": self.stuck_at,
            "evidence": self.evidence,
            "root_cause_kp_id": self.root_cause_kp_id,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# 判定「学生的这一句算答对还是答不上」
# ---------------------------------------------------------------------------


#: 视为"承认答不上"的信号词。命中即立刻进入下一级提示，**不需要模型判断**。
GIVE_UP_MARKERS = (
    "不知道", "不清楚", "不会", "不懂", "没学", "忘了", "不记得", "想不出",
    "不明白", "不理解", "没思路", "说不出来", "答不上", "过", "跳过",
    "idk", "dunno", "no idea", "skip",
)

#: 视为"给出了一段作答"的最小长度（太短的多半是"嗯""是的"这类）
MIN_ANSWER_LEN = 4


class Verdict(str, Enum):
    """把学生的话归成三类 —— 这是 R3 计数器唯一会读的东西。"""

    CORRECT = "correct"        # 答对了 → CONFIRM
    WRONG = "wrong"            # 答了但不对 / 答不上 → 往下降
    TOO_SHORT = "too_short"    # 太短，不足以判断 → **不推进状态机**，再问一次


def judge_answer(
    text: str,
    *,
    kp_name: str | None = None,
    kp_summary: str | None = None,
    kp_quote: str | None = None,
) -> tuple[Verdict, str]:
    """判断学生这一句是「答对」还是「答不上」。返回 (判定, 依据)。

    ## 为什么不用模型判

    这条判定**直接决定 R3 的计数器** —— 如果它不稳定，"连续 2 次答不上"
    就会时灵时不灵，那条硬规则等于没有。所以这里用**确定性的信号**：

    - **命中 `GIVE_UP_MARKERS`** → 明确答不上（学生自己说了）
    - **太短**（< `MIN_ANSWER_LEN`）→ 不足以判断，**不推进**（避免"嗯"把计数推满）
    - **与知识点文本有实质重叠**（≥ 2 个 2-gram 命中）→ 判答对
    - 其余 → 判答错

    **诚实说明这个判据的边界**：它是**字面重叠**，不理解同义表达。
    学生会用"数据包丢失时窗口减半"回答"拥塞窗口怎么变"—— 字面重叠可能不足。
    **所以判错只往下降一级（还有 hint1/hint2 两次机会），并且把判据写进返回的
    依据里** —— 让学生和评审都能看到"系统为什么觉得你答得不对"。
    """
    t = (text or "").strip()

    # ⚠️ **先判信号词，再判长度。顺序不能反。**
    #
    # 我第一版把长度判断放在前面，于是 ——
    # **「不知道」只有 3 个字 < MIN_ANSWER_LEN(4) → 被判成 TOO_SHORT → 不推进计数。**
    #
    # 后果不是"少判一次答错"，是**击穿 R3**：
    # 学生连说两次「不知道」（最标准的"答不上"表达），系统**不会降级讲解**，
    # 而会一直停在"太短不足以判断，再问一次"。
    #
    # **判据的优先级要按"证据强度"排，不是按"代码顺手"排。**
    # 「不知道」是学生**明确说出来的**信号（证据强），
    # 长度只是"信息量可能不足"的弱启发式（证据弱）—— 强的先判。
    low = t.lower()
    for marker in GIVE_UP_MARKERS:
        if marker in low:
            return Verdict.WRONG, f"学生明确表示答不上（命中「{marker}」）"

    if len(t) < MIN_ANSWER_LEN:
        return Verdict.TOO_SHORT, f"回答只有 {len(t)} 个字，不足以判断"

    # 与知识点文本做 2-gram 重叠
    ref = " ".join(x for x in (kp_name or "", kp_summary or "", kp_quote or "") if x)
    if ref:
        ref_grams = {ref[i : i + 2] for i in range(len(ref) - 1)}
        hit = {t[i : i + 2] for i in range(len(t) - 1)} & ref_grams
        if len(hit) >= 2:
            return Verdict.CORRECT, f"与知识点文本有 {len(hit)} 处实质重叠（例：{'、'.join(sorted(hit)[:3])}）"

    return Verdict.WRONG, "作答内容与知识点材料没有可识别的重叠"


# ---------------------------------------------------------------------------
# 状态机本体
# ---------------------------------------------------------------------------


def next_state(
    *,
    is_first_turn: bool,
    stuck_count: int,
    verdict: Verdict | None,
    has_hit: bool,
) -> tuple[State, int, list[str]]:
    """算出这轮该进哪个状态。返回 (状态, 新的 stuck_count, 说明)。

    参数
    ----
    - `is_first_turn`：这个会话的**第一轮提问**（还没有任何导师轮）
    - `stuck_count`：**已经**连续答不上几次（0 = 还没答过）
    - `verdict`：学生对上一轮反问的判定（`None` = 这是全新提问，没有上一轮）
    - `has_hit`：检索是否命中（SPEC R1：**必须先检索**）

    ## R2 是怎么被强制的

    `is_first_turn=True` 时**直接返回 S1_PROBE**，不看 `stuck_count`、不看 `verdict`。
    **这是唯一能让"首轮不给答案"永远成立的写法** ——
    如果把它写成"如果 stuck_count < 2 就 PROBE"，那就可能出现
    "第一轮就 stuck_count=2"（比如状态被错误地持久化）而直接跳到讲解。
    """
    notes: list[str] = []

    # R4：检索不到 → REFUSE。**放在最前面** ——
    # 越界判定先于一切，否则会拿不到 kp 的数据去组装回复。
    if not has_hit:
        notes.append("检索未命中 → REFUSE（R4：不得包含材料外的知识断言）")
        return State.REFUSE, stuck_count, notes

    # R2：首轮绝不给答案。**硬性短路**，不参与后面的计数逻辑。
    if is_first_turn:
        notes.append("首轮 → S1 PROBE（R2：绝不给答案，只给反问）")
        return State.S1_PROBE, 0, notes

    # 从这一轮开始才看上一轮的判定
    if verdict == Verdict.CORRECT:
        notes.append("学生答对 → CONFIRM（确认 + 变式练习）")
        return State.CONFIRM, 0, notes  # 答对即清零

    if verdict == Verdict.TOO_SHORT:
        # ⚠️ **不推进状态机** —— 太短不足以判断，原地再问一次。
        # 这是为了不让"嗯""哦"把 R3 的计数推满。
        notes.append("回答过短，不足以判断 → 停在 S1 PROBE 再问一次（不推进计数）")
        return State.S1_PROBE, stuck_count, notes

    # 答错 / 答不上 → 计数 +1，按 SPEC 的 R3 决定降级到哪一级
    stuck = stuck_count + 1
    notes.append(f"答错/答不上 → 连续第 {stuck} 次")

    if stuck >= STUCK_THRESHOLD:
        # ★ R3：**代码层强制降级**，不再追问。
        notes.append(
            f"连续 {stuck} 次达阈值 {STUCK_THRESHOLD} → **强制 S4 EXPLAIN**"
            "（R3：不得继续追问）"
        )
        return State.S4_EXPLAIN, stuck, notes

    notes.append("第 1 次答不上 → S2 HINT1（给方向，不给答案）")
    return State.S2_HINT1, stuck, notes


def hint_level_of(state: State) -> int:
    """这个状态对应的"提示层级"（写进 SSE 的 `state` 事件）。

    `probe` = 0（不给提示，只反问）、`hint1` = 1、`hint2` = 2、`explain` = 3。
    前端用它来决定"要不要显示「连续两次没答上，我直接讲」的提示"（SPEC F3.5）。
    """
    return {
        State.S1_PROBE: 0,
        State.CONFIRM: 0,
        State.REFUSE: 0,
        State.S2_HINT1: 1,
        State.S3_HINT2: 2,
        State.S4_EXPLAIN: 3,
    }.get(state, 0)


def should_show_downgrade_notice(state: State) -> bool:
    """SPEC F3.5：进入 S4 时 UI 要**明确提示**「连续两次没答上，我直接讲」。

    为什么值得单独写一个函数：这条要求的重点不是"降级"，而是
    **「让学生感知到系统的规则，而不是觉得被放弃」**。
    把它做成一个显式判断，前端就不可能忘。
    """
    return state == State.S4_EXPLAIN
