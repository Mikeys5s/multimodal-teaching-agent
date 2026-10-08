"""把 `engine.run_turn` 的结果编成 SSE 事件序列（归属：P2）。

## 边界

`qa.py` 只做「拿 HTTP 请求 → 调本模块 → 把帧写回响应」。
**所有"这一轮说什么、什么顺序发"的逻辑都在这里** —— 因为它是
**契约的一部分**（api-spec §5 规定了固定的事件顺序），不该散在端点函数里。

## 事件顺序（api-spec 固定）

    retrieved → state → delta* → diagnosis → done

**顺序是契约，不是实现细节**：
- `retrieved` 必须**先于任何 delta** —— 前端据此先渲染溯源卡片，
  让"先检索再回答"这件事**在界面上可见**（而不是只在日志里）
- `diagnosis` 必须在 `delta` 之后 —— 它是这一轮的**结论**，
  边生成边下结论会让"卡点判定"看起来像猜的

## 分块推送

`delta` 是把回复文本切块发的。**切块不是为了好看，是为了首 token 时间**：
SPEC §5.3 R7 要求「首 token ≤ 3s」。整段一次性发也能"看起来像流式"，
但那不满足 R7 —— **因为首 token 等于整段生成完的时刻**。

（当前实现是确定性算法，生成是瞬时的。切块 + 小 sleep 是为了
**让前端能真实地看到流式效果**，也是为了让"首 token"这个概念有意义。
接上真正的 LLM 后，切块点由模型产出决定，这个函数不用改。）
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from app.schemas.qa import (
    DiagnosisKpOut,
    NextPracticeOut,
    SseDeltaEvent,
    SseDiagnosisEvent,
    SseDoneEvent,
    SseRetrievedEvent,
    SseStateEvent,
    SseUsageOut,
    StuckAtOut,
)
from app.tutor.engine import TurnResult
from app.tutor.state import hint_level_of

#: 每个 delta 最多多少字 —— 太小会让事件数爆炸，太大就失去了流式感。
DELTA_CHUNK = 24

#: 块间间隔（秒）。**只为了视觉上的流式感**，不影响正确性。
#: 取 0.02：一段 300 字的回复约 13 块 → 0.26s，**远低于 R7 的 3s 上限**。
DELTA_SLEEP = 0.02



# ---------------------------------------------------------------------------
# 可显示名字（**把 kp_id 换成人看得懂的东西**）
# ---------------------------------------------------------------------------

_TITLES: dict[str, str] | None = None


def _load_titles() -> dict[str, str]:
    """读 `backend/app/kp-titles.json` → `{kp_id: display_title}`（只读一次）。

    **为什么答疑侧也要用它**：答疑里原本只吐 `kp_id`，学生看不懂；
    而**原名也常被切坏**（`There` / `which time the congestion wind`）——
    **可读标题是从材料小节标题或首句提炼的，学生才看得懂**。

    **加载失败返回空 dict** ⇒ 全部退回原名 ⇒ **服务照常**。
    """
    global _TITLES
    if _TITLES is None:
        import json as _json
        import pathlib as _pathlib

        p = _pathlib.Path(__file__).resolve().parents[1] / "kp-titles.json"
        try:
            items = _json.loads(p.read_text(encoding="utf-8")).get("items", [])
            _TITLES = {x["kp_id"]: x["display_title"]
                       for x in items if x.get("display_title")}
        except Exception:  # noqa: BLE001
            _TITLES = {}
    return _TITLES


def display_name(kp_id: str, fallback: str = "") -> str:
    """给一个 kp_id，返回**给人看的名字**。

    优先级：**可读标题** → **调用方给的 fallback（通常是原名）** → **kp_id 自己**。

    ⚠️ 最后一档「退回 kp_id」是**兜底**，正常不该走到 ——
    走到说明这个名字在库里找不到，**那本身是个数据问题**，不该靠前端猜。
    """
    t = _load_titles().get(kp_id)
    if t:
        return t
    return fallback or kp_id


def _chunks(text: str, size: int = DELTA_CHUNK) -> Iterator[str]:
    """按固定长度切块。**按标点优先断句**，避免把词切断（读起来更自然）。"""
    buf = ""
    for ch in text:
        buf += ch
        if len(buf) >= size and ch in "。！？\n；：，、.!?;:,":
            yield buf
            buf = ""
    if buf:
        yield buf


def _name_of(tr: TurnResult, kp_id: str) -> str:
    """从本轮命中里找出这个 kp_id 的**原名**（作为 display_name 的 fallback）。

    ⚠️ **必须定义在 `_diagnosis_event` 之前** ——
    2026-10-08 我把它加在了 `event_stream` 前，而 `_diagnosis_event` 更靠前，
    ⇒ 线上报 `NameError: name '_name_of' is not defined`（**事件流被掐断**）。
    """

    for h in tr.hits:
        if h.kp_id == kp_id:
            return h.name
    return ""


def _diagnosis_event(seq: int, tr: TurnResult) -> SseDiagnosisEvent:
    """把 `engine` 的诊断 dict 转成契约要求的三件产出。

    ⚠️ **字段名要逐个对上** —— `engine` 里用的是 `knowledge_points`（中文名列表）
    和 `next_practice`（一句建议），而契约要的是结构化对象
    （`DiagnosisKpOut(kp_id, name, difficulty)` / `NextPracticeOut(kp_id, task)`）。

    **转换放在这里而不是 engine 里**：engine 是"判断"，不该知道 HTTP 契约长什么样。
    """
    d: dict[str, Any] = tr.diagnosis

    kps: list[DiagnosisKpOut] = []
    for hit in tr.hits[:3]:
        kps.append(DiagnosisKpOut(kp_id=hit.kp_id, name=hit.name, difficulty=hit.difficulty))

    stuck = StuckAtOut(
        step=str(d.get("stuck_at") or "未知"),
        evidence_kp_id=tr.decision.root_cause_kp_id or tr.decision.kp_id,
        # ⭐ 同时给名字 —— 前端不该渲染 kp_id
        evidence_kp_name=display_name(
            tr.decision.root_cause_kp_id or tr.decision.kp_id or "",
            _name_of(tr, tr.decision.root_cause_kp_id or tr.decision.kp_id or ""),
        ),
        evidence_misconception_id=None,   # 误区表为空（见 templates.DATA_SOURCE 的说明）
    )

    practices: list[NextPracticeOut] = []
    if tr.hits:
        practices.append(
            NextPracticeOut(
                kp_id=tr.hits[0].kp_id,
                # ⭐ 名字（**优先可读标题**）：前端不该渲染 kp_id
                kp_name=display_name(tr.hits[0].kp_id, tr.hits[0].name),
                task=str(d.get("next_practice") or ""),
            )
        )

    return SseDiagnosisEvent(
        seq=seq, knowledge_points=kps, stuck_at=stuck, next_practice=practices,
    )


def event_stream(
    tr: TurnResult,
    *,
    session_id: str,
    student_seq: int,
    start_seq: int = 1,
) -> Iterator[tuple[str, Any]]:
    """产出一轮的完整事件序列。**返回 (事件名, 事件模型) 的迭代器。**

    为什么返回元组而不是直接返回 SSE 字符串：
    **让测试可以断言"事件名与顺序"，而不必去解析字符串**。
    拼帧是 `qa.py` 的事（`_sse_frame`），那一层薄得不需要测。

    `student_seq`：**学生轮**在 `qa_turns` 里的 seq。导师轮的 id 是
    `qt_<sid>_<student_seq + 1>` —— 这个约定在 `engine.run_turn` 的落库处，
    **两处必须一致**（否则 `done.turn_id` 会指向不存在的轮次）。
    """
    seq = start_seq

    # ---- ① retrieved（必须最先）--------------------------------------------
    yield "retrieved", SseRetrievedEvent(
        seq=seq,
        kp_ids=[h.kp_id for h in tr.hits],
        # ⭐ **与 kp_ids 一一对应的可显示名字** ——
        #    前端渲染「检索材料」时用这个，而不是直接显示 kp_id。
        #    优先可读标题，取不到退回原名（`hit.name`）——**不编**。
        kp_names=[display_name(h.kp_id, h.name) for h in tr.hits],
        block_ids=[],                      # 溯源到具体块：抽取还没落 block 级引用，如实留空
        is_out_of_scope=tr.is_out_of_scope,
    )
    seq += 1

    # ---- ② state -----------------------------------------------------------
    yield "state", SseStateEvent(
        seq=seq,
        turn_type=tr.decision.turn_type.value,
        state=tr.decision.state.value,
        hint_level=hint_level_of(tr.decision.state),
    )
    seq += 1

    # ---- ③ delta* ----------------------------------------------------------
    for chunk in _chunks(tr.reply_md):
        yield "delta", SseDeltaEvent(seq=seq, text=chunk)
        seq += 1
        time.sleep(DELTA_SLEEP)

    # ---- ④ diagnosis -------------------------------------------------------
    yield "diagnosis", _diagnosis_event(seq, tr)
    seq += 1

    # ---- ⑤ done ------------------------------------------------------------
    yield "done", SseDoneEvent(
        seq=seq,
        turn_id=f"qt_{session_id}_{student_seq + 1}",
        latency_ms=None,                   # 确定性算法，几十毫秒；不虚报成"模型耗时"
        usage=SseUsageOut(input_tokens=None, output_tokens=None),   # 运行期零模型调用
    )
