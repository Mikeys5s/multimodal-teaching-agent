"""知识点查询（归属：P2）。对应 docs/api-spec.md §4.2 / §4.3 / §4.4，端点 14、15、28。

★ 本文件承载**创新点的查询侧**：
  · `GET /api/knowledge-points/{id}` 返回的 `prerequisites[].reason` 让"为什么这个要排在前面"可解释；
  · `GET /api/knowledge-points/{id}/gap-analysis` 是**卡点根因回溯** ——
    不满足于说"你这题错了"，而是沿 hard 边反向回溯指出更可能的根因。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.pagination import PageData, PageParams
from app.core.response import Envelope, ok
from app.db import get_db
from app.schemas.graph import (
    GapAnalysisOut,
    GapSourceOut,
    HardPrereqOut,
    KpBriefOut,
    LikelyGapOut,
)
from app.schemas.knowledge import (
    ChapterRefOut,
    ExampleOut,
    KpDetailOut,
    KpItemOut,
    MisconceptionOut,
    PrerequisiteOut,
    SectionRefOut,
    SourceRefOut,
)

router = APIRouter(tags=["knowledge"])

DbSession = Annotated[Session, Depends(get_db)]
PageDep = Annotated[PageParams, Depends(PageParams.as_dependency)]

MOCK_MODE = True

KP_TYPES = ("concept", "skill", "theorem", "method", "fact")

KP_ID = "kp_9f2a1c40_000_002_003"


# ---------------------------------------------------------------------------
# mock 数据（计算机网络 · 传输层，演示时直接可用）
# ---------------------------------------------------------------------------


def _mock_kp(kp_id: str = KP_ID) -> KpItemOut:
    return KpItemOut(
        id=kp_id,
        name="TCP 拥塞控制",
        summary_md="发送方通过动态调整拥塞窗口 cwnd，适应网络拥塞程度，避免压垮网络。",
        difficulty=4,
        difficulty_reason="需要同时理解滑动窗口、RTT 估计与四种拥塞控制阶段的相互作用",
        kp_type="concept",
        chapter=ChapterRefOut(id="ch_9f2a1c40_000", number="5", title="传输层"),
        section=SectionRefOut(id="sec_9f2a1c40_000_002", number="5.3", title="TCP 拥塞控制"),
        source=SourceRefOut(
            material_id="mat_9f2a1c40",
            material_name="第5章-传输层.pdf",
            page=88,
            block_id="blk_9f2a1c40_00003",
            quote="拥塞窗口 cwnd 的大小由发送方根据网络拥塞程度动态调整。",
        ),
        prerequisite_count=2,
        example_count=3,
        misconception_count=1,
        needs_review=False,
        confidence=0.93,
    )


def _mock_detail(kp_id: str) -> KpDetailOut:
    base = _mock_kp(kp_id)
    return KpDetailOut(
        **base.model_dump(),
        prerequisites=[
            PrerequisiteOut(
                kp_id="kp_9f2a1c40_000_001_002",
                name="滑动窗口机制",
                relation_type="hard",
                reason="不理解发送窗口如何随 ACK 滑动，就无法理解 cwnd 调节的对象是什么",
                confidence=0.9,
            ),
            PrerequisiteOut(
                kp_id="kp_9f2a1c40_000_001_005",
                name="RTT 与超时重传",
                relation_type="hard",
                reason="RTT 估计决定了超时阈值，而超时是拥塞判断的触发条件",
                confidence=0.86,
            ),
        ],
        examples=[
            ExampleOut(
                id="ex_9f2a1c40_001",
                question_type="single_choice",
                stem_md="慢启动阶段 cwnd 的增长方式是：",
                options_json='[{"key":"A","content":"线性增长"},{"key":"B","content":"指数增长"}]',
                answer_md="B",
                analysis_md="每收到一个 ACK，cwnd 增加一个 MSS，因此每经过一个 RTT 翻倍。",
                difficulty=3,
                source_page=89,
            )
        ],
        misconceptions=[
            MisconceptionOut(
                id="mis_9f2a1c40_001",
                description="把拥塞窗口 cwnd 与接收窗口 rwnd 混为一谈",
                cause="两者都叫「窗口」且都限制发送量，容易合并成一个概念",
                remedy="强调 cwnd 反映网络容量、rwnd 反映接收方缓冲；实际发送窗口取两者较小值",
                source="human",
                confidence=0.92,
            )
        ],
    )


# ---------------------------------------------------------------------------
# 端点 14：知识点列表
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-points",
    response_model=Envelope[PageData[KpItemOut]],
    summary="知识点查询",
    description=(
        "支持按章节 / 难度区间 / 类型 / 待核实 / 关键词过滤。\n\n"
        "`needs_review` 为**布尔**（api-spec v1.3 统一），不传即不过滤；"
        "`difficulty_min > difficulty_max` 返回 400。"
    ),
)
def list_knowledge_points(
    db: DbSession,
    page: PageDep,
    material_id: Annotated[str | None, Query()] = None,
    chapter_id: Annotated[str | None, Query()] = None,
    section_id: Annotated[str | None, Query()] = None,
    difficulty_min: Annotated[int | None, Query(ge=1, le=5)] = None,
    difficulty_max: Annotated[int | None, Query(ge=1, le=5)] = None,
    kp_type: Annotated[str | None, Query()] = None,
    needs_review: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(description="关键词全文检索")] = None,
) -> Envelope[PageData[KpItemOut]]:
    if (
        difficulty_min is not None
        and difficulty_max is not None
        and difficulty_min > difficulty_max
    ):
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            f"难度区间不合法：min={difficulty_min} 大于 max={difficulty_max}",
        )
    if kp_type is not None and kp_type not in KP_TYPES:
        raise ApiError(
            ErrorCode.INVALID_PARAM, f"kp_type 取值不合法：{kp_type}", {"allowed": list(KP_TYPES)}
        )
    for name, value in (
        ("material_id", material_id),
        ("chapter_id", chapter_id),
        ("section_id", section_id),
    ):
        if value is not None and not value:
            raise ApiError(ErrorCode.INVALID_PARAM, f"{name} 不能为空字符串")

    # 过滤逻辑（真实）已写完；数据源在 mock 模式下为样例
    items = [_mock_kp()] if MOCK_MODE else []
    if needs_review is not None:
        items = [i for i in items if i.needs_review == needs_review]
    if kp_type is not None:
        items = [i for i in items if i.kp_type == kp_type]
    return ok(PageData.of(items=items, total=len(items), params=page))


# ---------------------------------------------------------------------------
# 端点 15：知识点详情
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-points/{kp_id}",
    response_model=Envelope[KpDetailOut],
    summary="知识点详情",
    description=(
        "在列表项结构上追加三段：前置依赖 / 典型例题 / 常见误区。\n\n"
        "`prerequisites[].reason` **必须来自依赖边上的 reason** —— "
        "「为什么这个要排在前面」要能逐条说清，不是黑盒拓扑排序。"
    ),
)
def get_knowledge_point(kp_id: str, db: DbSession) -> Envelope[KpDetailOut]:
    _require_kp(kp_id)
    return ok(_mock_detail(kp_id))


# ---------------------------------------------------------------------------
# 端点 28：卡点根因回溯
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-points/{kp_id}/gap-analysis",
    response_model=Envelope[GapAnalysisOut],
    summary="卡点根因回溯",
    description=(
        "沿 `hard` 边反向可达，返回全部硬前置与「最可能的断层」。\n\n"
        "`student_evidence` 是**可重复查询参数**，传 `kp_misconceptions.id`；"
        "**无效值忽略而不报错** —— 它只影响排序精度，不该让整个请求失败（api-spec v1.3）。"
    ),
)
def gap_analysis(
    kp_id: str,
    db: DbSession,
    student_evidence: Annotated[
        list[str] | None, Query(description="本轮暴露的误区 id，可重复传入")
    ] = None,
) -> Envelope[GapAnalysisOut]:
    _require_kp(kp_id)
    evidence = student_evidence or []

    gap = LikelyGapOut(
        kp_id="kp_9f2a1c40_000_001_002",
        name="滑动窗口机制",
        evidence=(
            "本轮命中误区『把拥塞窗口与接收窗口混为一谈』"
            if evidence
            else "该前置被 3 个后续知识点共同依赖，是这条链上最可能的断层"
        ),
        source=GapSourceOut(material_id="mat_9f2a1c40", page=88),
    )
    return ok(
        GapAnalysisOut(
            target_kp=KpBriefOut(kp_id=kp_id, name="TCP 拥塞控制"),
            hard_prerequisites=[
                HardPrereqOut(
                    kp_id="kp_9f2a1c40_000_001_002",
                    name="滑动窗口机制",
                    depth=1,
                    reason="不理解窗口就无法理解 cwnd 的调节对象",
                ),
                HardPrereqOut(
                    kp_id="kp_9f2a1c40_000_001_005",
                    name="RTT 与超时重传",
                    depth=1,
                    reason="RTT 估计决定超时阈值，超时是拥塞判断的触发条件",
                ),
                HardPrereqOut(
                    kp_id="kp_9f2a1c40_000_000_001",
                    name="可靠数据传输的基本原理",
                    depth=2,
                    reason="滑动窗口与超时重传都建立在可靠传输的基本假设上",
                ),
            ],
            likely_gap=gap,
            suggestion=(
                "你这一题卡在「TCP 拥塞控制」，但根因更可能是「滑动窗口机制」没吃透 —— "
                "建议先回第 88 页复习窗口如何随 ACK 滑动，再回来学拥塞控制。"
            ),
        )
    )


def _require_kp(kp_id: str) -> None:
    """知识点 id 格式校验。

    mock 模式下按格式判断（不查库），让 P3 立刻能看到完整响应体；
    D6 之后改为真实查库。
    """
    if not kp_id.startswith("kp_"):
        raise ApiError(ErrorCode.NOT_FOUND, f"知识点 {kp_id} 不存在（id 应以 kp_ 开头）")
