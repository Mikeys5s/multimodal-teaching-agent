"""`engine` 的读侧测试（归属：P2）—— 需要真库，所以单开一个文件。

## 为什么这个文件必须存在

`test_tutor_state.py` 测的是 `state.py` 的**纯函数**（不需要库）。
但 `_stuck_count` / `state_of_session` / `report_of_session` 都**要读 `qa_turns`** ——
它们住在 `engine.py` 里，**于是从没被单元测试覆盖过。**

**代价是真实的**（2026-09-21）：

    STUCK_THRESHOLD = 2，所以第 2 次答不上是直接跳 explain（不是 hint2）
    而 _stuck_count 只数 hint1/hint2  →  stuck 停在 1，应该是 2

**24 个测试全绿，问题留到全链路端到端才暴露。**

## ⭐ 这个文件要守住的一条纪律

**修一个"不该怎样"的 bug 时，同时写下"那它该怎样"的断言。**

我第一版修法是"`explain` 不清零" —— 那只是**消除错误行为**。
测试如果只写"不该是 0"，它就会通过，而数字停在该走到的地方之前（1 而不是 2）。

**所以我在这里显式断言"它该等于 2"，而不只是"它不该等于 0"。**
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import QaSession, QaTurn
from app.tutor import engine as E
from app.tutor.state import STUCK_THRESHOLD, State


# ---------------------------------------------------------------------------
# 造轮次的小工具（不碰真实数据 —— 用 conftest 的临时库）
# ---------------------------------------------------------------------------


def _session(db: Session, sid: str = "qs_test_001") -> str:
    db.add(QaSession(
        id=sid, student_label="test", material_scope="all",
        created_at="2026-09-21T00:00:00+00:00", updated_at="2026-09-21T00:00:00+00:00",
    ))
    db.commit()
    return sid


def _turn(db: Session, sid: str, seq: int, role: str, turn_type: str | None,
          kp_ids: str | None = None, diagnosis: str | None = None) -> None:
    db.add(QaTurn(
        id=f"qt_{sid}_{seq}", session_id=sid, seq=seq, role=role,
        content_md=f"（{role} 第 {seq} 轮）", turn_type=turn_type,
        retrieved_kp_ids=kp_ids, retrieved_block_ids=None,
        grounded=0 if turn_type == "refuse" else 1, diagnosis_json=diagnosis,
        created_at="2026-09-21T00:00:00+00:00",
    ))
    db.commit()


def _converse(db: Session, sid: str, tutor_types: list[str]) -> None:
    """按给定的导师轮类型序列造一轮对话（学生轮自动补）。"""
    seq = 1
    for t in tutor_types:
        _turn(db, sid, seq, "student", None)
        _turn(db, sid, seq + 1, "tutor", t)
        seq += 2


# ---------------------------------------------------------------------------
# ★ 核心：explain 要计入计数（这次的 bug）
# ---------------------------------------------------------------------------


def test_explain_counts_toward_stuck(session: Session) -> None:
    """★ `explain` **必须 +1**，不能只是"不清零"。

    这是 2026-09-21 全链路实测暴露的 bug：

        hint1  → stuck = 1   ✅
        explain → stuck = 1   ❌ 应该是 2

    **断言的是"该等于 2"，不是"不该等于 0"** ——
    后者会让"停在 1"的错误实现也通过。
    """
    sid = _session(session)
    _converse(session, sid, ["probe", "hint1", "explain"])

    assert E._stuck_count(session, sid) == 2, (
        "hint1 + explain 应当计 2 次失败 —— "
        "只断言「不为 0」是不够的（那样「停在 1」也会通过）"
    )


def test_two_hints_also_count_two(session: Session) -> None:
    """`hint1` + `hint2` 这条路径也要到 2（如果阈值改成 3 就会走它）。"""
    sid = _session(session)
    _converse(session, sid, ["probe", "hint1", "hint2"])
    assert E._stuck_count(session, sid) == 2


def test_confirm_resets_to_zero(session: Session) -> None:
    """**只有"答对"才清零。**"""
    sid = _session(session)
    _converse(session, sid, ["probe", "hint1", "explain", "confirm"])
    assert E._stuck_count(session, sid) == 0, "confirm（答对）必须把计数清零"


def test_probe_does_not_count(session: Session) -> None:
    """**首轮反问不是"失败"** —— 它不该被计入。

    计进去的话，学生还没答过任何一次，`consecutive_failures` 就已经是 1 了。
    """
    sid = _session(session)
    _converse(session, sid, ["probe"])
    assert E._stuck_count(session, sid) == 0


def test_refuse_does_not_count(session: Session) -> None:
    """越界拒答不是"学生答不上" —— 不该计入（那是材料的问题，不是学生的）。"""
    sid = _session(session)
    _converse(session, sid, ["probe", "refuse"])
    assert E._stuck_count(session, sid) == 0


def test_confirm_clears_a_long_run(session: Session) -> None:
    """连续多次失败后答对 → 清零；再失败 → 从 1 重新开始。"""
    sid = _session(session)
    _converse(session, sid, ["probe", "hint1", "explain", "confirm", "hint1"])
    assert E._stuck_count(session, sid) == 1, "confirm 之后的失败应当从 1 重新开始"


def test_stuck_count_never_exceeds_threshold_without_reset(session: Session) -> None:
    """连续失败时，计数应当**单调涨到阈值后继续涨**（而不是卡住）。

    ⚠️ 这条是"阈值 = 2"时的真实行为：第 2 次直接跳 explain，
    所以最多看到 hint1 + explain×N。**计数要如实反映"N 次失败"。**
    """
    sid = _session(session)
    _converse(session, sid, ["probe", "hint1", "explain", "explain"])
    assert E._stuck_count(session, sid) == 3, "3 次失败就该是 3，不该卡在 2"


# ---------------------------------------------------------------------------
# state_of_session：反推状态要与写侧对称
# ---------------------------------------------------------------------------


def test_state_of_empty_session_is_probe(session: Session) -> None:
    """**0 轮的会话必须是 `S1_PROBE` / 计数 0。**

    这条挡的是"写死的状态" —— `get_state` 曾经返回 `S2_HINT1 / hint_level=1`，
    **一个刚建的会话会说"已经提示了 1 次"。**
    """
    sid = _session(session)
    st = E.state_of_session(session, sid)
    assert st.state == State.S1_PROBE
    assert st.hint_level == 0
    assert st.consecutive_failures == 0
    assert st.current_kp_id is None
    assert st.has_tutor_turn is False
    assert st.turn_count == 0


def test_state_after_explain_reports_two_failures(session: Session) -> None:
    """进到 `explain` 之后，`consecutive_failures` 必须是 2（与 `_stuck_count` 同源）。"""
    sid = _session(session)
    _converse(session, sid, ["probe", "hint1", "explain"])
    st = E.state_of_session(session, sid)
    assert st.state == State.S4_EXPLAIN
    assert st.consecutive_failures == 2
    assert st.hint_level == 3, "explain 的提示层级是最高一级"
    assert st.explain_threshold == STUCK_THRESHOLD


def test_state_carries_last_kp_id(session: Session) -> None:
    """状态里要带上**最后一条导师轮讲的那个知识点** —— 前端据此显示"正在讲什么"。"""
    sid = _session(session)
    _turn(session, sid, 1, "student", None)
    _turn(session, sid, 2, "tutor", "probe", kp_ids='["kp_aaa", "kp_bbb"]')
    st = E.state_of_session(session, sid)
    assert st.current_kp_id == "kp_aaa", "取检索命中的第一个"


def test_state_survives_broken_kp_ids(session: Session) -> None:
    """`retrieved_kp_ids` 是脏数据时不能抛异常（它是落库的 JSON 字符串）。"""
    sid = _session(session)
    _turn(session, sid, 1, "student", None)
    _turn(session, sid, 2, "tutor", "probe", kp_ids="{不是合法 JSON")
    st = E.state_of_session(session, sid)
    assert st.current_kp_id is None, "坏 JSON 应当降级成 None，而不是把接口打成 500"


# ---------------------------------------------------------------------------
# report_of_session：接地率的分母
# ---------------------------------------------------------------------------


def test_grounded_rate_denominator_is_tutor_turns(session: Session) -> None:
    """★ 接地率的分母是**导师轮**，不是全部轮。

    SPEC 原话：「幻觉率的分母只用导师轮」。
    用全部轮次算会把分母撑大一倍、把比率算好看一倍。
    """
    sid = _session(session)
    _converse(session, sid, ["probe", "confirm"])   # 2 导师轮，都 grounded=1
    rep = E.report_of_session(session, sid)
    assert rep.turn_count == 4, "2 学生 + 2 导师"
    assert rep.grounded_rate == 1.0, "分母应当是 2（导师轮），不是 4（全部轮）"


def test_refuse_lowers_grounded_rate(session: Session) -> None:
    """**拒答轮按 0 计入** —— 它要如实把接地率拉下来。

    这是「幻觉率必须为 0」那条红线的载体：
    **一个恒定 100% 的比率，等于没有这个指标。**
    """
    sid = _session(session)
    _converse(session, sid, ["probe", "probe", "refuse"])   # 3 导师轮，1 条 refuse
    rep = E.report_of_session(session, sid)
    assert rep.grounded_rate < 1.0, "有拒答轮时接地率必须被拉下来"
    # ⚠️ **容差用 1e-3，不用 1e-6。**
    #
    # `report_of_session` 返回的是 `round(rate, 4)` —— 0.6667 而不是 0.66666…
    # 我第一版写 `abs(rate - 2/3) < 1e-6`，**那是要求实现具备它没有的精度**：
    #
    #     AssertionError: 应当是 2/3，实际 0.6667（差 3.33e-05）
    #
    # **测试要断言「行为」，不要断言「浮点精度」。**
    # 但也不能松到看不出问题 —— 1e-3 足以区分 2/3 与 1.0、3/4 这些真实差异。
    assert abs(rep.grounded_rate - 2 / 3) < 1e-3, f"应当是 2/3，实际 {rep.grounded_rate}"
    assert "拒答" in rep.summary_md, "总结里要说清「为什么不是 100%」"


def test_empty_session_report_is_honest(session: Session) -> None:
    """**空会话的报告要说"还没有答疑记录"，不能编一段漂亮话。**

    原来它返回写死的「本次答疑共 8 轮，接地率 100%」——
    **一个刚建的会话也会这么说。**
    """
    sid = _session(session)
    rep = E.report_of_session(session, sid)
    assert rep.turn_count == 0
    assert rep.grounded_rate == 0.0
    assert rep.stuck_points == []
    assert "还没有" in rep.summary_md
    assert "快排" not in rep.summary_md, "绝不能出现写死的示例内容"
