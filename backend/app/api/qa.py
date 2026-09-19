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

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.response import Envelope, ok
from app.db import get_db
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

# ★ 骨架阶段开关：True = 业务数据返回 mock；P3 实现真实业务时置 False
MOCK_MODE = True

SESSION_ID = "qs_9f2a1c40_001"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _require_session(session_id: str) -> None:
    if not session_id.startswith("qs_"):
        raise ApiError(ErrorCode.NOT_FOUND, f"会话 {session_id} 不存在（id 应以 qs_ 开头）")


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
    # TODO(P3): 落库到 qa_sessions
    return ok(SessionCreatedOut(session_id=SESSION_ID))


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
    _require_session(session_id)
    # TODO(P3): 从 qa_turns 读取真实轮次
    return ok(
        SessionDetailOut(
            id=session_id,
            student_label="demo",
            material_scope=["mat_9f2a1c40"],
            created_at="2026-09-17T13:20:01+00:00",
            updated_at="2026-09-17T13:22:44+00:00",
            turns=[
                TurnOut(
                    id="turn_0001",
                    seq=0,
                    role="student",
                    content_md="这题为什么用快排不用冒泡？",
                    turn_type="student_question",
                    grounded=False,
                    created_at="2026-09-17T13:20:05+00:00",
                ),
                TurnOut(
                    id="turn_0002",
                    seq=1,
                    role="tutor",
                    content_md=(
                        "先想一个问题：如果数组已经是升序的，冒泡排序还需要比较多少次？快速排序呢？"
                    ),
                    turn_type="probe",
                    retrieved_kp_ids=["kp_9f2a1c40_000_002_003"],
                    retrieved_block_ids=["blk_9f2a1c40_00003"],
                    grounded=True,
                    diagnosis=DiagnosisOut(
                        knowledge_points=[
                            DiagnosisKpOut(
                                kp_id="kp_9f2a1c40_000_002_003",
                                name="快速排序的分区思想",
                                difficulty=3,
                            )
                        ],
                        stuck_at=StuckAtOut(
                            step="尚未建立分区与最终位置的关系",
                            evidence_kp_id="kp_9f2a1c40_000_002_003",
                        ),
                        next_practice=[
                            NextPracticeOut(
                                kp_id="kp_9f2a1c40_000_002_003",
                                task="手写一次 Hoare 分区过程",
                            )
                        ],
                    ),
                    latency_ms=2310,
                    created_at="2026-09-17T13:20:07+00:00",
                ),
            ],
        )
    )


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
    _require_session(session_id)

    # 续推：客户端带了 Last-Event-ID 就从它之后继续
    start_seq = 1
    if last_event_id and last_event_id.isdigit():
        start_seq = int(last_event_id) + 1

    return StreamingResponse(
        _mock_event_stream(session_id, start_seq),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 反代下禁用缓冲，否则流式会被攒起来一次性下发
        },
    )


def _mock_event_stream(session_id: str, start_seq: int) -> Iterator[str]:
    """★ 骨架阶段的 mock 事件序列 —— 顺序与字段严格按 api-spec §5.2。

    这段代码的价值不在于"能回答"，而在于**把 SSE 契约跑通**：
    P3 可以据此把前端的流式渲染、溯源卡片、三件产出面板全部写完。
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
    _require_session(session_id)
    # TODO(P3): 从会话的最后一条 turn 反推真实状态
    return ok(
        QaStateOut(
            state="S2_HINT1",
            hint_level=1,
            consecutive_failures=1,
            current_kp_id="kp_9f2a1c40_000_002_003",
            next_action="hint2",
            explain_threshold=2,
        )
    )


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
    _require_session(session_id)
    # TODO(P3): 聚合真实轮次
    return ok(
        SessionReportOut(
            session_id=session_id,
            turn_count=8,
            grounded_rate=1.0,
            stuck_points=[
                StuckAtOut(
                    step="尚未建立分区与最终位置的关系",
                    evidence_kp_id="kp_9f2a1c40_000_002_003",
                )
            ],
            suggested_practices=[
                NextPracticeOut(kp_id="kp_9f2a1c40_000_002_003", task="手写一次 Hoare 分区过程")
            ],
            summary_md=(
                "本次答疑共 8 轮，全部回答均基于教材内容（接地率 100%）。\n\n"
                "卡点集中在「快速排序的分区思想」——建议先用一个小数组手写一遍分区过程，"
                "再回头看复杂度分析。"
            ),
        )
    )


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
    _require_session(session_id)
    # TODO(P3): 真实删除
    return ok({"deleted": session_id})
