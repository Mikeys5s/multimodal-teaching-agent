"""苏格拉底状态机的硬规则测试（归属：P2）。

## 这份测试只测**判断**，不测文案

因为 SPEC §5.3 要求的可测部分是「**状态流转**」：
- **R2 首轮绝不给答案**
- **R3 连续 2 次答不上 → 强制 S4**
- **R4 检索不到 → REFUSE**

文案好不好读是另一回事（靠人读），**但规则必须能被断言**。
所以这里一个字符都不比对回复内容，只断言 `State` / `TurnType` / 计数。

## 一条特别要测的边界

`test_too_short_answer_does_not_advance` —— 「嗯」「哦」这类回答
**不能推进 R3 的计数**。这一条如果错了，学生只要连发两个"嗯"
就会被强制讲解 —— **那是最容易被评委发现的那种伪实现**。
"""

from __future__ import annotations

import pytest

from app.tutor.state import (
    STATE_TO_TURN,
    STUCK_THRESHOLD,
    State,
    TurnType,
    Verdict,
    judge_answer,
    next_state,
)


# ---------------------------------------------------------------------------
# R2：首轮绝不给答案
# ---------------------------------------------------------------------------


def test_first_turn_never_explains() -> None:
    """★ R2：首轮**永远**是 S1 PROBE —— 哪怕计数器被污染成 2。"""
    for stuck in (0, 1, 2, 5):
        state, _, notes = next_state(
            is_first_turn=True, stuck_count=stuck, verdict=None, has_hit=True
        )
        assert state == State.S1_PROBE, f"stuck_count={stuck} 时首轮跑偏了"
        assert state.value != "S4_EXPLAIN", "首轮绝不能直接讲解（R2）"
    assert any("R2" in n for n in notes)


def test_first_turn_resets_counter() -> None:
    """首轮把计数归零 —— 避免上一次会话的残留影响这次（R3 的"连续"语义）。"""
    _, stuck, _ = next_state(
        is_first_turn=True, stuck_count=3, verdict=None, has_hit=True
    )
    assert stuck == 0


# ---------------------------------------------------------------------------
# R3：连续 2 次答不上 → 强制 S4
# ---------------------------------------------------------------------------


def test_wrong_once_goes_to_hint1() -> None:
    state, stuck, _ = next_state(
        is_first_turn=False, stuck_count=0, verdict=Verdict.WRONG, has_hit=True
    )
    assert state == State.S2_HINT1
    assert stuck == 1


def test_wrong_twice_forces_explain() -> None:
    """★ R3：第 2 次答不上 → **强制 S4**，不得继续追问。"""
    state, stuck, notes = next_state(
        is_first_turn=False, stuck_count=1, verdict=Verdict.WRONG, has_hit=True
    )
    assert state == State.S4_EXPLAIN, "连续 2 次答不上必须强制讲解（R3）"
    assert stuck == STUCK_THRESHOLD
    assert any("强制" in n for n in notes)


def test_correct_resets_counter() -> None:
    state, stuck, _ = next_state(
        is_first_turn=False, stuck_count=5, verdict=Verdict.CORRECT, has_hit=True
    )
    assert state == State.CONFIRM
    assert stuck == 0, "答对必须清零 —— 否则 R3 的「连续」就不成立"


def test_too_short_answer_does_not_advance() -> None:
    """★ 「嗯」「哦」这类回答**不推进计数**。

    这一条如果错了：学生连发两个"嗯"就被强制讲解 —— **最低级也最容易被抓的伪实现**。
    """
    state, stuck, notes = next_state(
        is_first_turn=False, stuck_count=1, verdict=Verdict.TOO_SHORT, has_hit=True
    )
    assert state == State.S1_PROBE, "太短不足以判断 → 原地再问，不该降级"
    assert stuck == 1, "计数不能推进"
    assert any("过短" in n for n in notes)


# ---------------------------------------------------------------------------
# R4：检索不到 → REFUSE
# ---------------------------------------------------------------------------


def test_no_hit_is_always_refuse() -> None:
    """★ R4：**不管其他条件如何**，没命中就是 REFUSE。

    这是越界判定的"短路"语义 —— 排在 R2 之前。
    """
    for first in (True, False):
        for stuck in (0, 2):
            state, _, notes = next_state(
                is_first_turn=first, stuck_count=stuck,
                verdict=Verdict.WRONG, has_hit=False,
            )
            assert state == State.REFUSE
            assert any("R4" in n for n in notes)


# ---------------------------------------------------------------------------
# 状态 ↔ 回复类型 的映射
# ---------------------------------------------------------------------------


def test_every_state_has_a_turn_type() -> None:
    """每个状态都要能映射出一个 turn_type —— 否则 SSE 的 `state` 事件会缺字段。"""
    for st in State:
        if st == State.S0_RETRIEVE:
            continue      # S0 是入口，不产回复
        assert STATE_TO_TURN[st] in TurnType


def test_hint_levels_are_ordered() -> None:
    """提示层级必须单调递增 —— 前端靠它决定显示什么（F3.5）。"""
    from app.tutor.state import hint_level_of

    assert hint_level_of(State.S1_PROBE) == 0
    assert hint_level_of(State.S2_HINT1) == 1
    assert hint_level_of(State.S3_HINT2) == 2
    assert hint_level_of(State.S4_EXPLAIN) > hint_level_of(State.S3_HINT2)


def test_downgrade_notice_only_on_explain() -> None:
    """SPEC F3.5：只有进 S4 时才提示「连续两次没答上，我直接讲」。"""
    from app.tutor.state import should_show_downgrade_notice

    for st in State:
        expect = st == State.S4_EXPLAIN
        assert should_show_downgrade_notice(st) is expect


# ---------------------------------------------------------------------------
# 作答判定
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["不知道", "不会", "不清楚", "我想不出来", "没学过", "skip", "no idea"],
)
def test_give_up_markers_are_recognized(text: str) -> None:
    v, _ = judge_answer(text)
    assert v == Verdict.WRONG, f"「{text}」应判答不上"


@pytest.mark.parametrize("text", ["嗯", "哦", "是的", "?"])
def test_short_answers_are_not_judged(text: str) -> None:
    v, why = judge_answer(text)
    assert v == Verdict.TOO_SHORT, f"「{text}」太短，不该判对错（否则计数会被推满）"
    assert "不足以判断" in why


def test_answer_overlapping_material_is_correct() -> None:
    """与材料有实质重叠 → 判答对。"""
    v, why = judge_answer(
        "拥塞窗口会随着确认而增长",
        kp_name="拥塞窗口",
        kp_summary="拥塞窗口是发送方维护的一个状态量，会随确认而增长",
    )
    assert v == Verdict.CORRECT, why


def test_unrelated_answer_is_wrong() -> None:
    v, _ = judge_answer(
        "这跟天气有关系吧",
        kp_name="拥塞窗口",
        kp_summary="拥塞窗口是发送方维护的状态量",
    )
    assert v == Verdict.WRONG


def test_judge_always_gives_evidence() -> None:
    """SPEC R6：卡点判定**必须给出依据** —— 不能只返回一个枚举值。"""
    for text in ("不知道", "嗯", "拥塞窗口会增长", "天气不错"):
        _, why = judge_answer(text, kp_name="拥塞窗口", kp_summary="拥塞窗口会增长")
        assert why, f"「{text}」的判定没有给出依据（R6）"
