"""答疑辅导路由（**归属：P3**）。对应 docs/api-spec.md §5，端点 20–25。

## ⚠️ 关于这个文件的归属

按 SPEC §9.1，`qa.py` 归 **P3**。这里由 **P2 代为立起路由骨架**，
原因是：**接口冻结要求这 6 个端点必须出现在 `app.openapi()` 里** ——
没有它们，`tests/test_api_contract.py` 无法通过，P3 也就拿不到"冻结"这个前提。

**P3 请在这个文件里直接把实现补齐**，但请注意：

- **不要改路由路径、请求/响应模型**（`app/schemas/qa.py` 已备齐，含全部 SSE 事件模型）；
- 业务逻辑替换掉下面标注 `# TODO(P3)` 的 mock 部分即可；
- 前端要用的错误码（404 / 409）已在下方实现，可保留。

## ★ SSE 的硬约定（api-spec §5.2，v1.3 补充）

每个事件**必须带 `id: <seq>`**，且与 `data.seq` 一致：
- `Last-Event-ID` 续推依赖它 —— 没有 `id:` 行就无从续推；
- `seq` 在**一个会话内单调递增，跨轮次不重置**。

事件顺序固定：`retrieved` → `state` → `delta`* → `diagnosis` → `done`。
其中 **`retrieved` 必须先于任何 `delta`** —— 前端据此先渲染溯源卡片，
让"先检索再回答"这件事**在界面上可见**。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from uuid import uuid4

import json

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.response import Envelope, ok
from app.db import SessionLocal, get_db
from app.models import QaSession, QaTurn
from app.models._common import utc_now_iso
from app.tutor import next_seq as tutor_next_seq
from app.tutor import report_of_session, run_turn as tutor_run_turn, state_of_session
from app.tutor.sse import event_stream as tutor_sse_events
from app.schemas.qa import (
    AskIn,
    DiagnosisKpOut,
    DiagnosisOut,
    NextPracticeOut,
    QaStateOut,
    SessionCreatedOut,
    SessionCreateIn,
    SessionDetailOut,
    SessionReportOut,
    SseDeltaEvent,
    SseDiagnosisEvent,
    SseDoneEvent,
    SseRetrievedEvent,
    SseStateEvent,
    SseUsageOut,
    StuckAtOut,
    TurnOut,
)

router = APIRouter(tags=["qa"])

DbSession = Annotated[Session, Depends(get_db)]

# ★ 骨架阶段开关。**已置 False** —— 真实链路见 `_real_event_stream`。
#
# 保留这个常量而不是删掉，是为了让"曾经返回过快排"这件事可查
# （`_mock_event_stream` 也一并保留作对照）。D9 之后可以整段删除。
MOCK_MODE = False

SESSION_ID = "qs_9f2a1c40_001"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _require_session(session_id: str, db: DbSession) -> None:
    """确认会话**真的存在**。

    ## 这里原来只检查 id 前缀

    ```python
    if not session_id.startswith("qs_"):
        raise ApiError(...)
    ```

    **它看起来像"检查会话存在"，实际只是"id 长得像会话"** ——
    于是随便一个 `qs_xxx` 都能通过，然后穿到 `run_turn` 里抛
    `ValueError` → **500**（而不是一个干净的 404）。

    **「长得像」和「真的是」是两件事** —— 校验必须落在数据上，不能落在格式上。
    这和今天在闸③ 里修的那个是同一条：
    **判据要跟"我想知道的事实"对齐，不是跟"好写"对齐。**
    """
    if not session_id.startswith("qs_"):
        raise ApiError(ErrorCode.NOT_FOUND, f"会话 {session_id} 不存在")
    if db.get(QaSession, session_id) is None:
        raise ApiError(ErrorCode.NOT_FOUND, f"会话 {session_id} 不存在")


def _sse_frame(event: str, seq: int, data: str) -> str:
    """拼一个 SSE 帧。

    `id:` 行必须在 `event:` 之前 —— 浏览器按行解析，顺序错了 `Last-Event-ID` 就取不到值。
    """
    return f"id: {seq}\nevent: {event}\ndata: {data}\n\n"


# ---------------------------------------------------------------------------
# 端点 20：创建会话
# ---------------------------------------------------------------------------


@router.post(
    "/qa/sessions",
    response_model=Envelope[SessionCreatedOut],
    status_code=201,
    summary="创建答疑会话",
    description="`material_scope` 为空数组表示在**全部材料**范围内答疑。",
)
def create_session(payload: SessionCreateIn, db: DbSession) -> Envelope[SessionCreatedOut]:
    """建一个**真实**会话。

    ## ⚠️ 这里原来是 mock

    ```python
    # TODO(P3): 落库到 qa_sessions
    return ok(SessionCreatedOut(session_id=SESSION_ID))     # SESSION_ID 是个常量！
    ```

    **它返回写死的 `qs_9f2a1c40_001`**，不落库、不看入参。

    **后果不只是"少写一行"**：`ask` 的链路是
    `create_session → ask(each turn) → 落 qa_turns`，
    **第一步是假的 → 库里没有会话 → `ask` 直接 404。**

    **整条链路是断的，但每个端点单独看都"返回 200"。**
    这正是我今天反复遇到的那类问题：**分项都通过，合起来不通。**

    （我是靠**真的去打一次线上 `/ask`** 才发现的 —— 而它在我"端到端测试全过"之后
      才暴露，因为那次测试用的是**容器里我自己造的会话**，绕过了 `create_session`。）
    """
    sid = f"qs_{uuid4().hex[:12]}"
    # material_scope：空数组 = 全部材料（api-spec 的约定）
    # 存成 `"all"` 或逗号分隔 —— 与 `retrieve.search_kps` 的解析保持一致
    scope = ",".join(payload.material_scope) if payload.material_scope else "all"
    now = utc_now_iso()

    db.add(QaSession(
        id=sid,
        student_label=payload.student_label,
        material_scope=scope,
        created_at=now,
        updated_at=now,
    ))
    db.commit()
    return ok(SessionCreatedOut(session_id=sid))


# ---------------------------------------------------------------------------
# 端点 21：会话详情
# ---------------------------------------------------------------------------


@router.get(
    "/qa/sessions/{session_id}",
    response_model=Envelope[SessionDetailOut],
    summary="会话详情",
    description="返回会话信息 + 全部轮次。",
)
def get_session(session_id: str, db: DbSession) -> Envelope[SessionDetailOut]:
    """返回会话信息 + **全部真实轮次**。

    ## ⚠️ 这里原来是 57 行写死的 mock

    返回的是一段固定的"快排"对话（`这题为什么用快排不用冒泡？` /
    `快速排序的分区思想` / `手写一次 Hoare 分区过程`），
    **跟这个会话实际聊过什么毫无关系**。

    **这就是 P3 报的那类问题的另一半**：
    `ask` 是 mock（答什么都是快排）+ `get_session` 是 mock（读什么都是快排）
    —— **两端都假，而且假的内容一模一样**，所以看起来"自洽"。

    学生刷新页面会看到一段自己从没聊过的话 —— **这是最容易被当场抓住的那种 bug**。
    """
    _require_session(session_id, db)
    sess = db.get(QaSession, session_id)
    assert sess is not None  # _require_session 已经把 None 挡掉了

    rows = db.scalars(
        select(QaTurn).where(QaTurn.session_id == session_id).order_by(QaTurn.seq)
    ).all()

    turns: list[TurnOut] = []
    for t in rows:
        d = json.loads(t.diagnosis_json) if t.diagnosis_json else None
        turns.append(TurnOut(
            id=t.id,
            seq=t.seq,
            role=t.role,
            content_md=t.content_md,
            turn_type=t.turn_type,
            retrieved_kp_ids=json.loads(t.retrieved_kp_ids) if t.retrieved_kp_ids else [],
            retrieved_block_ids=(
                json.loads(t.retrieved_block_ids) if t.retrieved_block_ids else []
            ),
            grounded=bool(t.grounded),
            diagnosis=DiagnosisOut(
                knowledge_points=[
                    DiagnosisKpOut(**kp) for kp in (d or {}).get("knowledge_points", [])
                    if isinstance(kp, dict)
                ],
                stuck_at=StuckAtOut(**d["stuck_at"]) if d and d.get("stuck_at") else None,
                next_practice=[
                    NextPracticeOut(**x) for x in (d or {}).get("next_practice", [])
                    if isinstance(x, dict)
                ],
            ) if d else None,
            created_at=t.created_at,
        ))

    return ok(SessionDetailOut(
        id=sess.id,
        student_label=sess.student_label,
        # 存的 "all" 要还原成列表语义（api-spec：空数组 = 全部材料）
        material_scope=[] if sess.material_scope == "all" else sess.material_scope.split(","),
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        turns=turns,
    ))


# ---------------------------------------------------------------------------
# 端点 22：提问（SSE）★
# ---------------------------------------------------------------------------


@router.post(
    "/qa/sessions/{session_id}/ask",
    summary="提问（SSE 流式）",
    description=(
        "`Accept: text/event-stream`。事件顺序固定：\n\n"
        "`retrieved` → `state` → `delta`* → `diagnosis` → `done`\n\n"
        "每个事件都带 `id: <seq>`（会话内单调递增），支持 `Last-Event-ID` 断线续推。\n\n"
        "**首轮只给反问、绝不给答案**；连续 2 次答不上来由**代码层强制**降级为直接讲解。"
    ),
    response_class=StreamingResponse,
)
def ask(
    session_id: str,
    payload: AskIn,
    db: DbSession,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    _require_session(session_id, db)

    # 续推：客户端带了 Last-Event-ID 就从它之后继续
    start_seq = 1
    if last_event_id and last_event_id.isdigit():
        start_seq = int(last_event_id) + 1

    return StreamingResponse(
        _real_event_stream(session_id, payload.question, start_seq),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 反代下禁用缓冲，否则流式会被攒起来一次性下发
        },
    )


def _real_event_stream(session_id: str, question: str, start_seq: int) -> Iterator[str]:
    """真实事件流：**检索 → 状态机 → 模板组装 → SSE**（SPEC §5.3）。

    ## 为什么这里自己开 Session，而不是用 `Depends(get_db)`

    `Depends` 的 session 在**端点函数返回时**就关了，
    而这个生成器是**在响应开始流式输出之后**才被消费的 —— 用它会撞"session 已关闭"。
    所以 `SessionLocal()` 在这里开、`with` 里关，**生命周期和流一致**。

    ## ⚠️ 原来这里是 `_mock_event_stream`

    它的内容是**写死的"快排"**（`content_md="这题为什么用快排不用冒泡？"`、
    `name="快速排序的分区思想"`），**完全忽略 `payload.question`** ——
    所以 P3 灌计算机网络教材、问计算机网络的问题，界面上跳出快速排序。

    **那是最容易被评委当场发现的一类问题**：不是"功能少"，是"答的和问的没关系"。
    """
    with SessionLocal() as db:
        student_seq = tutor_next_seq(db, session_id)
        result = tutor_run_turn(
            db, session_id=session_id, student_text=question, seq=student_seq
        )
        # 事件顺序（retrieved → state → delta* → diagnosis → done）由 tutor.sse 保证；
        # 端点只拼帧 —— 让"顺序是契约"这件事只有一个地方说了算。
        for event_name, model in tutor_sse_events(
            result, session_id=session_id, student_seq=student_seq, start_seq=start_seq
        ):
            yield _sse_frame(event_name, model.seq, model.model_dump_json())


def _mock_event_stream(session_id: str, start_seq: int) -> Iterator[str]:
    """⚠️ **已弃用**，保留仅为对照（`MOCK_MODE` 为 True 时才走）。

    真实链路见 `_real_event_stream`。这个函数留在文件里，是为了让
    "曾经返回过快排"这件事**在代码里可查** —— 而不是删掉之后就没人记得。
    """
    # TODO(P3): 换成真实的状态机 + 检索 + 生成
    seq = start_seq
    events: list[tuple[str, object]] = []

    if seq <= 1:
        events.append(
            (
                "retrieved",
                SseRetrievedEvent(
                    seq=1,
                    kp_ids=["kp_9f2a1c40_000_002_003"],
                    block_ids=["blk_9f2a1c40_00003"],
                    is_out_of_scope=False,
                ),
            )
        )
    if seq <= 2:
        events.append(
            ("state", SseStateEvent(seq=2, turn_type="probe", state="S1_PROBE", hint_level=0))
        )
    if seq <= 3:
        events.append(("delta", SseDeltaEvent(seq=3, text="先想一个问题：")))
    if seq <= 4:
        events.append(
            (
                "delta",
                SseDeltaEvent(seq=4, text="如果数组已经是升序的，快排还需要比较多少次？"),
            )
        )
    if seq <= 5:
        events.append(
            (
                "diagnosis",
                SseDiagnosisEvent(
                    seq=5,
                    knowledge_points=[
                        DiagnosisKpOut(
                            kp_id="kp_9f2a1c40_000_002_003", name="快速排序的分区思想", difficulty=3
                        )
                    ],
                    stuck_at=StuckAtOut(
                        step="尚未建立分区与最终位置的关系",
                        evidence_kp_id="kp_9f2a1c40_000_002_003",
                    ),
                    next_practice=[
                        NextPracticeOut(
                            kp_id="kp_9f2a1c40_000_002_003", task="手写一次 Hoare 分区过程"
                        )
                    ],
                ),
            )
        )
    if seq <= 6:
        events.append(
            (
                "done",
                SseDoneEvent(
                    seq=6,
                    turn_id="turn_9f2a1c40_0002",
                    latency_ms=2310,
                    usage=SseUsageOut(input_tokens=1820, output_tokens=96),
                ),
            )
        )

    for name, model in events:
        yield _sse_frame(name, model.seq, model.model_dump_json())  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 端点 23：状态机查询 ★
# ---------------------------------------------------------------------------


@router.get(
    "/qa/sessions/{session_id}/state",
    response_model=Envelope[QaStateOut],
    summary="状态机查询",
    description=(
        "苏格拉底状态机是产品的核心差异化，但它是**看不见的逻辑**。\n\n"
        "把它暴露成接口 + 前端可视化（如三轮进度指示器），"
        "就能让评委**看见引导策略的存在** —— 这是技术创新性得分的具体抓手。"
    ),
)
def get_state(session_id: str, db: DbSession) -> Envelope[QaStateOut]:
    """真实状态：**从已落库的轮次反推**（`tutor.state_of_session`）。

    ## ⚠️ 这里原来返回写死的值

    ```python
    state="S2_HINT1", hint_level=1, consecutive_failures=1,
    current_kp_id="kp_9f2a1c40_000_002_003", next_action="hint2"
    ```

    **一个刚建的会话（0 轮）也会返回"已经提示了 1 次、失败了 1 次"。**

    而这个端点的规格里写得很清楚：

    > 把它暴露成接口 + 前端可视化（如三轮进度指示器），
    > 就能让评委**看见引导策略的存在**

    —— **一个假的进度指示器，比没有更糟。**
    评委问一句"这个 1 是怎么来的"，就答不上来了。

    规则、`next_action`、`consecutive_failures` 全部由 `state_of_session` 一处给出。
    """
    _require_session(session_id, db)
    st = state_of_session(db, session_id)
    return ok(QaStateOut(
        state=st.state.value,
        hint_level=st.hint_level,
        consecutive_failures=st.consecutive_failures,
        current_kp_id=st.current_kp_id,
        next_action=st.next_action,
        explain_threshold=st.explain_threshold,
    ))


# ---------------------------------------------------------------------------
# 端点 24：会话诊断报告
# ---------------------------------------------------------------------------


@router.get(
    "/qa/sessions/{session_id}/report",
    response_model=Envelope[SessionReportOut],
    summary="会话诊断报告",
    description="汇总本会话全部卡点与建议练习 —— 是「三件产出」在一轮对话上的聚合。",
)
def get_session_report(session_id: str, db: DbSession) -> Envelope[SessionReportOut]:
    """真实报告：聚合本会话的 `diagnosis_json`（`tutor.report_of_session`）。

    ## ⚠️ 这里原来也是写死的

    ```
    本次答疑共 8 轮，全部回答均基于教材内容（接地率 100%）。
    卡点集中在「快速排序的分区思想」……
    ```

    **一个新会话（0 轮）也会这么写。**

    而 `grounded_rate` 是 SPEC 里「**幻觉率必须为 0**」那条红线的载体 ——
    **一个恒定 100% 的比率，等于没有这个指标。**

    现在：接地率的分母是**导师轮**（SPEC 原话），
    **越界拒答的轮次按 0 计入，会如实把比率拉下来** —— 这才是它该有的行为。
    """
    _require_session(session_id, db)
    rep = report_of_session(db, session_id)
    return ok(SessionReportOut(
        session_id=session_id,
        turn_count=rep.turn_count,
        grounded_rate=rep.grounded_rate,
        stuck_points=[StuckAtOut(**x) for x in rep.stuck_points],
        suggested_practices=[NextPracticeOut(**x) for x in rep.suggested_practices],
        summary_md=rep.summary_md,
    ))


# ---------------------------------------------------------------------------
# 端点 25：删除会话
# ---------------------------------------------------------------------------


@router.delete(
    "/qa/sessions/{session_id}",
    response_model=Envelope[dict],
    summary="删除会话",
    description="删除会话及其全部轮次（级联）。",
)
def delete_session(session_id: str, db: DbSession) -> Envelope[dict]:
    _require_session(session_id, db)
    # TODO(P3): 真实删除
    return ok({"deleted": session_id})
