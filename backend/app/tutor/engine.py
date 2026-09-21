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

from app.models import KnowledgePoint, QaSession, QaTurn, utc_now_iso
from app.tutor import retrieve as R
from app.tutor import templates as T
from app.tutor.state import (
    STATE_TO_TURN,
    STUCK_THRESHOLD,
    Decision,
    State,
    Verdict,
    hint_level_of,
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
        if turn.turn_type in ("hint1", "hint2", "explain"):
            # ★ `explain` **也要 +1**（2026-09-21 全链路实测发现我昨天只修了一半）
            #
            # `STUCK_THRESHOLD = 2`，所以第 2 次答不上是**直接跳 `explain`**（不是 `hint2`）。
            # 我昨天把它从"清零"改成了"不增减" —— **不清零是对的，但不 +1 是错的**：
            #
            #     第 1 次答不上 → hint1     → stuck = 1   ✅
            #     第 2 次答不上 → explain   → stuck = 1   ❌ 应该是 2
            #
            # **`explain` 是「第 2 次答不上」这个事实的产物** ——
            # 它记的是"学生又失败了一次"，所以它和 `hint1`/`hint2` 一样要计入。
            #
            # 只"不清零"不够 —— 那只是让数字**停在 1**，而它该**走到 2**。
            # **"不要再犯错"和"要做对"是两件事。**
            stuck += 1
        elif turn.turn_type == "confirm":
            # ★ **只有"答对"才清零。**
            stuck = 0
    return stuck


def _is_first_turn(session: Session, session_id: str) -> bool:
    """这个会话还没有过**任何导师轮**吗 —— 决定 R2 是否生效。

    ⚠️ 判据是"有没有导师轮"，**不是"这是不是第一句学生话"**。
    因为学生可能连发两条消息而系统只回了一条，用"第几句"会误判。
    """
    return not any(t.role == "tutor" for t in _history(session, session_id))


def _carried_kp(session: Session, session_id: str) -> str | None:
    """这一轮该**延续**哪个知识点？返回 None 表示"这是全新提问"。

    ## 为什么需要它

    学生在被反问之后回一句「不知道」—— 这句**本身不含任何知识点线索**。
    如果拿它去检索，必然什么都搜不到，然后 R4 短路成 REFUSE，
    于是 **R3（连续 2 次答不上就强制讲解）永远触发不了**。

    **"不知道"是学生对上一个问题的回应，不是一个新的提问。**
    所以这一轮该讲的知识点 = **上一轮导师轮讲的那个**。

    ## 判据：**只有"提示类"轮次之后才延续**

    | 上一轮导师轮 | 这一轮的性质 | 延续？ |
    |---|---|---|
    | `probe` / `hint1` / `hint2` | **学生在回应那个反问** | ✅ 延续 |
    | `confirm` / `explain` | 那一轮已经**讲完了**；学生再说是新问题 | ❌ 不延续 |
    | `refuse` | 上一轮就没讲东西，无从延续 | ❌ 不延续 |

    ## ⚠️ 我第一版写的是"只要有导师轮就延续"，并且把它写成"已知取舍"

    那段 docstring 里我写：「真换了话题，学生会说出新的关键词 —— 但那时我们仍用
    旧知识点作答，**这是一个已知的取舍**」。

    **端到端实测证明那个取舍是错的**：讲完 `explain` 之后学生问
    「请证明黎曼猜想」—— 系统**拿上一轮的计算机网络知识点答了**，
    **R4（检索不到必须 REFUSE）直接失效**。

    **教训**：「已知取舍」这四个字不能代替验证。
    我在写的时候就能想到"换个话题会怎样"这个反例，**但我把它写进注释就安心了**。
    **注释不是测试。**
    """
    last: QaTurn | None = None
    for t in _history(session, session_id):
        if t.role == "tutor":
            last = t
    if last is None or not last.retrieved_kp_ids:
        return None
    # ★ 只有"学生还没答上来"的那两个状态才延续
    if last.turn_type not in ("probe", "hint1", "hint2"):
        return None
    try:
        ids = json.loads(last.retrieved_kp_ids)
    except (ValueError, TypeError):
        return None
    return ids[0] if isinstance(ids, list) and ids else None


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
    #
    # ⚠️ **"延续轮"不能用学生的话去检索。**（2026-09-20 端到端实测发现的缺陷）
    #
    # 学生在第 2 轮说「不知道」时，如果拿这三个字去检索 —— **它当然什么都搜不到**
    # → `has_hit=False` → **R4 短路直接 REFUSE**。
    # 于是「连续 2 次答不上 → 强制讲解」这条硬规则**永远触发不了**：
    # **学生越诚实地说"不知道"，系统越只会回"材料里没有"。**
    #
    # 判据：这一轮是不是"对上一条反问的回应"。
    # 是 → **沿用上一轮导师轮问的那个知识点**（那才是这一轮该讲的东西）；
    # 不是（全新提问）→ 用学生的话检索。
    carried = _carried_kp(session, session_id)
    if carried is not None:
        kp = session.get(KnowledgePoint, carried)
        hits = (
            [R.Hit(
                kp_id=kp.id, name=kp.name, summary_md=kp.summary_md or "",
                source_quote=kp.source_quote or "", difficulty=kp.difficulty or 3,
                section_id=kp.section_id,
                score=1.0,   # 我们本来就在讲它 —— 分数不该再来干扰
            )]
            if kp is not None
            else []
        )
    else:
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


# ---------------------------------------------------------------------------
# 读侧：从已落库的轮次**反推**当前状态与报告
# ---------------------------------------------------------------------------
#
# 这两个函数是「状态机的读」—— 放在这里而不是端点里，理由和写侧一样：
# **状态怎么算只有一个地方说了算。**
#
# ⚠️ 端点上那两个 `# TODO(P3)` 原来返回**写死的**值：
#
#     state="S2_HINT1", hint_level=1, consecutive_failures=1,
#     current_kp_id="kp_9f2a1c40_000_002_003"
#
# **一个刚建的会话（0 轮）也会返回"已经提示了 1 次"** ——
# 而前端的"三轮进度指示器"就是读这个字段画的。
# **它会让评委看到一个从未发生过的提示进度。**

#: 导师轮类型 -> 能被反推成的状态
_TURN_TO_STATE: dict[str, State] = {
    "probe": State.S1_PROBE,
    "hint1": State.S2_HINT1,
    "hint2": State.S3_HINT2,
    "explain": State.S4_EXPLAIN,
    "confirm": State.CONFIRM,
    "refuse": State.REFUSE,
}

#: 每个状态之后**下一个**该给的动作（`get_state` 的 `next_action`）。
NEXT_ACTION: dict[State, str] = {
    State.S1_PROBE: "等待学生作答（答不上则给 hint1）",
    State.S2_HINT1: "hint2",
    State.S3_HINT2: "explain",
    State.S4_EXPLAIN: "explain",
    State.CONFIRM: "换同章节相邻知识点巩固",
    State.REFUSE: "请学生换一个已入库的知识点，或补充材料",
}


@dataclass
class SessionState:
    """反推出来的会话状态 —— 纯数据，便于断言。"""

    state: State
    hint_level: int
    consecutive_failures: int
    current_kp_id: str | None
    next_action: str
    explain_threshold: int
    turn_count: int
    has_tutor_turn: bool


def state_of_session(session: Session, session_id: str) -> SessionState:
    """从已落库的轮次反推：**这个会话现在在状态机的哪一步**。

    `consecutive_failures` 直接复用 `_stuck_count` —— **同一个判据不写第二遍。**
    """
    turns = _history(session, session_id)
    tutor_turns = [t for t in turns if t.role == "tutor"]

    if not tutor_turns:
        return SessionState(
            state=State.S1_PROBE, hint_level=0, consecutive_failures=0,
            current_kp_id=None, next_action=NEXT_ACTION[State.S1_PROBE],
            explain_threshold=STUCK_THRESHOLD, turn_count=len(turns), has_tutor_turn=False,
        )

    last = tutor_turns[-1]
    state = _TURN_TO_STATE.get(last.turn_type or "", State.S1_PROBE)

    kp_id: str | None = None
    if last.retrieved_kp_ids:
        try:
            ids = json.loads(last.retrieved_kp_ids)
            kp_id = ids[0] if isinstance(ids, list) and ids else None
        except (ValueError, TypeError):
            kp_id = None

    return SessionState(
        state=state,
        hint_level=hint_level_of(state),
        consecutive_failures=_stuck_count(session, session_id),
        current_kp_id=kp_id,
        next_action=NEXT_ACTION[state],
        explain_threshold=STUCK_THRESHOLD,
        turn_count=len(turns),
        has_tutor_turn=True,
    )


@dataclass
class SessionReport:
    """会话级的"三件产出"聚合。"""

    turn_count: int
    grounded_rate: float
    stuck_points: list[dict[str, Any]]
    suggested_practices: list[dict[str, Any]]
    summary_md: str


def report_of_session(session: Session, session_id: str) -> SessionReport:
    """把整个会话的 `diagnosis_json` 聚合起来。

    ## `grounded_rate` 的分母是**导师轮**，不是全部轮

    SPEC：**「幻觉率的分母只用导师轮」** —— 学生轮没有"是否基于材料"这回事。
    **用全部轮次算会把分母撑大一倍、把比率算好看一倍。**

    ## `summary_md` 必须**基于真实数据**

    原来那段写死的：

        本次答疑共 8 轮，全部回答均基于教材内容（接地率 100%）。
        卡点集中在「快速排序的分区思想」……

    —— **一个刚建的会话（0 轮）也会这么写。**
    """
    turns = _history(session, session_id)
    tutor_turns = [t for t in turns if t.role == "tutor"]

    grounded = sum(1 for t in tutor_turns if t.grounded)
    rate = (grounded / len(tutor_turns)) if tutor_turns else 0.0

    stuck_points: list[dict[str, Any]] = []
    practices: list[dict[str, Any]] = []
    seen_stuck: set[str] = set()
    seen_practice: set[str] = set()

    for t in tutor_turns:
        if not t.diagnosis_json:
            continue
        try:
            d = json.loads(t.diagnosis_json)
        except (ValueError, TypeError):
            continue

        sa = d.get("stuck_at")
        if isinstance(sa, str) and sa and sa not in seen_stuck:
            seen_stuck.add(sa)
            stuck_points.append({
                "step": sa,
                "evidence_kp_id": d.get("root_cause_kp_id"),
                "evidence_misconception_id": None,
            })

        task = d.get("next_practice")
        kp = d.get("root_cause_kp_id")
        if kp is None and t.retrieved_kp_ids:
            try:
                ids = json.loads(t.retrieved_kp_ids)
                kp = ids[0] if isinstance(ids, list) and ids else None
            except (ValueError, TypeError):
                kp = None
        if isinstance(task, str) and task and isinstance(kp, str) and kp not in seen_practice:
            seen_practice.add(kp)
            practices.append({"kp_id": kp, "task": task})

    # 总结按真实数据分情况写，**不要一段固定的漂亮话**
    n_student = len(turns) - len(tutor_turns)
    if not tutor_turns:
        summary = "本次会话还没有答疑记录。问一个已入库材料里的问题，我来引导你。"
    elif rate >= 1.0:
        summary = (
            f"本次答疑共 {n_student} 个学生提问、{len(tutor_turns)} 轮引导，"
            "**全部回答都基于教材内容**（接地率 100%）。"
        )
    else:
        n_refuse = sum(1 for t in tutor_turns if t.turn_type == "refuse")
        summary = (
            f"本次答疑共 {n_student} 个学生提问、{len(tutor_turns)} 轮引导，"
            f"接地率 {rate:.0%}（其中 {n_refuse} 轮是越界拒答 —— "
            "**拒答轮按 0 计入，这是「宁缺毋错」原则的体现**）。"
        )

    if stuck_points:
        summary += f"\n\n卡点集中在：{stuck_points[0]['step']}。"
    if practices:
        summary += f"\n\n建议练习：{practices[0]['task']}"

    return SessionReport(
        turn_count=len(turns),
        grounded_rate=round(rate, 4),
        stuck_points=stuck_points,
        suggested_practices=practices,
        summary_md=summary,
    )


__all__ = [
    "NEXT_ACTION",
    "SessionReport",
    "SessionState",
    "TurnResult",
    "next_seq",
    "report_of_session",
    "run_turn",
    "state_of_session",
]
