"""答疑编排引擎（归属：P2）—— 把「检索 → 状态机 → 模板」接起来。

## 这一层只做编排水管，不做判断

判断都在下面两个模块里，各有各的测试：

- `state.py`：**该走哪个状态**（R2/R3/R4 的硬规则）
- `retrieve.py`：**材料里有没有**（R1 先检索 + F3.8 根因回溯）

本模块负责**按顺序调用它们**、**组装三件产出**（R5）、**落库**。

## SPEC §5.3 每轮必须输出三件事（R5）

| 三件事 | 从哪来 |
|---|---|
| **涉及的知识点** | `retrieve.search_kps` 的命中 |
| **学生卡在哪一步** | `state.judge_answer` 的判定 + `Decision.stuck_at` |
| **下一步建议练习** | 按当前状态决定（hint1 时建议复习摘要，explain 时建议做变式） |

**这三件不是"附加信息"，是 SPEC 的硬性规则** —— 所以它们进 `diagnosis` 字段、
进 SSE、也进 `qa_turns` 落库，缺一件就是没实现。

## 一个刻意的顺序：**先检索，再决定状态**

看起来"先判越界再检索"更省事，但 SPEC R1 是「**每次提问必须先检索再回答**」。
所以哪怕最终走 REFUSE，**检索也确实发生了** —— 这正是 R4
「REFUSE 时要列出最接近的 2–3 个知识点」能成立的前提。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import QaSession, QaTurn, utc_now_iso
from app.tutor import retrieve as R
from app.tutor import templates as T
from app.tutor.state import (
    STATE_TO_TURN,
    STUCK_THRESHOLD,
    Decision,
    State,
    Verdict,
    judge_answer,
    next_state,
    should_show_downgrade_notice,
)


@dataclass
class TurnResult:
    """一次 `ask` 的完整结果 —— SSE 与落库都从这里取数。"""

    decision: Decision
    reply_md: str
    hits: list[R.Hit]
    is_out_of_scope: bool
    template_meta: dict[str, Any]
    diagnosis: dict[str, Any]
    show_downgrade_notice: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.decision.state.value,
            "turn_type": self.decision.turn_type.value,
            "hint_level": self.decision.stuck_count,
            "reply_md": self.reply_md,
            "retrieved_kp_ids": [h.kp_id for h in self.hits],
            "is_out_of_scope": self.is_out_of_scope,
            "diagnosis": self.diagnosis,
            "template": self.template_meta,
            "show_downgrade_notice": self.show_downgrade_notice,
        }


def _history(session: Session, session_id: str) -> list[QaTurn]:
    return list(
        session.scalars(
            select(QaTurn).where(QaTurn.session_id == session_id).order_by(QaTurn.seq)
        ).all()
    )


def _stuck_count(session: Session, session_id: str) -> int:
    """数「从最后一次导师轮开始，学生连续答不上几次」。

    ## 为什么不是简单地数全部 turn

    SPEC R3 说的是**连续** 2 次。所以：
    - 遇到 `confirm` / `explain` → 序列被"收敛"打断 → **清零**
    - 遇到 `hint1` / `hint2` → **续上计数**

    这个函数是 R3 的**唯一数据来源** —— 它错了，硬规则就废了。
    所以它的测试是必须的（见 tests/test_tutor_state.py）。
    """
    stuck = 0
    for turn in _history(session, session_id):
        if turn.role != "tutor":
            continue
        if turn.turn_type in ("hint1", "hint2"):
            stuck += 1
        elif turn.turn_type in ("confirm", "explain"):
            stuck = 0
    return stuck


def _is_first_turn(session: Session, session_id: str) -> bool:
    """这个会话还没有过**任何导师轮**吗 —— 决定 R2 是否生效。

    ⚠️ 判据是"有没有导师轮"，**不是"这是不是第一句学生话"**。
    因为学生可能连发两条消息而系统只回了一条，用"第几句"会误判。
    """
    return not any(t.role == "tutor" for t in _history(session, session_id))


def _diagnosis(
    decision: Decision,
    hits: list[R.Hit],
    verdict: Verdict | None,
    session: Session,
) -> dict[str, Any]:
    """组装 R5 的三件产出。**三件都必须有**，缺一件就是没实现 R5。"""
    involved = [f"{h.name}（难度 {h.difficulty}）" for h in hits[:3]] or ["（未命中任何知识点）"]

    # 卡在哪一步 —— 依据来自 state.judge_answer，不是"感觉"
    if decision.state == State.REFUSE:
        stuck_at = "问题不在材料范围内"
        evidence = "检索未命中任何高于阈值的知识点（R4）"
    elif verdict is None:
        stuck_at = "首次作答前"
        evidence = "本轮是提问，还没有学生作答"
    elif verdict == Verdict.CORRECT:
        stuck_at = "已答对"
        evidence = decision.evidence or "作答与材料文本有实质重叠"
    else:
        stuck_at = "答错概念本身"
        evidence = decision.evidence or "作答与材料无重叠"
        # ★ F3.8：卡点根因回溯 —— 找到断层的前置
        if decision.root_cause_kp_id:
            brief = R.kp_brief(session, decision.root_cause_kp_id)
            if brief:
                stuck_at = f"前置未掌握（{brief}）"
                evidence = (
                    f"{decision.kp_id} 的 hard 前置链上，{brief} 是最远的一个 ——"
                    "**根因更可能在这里，而不是当前这一题**"
                )

    # 下一步建议练习 —— 按状态给，不是固定文案
    practice = {
        State.S1_PROBE: "先用自己的话复述一遍这个概念，再回答上面的问题",
        State.S2_HINT1: "对照摘要，找出你刚才漏掉的那个关键词",
        State.S3_HINT2: "把原文那句话抄一遍，并标出它解释了哪一步",
        State.S4_EXPLAIN: "合上材料，把刚才的讲解复述一遍；然后做同章节的相邻知识点",
        State.CONFIRM: "做同章节的相邻知识点，检验是不是真懂（而不是记住）",
        State.REFUSE: "换一个已入库的知识点提问，或者补充材料后重新上传",
    }[decision.state]

    return {
        "knowledge_points": involved,
        "stuck_at": stuck_at,
        "stuck_evidence": evidence,
        "next_practice": practice,
        "root_cause_kp_id": decision.root_cause_kp_id,
    }


def run_turn(
    session: Session,
    *,
    session_id: str,
    student_text: str,
    seq: int,
) -> TurnResult:
    """跑一轮答疑：检索 → 状态机 → 组装回复 → 落库。

    ## 落库策略：**先写学生轮，再写导师轮**

    `qa_turns.seq` 是会话内单调递增的（api-spec：SSE 的 `id:` 也用它）。
    学生轮先落，导师轮的 seq = 学生轮 + 1，这样 SSE 的 `id` 和库里的 seq 天然一致 ——
    `Last-Event-ID` 断线续推才有依据。
    """
    sess = session.get(QaSession, session_id)
    if sess is None:
        raise ValueError(f"会话不存在：{session_id}")

    scope = sess.material_scope

    # ---- ① 检索（R1：永远先检索）--------------------------------------------
    hits = R.search_kps(session, student_text, material_scope=scope)
    out_of_scope = R.is_out_of_scope(hits)

    # ---- ② 状态机 -------------------------------------------------------------
    first = _is_first_turn(session, session_id)
    stuck = _stuck_count(session, session_id)

    verdict: Verdict | None = None
    top = hits[0] if hits else None
    if not first and top is not None:
        verdict, why = judge_answer(
            student_text,
            kp_name=top.name,
            kp_summary=top.summary_md,
            kp_quote=top.source_quote,
        )
    else:
        why = ""

    state, new_stuck, notes = next_state(
        is_first_turn=first,
        stuck_count=stuck,
        verdict=verdict,
        has_hit=not out_of_scope,
    )
    turn_type = STATE_TO_TURN[state]

    decision = Decision(
        state=state,
        turn_type=turn_type,
        stuck_count=new_stuck,
        kp_id=top.kp_id if top else None,
        stuck_at="",
        evidence=why,
        notes=notes,
    )

    # ★ 根因回溯只在这一轮真的"卡住"时做 —— 不卡就别往前置上引
    if state in (State.S2_HINT1, State.S3_HINT2) and top is not None:
        decision.root_cause_kp_id = R.root_cause_of(session, top.kp_id)

    # ---- ③ 组装回复 ----------------------------------------------------------
    pre_name = pre_sum = ""
    if decision.root_cause_kp_id:
        pre_kp = session.get(type(top), decision.root_cause_kp_id) if top else None  # type: ignore[arg-type]
        if pre_kp is not None:
            pre_name, pre_sum = pre_kp.name, pre_kp.summary_md or ""

    variant_q = R.sibling_variant(session, top.kp_id) if top else ""

    reply_md, tpl_meta = T.build_reply(
        turn_type,
        seed=f"{session_id}:{seq}",
        kp_name=top.name if top else "",
        summary=top.summary_md if top else "",
        quote=top.source_quote if top else "",
        pre_name=pre_name,
        pre_summary=pre_sum,
        candidates=[h.name for h in hits[:3]],
        variant_question=variant_q,
    )

    diagnosis = _diagnosis(decision, hits, verdict, session)
    decision.stuck_at = diagnosis["stuck_at"]

    # ---- ④ 落库 --------------------------------------------------------------
    now = utc_now_iso()
    session.add(QaTurn(
        id=f"qt_{session_id}_{seq}",
        session_id=session_id,
        seq=seq,
        role="student",
        content_md=student_text,
        turn_type=None,
        grounded=0,
        created_at=now,
    ))
    session.add(QaTurn(
        id=f"qt_{session_id}_{seq + 1}",
        session_id=session_id,
        seq=seq + 1,
        role="tutor",
        content_md=reply_md,
        turn_type=turn_type.value,
        retrieved_kp_ids=json.dumps([h.kp_id for h in hits], ensure_ascii=False),
        retrieved_block_ids=None,
        grounded=0 if out_of_scope else 1,   # ★ REFUSE 的轮次不计入"基于材料"
        diagnosis_json=json.dumps(diagnosis, ensure_ascii=False),
        created_at=utc_now_iso(),
    ))
    sess.updated_at = utc_now_iso()
    session.commit()

    return TurnResult(
        decision=decision,
        reply_md=reply_md,
        hits=hits,
        is_out_of_scope=out_of_scope,
        template_meta=tpl_meta,
        diagnosis=diagnosis,
        show_downgrade_notice=should_show_downgrade_notice(state),
    )


#: 下一轮学生轮的 seq（学生轮 +1 = 导师轮，再 +1 = 下一个学生轮）
def next_seq(session: Session, session_id: str) -> int:
    turns = _history(session, session_id)
    return (turns[-1].seq + 1) if turns else 1


__all__ = ["TurnResult", "run_turn", "next_seq", "STUCK_THRESHOLD"]
