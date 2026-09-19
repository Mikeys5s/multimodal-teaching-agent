"""质量报告与导出（归属：P2）。对应 docs/api-spec.md §4.5 / §4.6，端点 18、19。

质量报告页是 Demo 视频里的一个亮点镜头 —— **把工程严谨度可视化**。
所以这里的每个比率都直接对应一条验收指标，不是为了好看而堆的仪表盘。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.response import CsvResponse, Envelope, ok, text_response
from app.db import get_db
from app.quality import check_acceptance as quality_check_acceptance
from app.quality import compute as quality_compute
from app.schemas.report import (
    AcceptanceRowOut,
    ExportKpOut,
    GraphStatsReportOut,
    KnowledgePointStatsOut,
    MaterialStatsOut,
    QaStatsOut,
    QualityReportOut,
)

router = APIRouter(tags=["report"])

DbSession = Annotated[Session, Depends(get_db)]

MOCK_MODE = True

EXPORT_COLUMNS = (
    "id",
    "name",
    "summary_md",
    "difficulty",
    "difficulty_reason",
    "kp_type",
    "chapter_number",
    "chapter_title",
    "section_number",
    "section_title",
    "source_material_id",
    "source_material_name",
    "source_page",
    "source_quote",
    "prerequisite_count",
    "needs_review",
)


# ---------------------------------------------------------------------------
# 端点 19：质量报告
# ---------------------------------------------------------------------------


@router.get(
    "/report/quality",
    response_model=Envelope[QualityReportOut],
    summary="质量报告",
    description=(
        "四段式统计：素材 / 知识点 / 图谱 / 答疑，外加 `acceptance`（验收指标逐条实测）。\n\n"
        "其中 `structure_complete_rate`（A2-1）、`grounding_rate`（A2-3）、"
        "`graph.cycle_count`（B1-2）、`graph.reason_complete_rate`（B1-5）、"
        "`qa.grounded_rate`（幻觉率 0）**直接对应验收指标**。\n\n"
        "**数据来源**：全部由 `app/quality.py::compute()` 从数据库实测得出，"
        "与 `scripts/evaluate.py` **同源** —— 不存在'报告页一套数字、验收另一套'。"
    ),
)
def quality_report(db: DbSession) -> Envelope[QualityReportOut]:
    # ★ 全部实测，不再有写死的数字。
    #
    # 这里曾经是一整块 mock（`total=184` / `edge_count=267` / …），与
    # `scripts/evaluate.py` 并行存在两套数字 —— 它们**会分叉，而且不报错**。
    # 现在两边都调同一个 `compute()`：报告页给评委看的数字，
    # 就是 `evaluate.py` 算出来的数字。
    report = quality_compute(db)

    return ok(
        QualityReportOut(
            materials=MaterialStatsOut(
                total=report["materials"]["total"],
                done=report["materials"]["done"],
                failed=report["materials"]["failed"],
                avg_quality_score=report["materials"]["avg_quality_score"],
            ),
            knowledge_points=KnowledgePointStatsOut(
                total=report["knowledge_points"]["total"],
                structure_complete_rate=report["knowledge_points"]["structure_complete_rate"],
                five_field_complete_rate=report["knowledge_points"]["five_field_complete_rate"],
                grounding_rate=report["knowledge_points"]["grounding_rate"],
                needs_review_count=report["knowledge_points"]["needs_review_count"],
            ),
            graph=GraphStatsReportOut(
                edge_count=report["graph"]["edge_count"],
                cycle_count=report["graph"]["cycle_count"],
                pruned_count=report["graph"]["pruned_count"],
                conflict_count=report["graph"]["conflict_count"],
                reason_complete_rate=report["graph"]["reason_complete_rate"],
                prerequisite_sampling_pass_rate=report["graph"][
                    "prerequisite_sampling_pass_rate"
                ],
            ),
            qa=QaStatsOut(
                session_count=report["qa"]["session_count"],
                turn_count=report["qa"]["turn_count"],
                grounded_rate=report["qa"]["grounded_rate"],
                refuse_count=report["qa"]["refuse_count"],
            ),
            acceptance=[AcceptanceRowOut(**row._asdict()) for row in quality_check_acceptance(report)],
        )
    )


# ---------------------------------------------------------------------------
# 端点 18：导出
# ---------------------------------------------------------------------------


def _mock_export_rows() -> list[ExportKpOut]:
    return [
        ExportKpOut(
            id="kp_9f2a1c40_000_002_003",
            name="TCP 拥塞控制",
            summary_md="发送方通过动态调整拥塞窗口 cwnd 适应网络拥塞程度。",
            difficulty=4,
            difficulty_reason="需要同时理解滑动窗口、RTT 估计与四个拥塞阶段的相互作用",
            kp_type="concept",
            chapter_number="5",
            chapter_title="传输层",
            section_number="5.3",
            section_title="TCP 拥塞控制",
            source_material_id="mat_9f2a1c40",
            source_material_name="第5章-传输层.pdf",
            source_page=88,
            source_quote="拥塞窗口 cwnd 的大小由发送方根据网络拥塞程度动态调整。",
            prerequisite_count=2,
            needs_review=False,
        ),
        ExportKpOut(
            id="kp_9f2a1c40_000_001_002",
            name="滑动窗口机制",
            summary_md="发送方无需等待确认即可连续发送多个报文段。",
            difficulty=3,
            difficulty_reason="窗口滑动与累计确认的关系需要借助图示才能建立直觉",
            kp_type="concept",
            chapter_number="5",
            chapter_title="传输层",
            section_number="5.2",
            section_title="可靠数据传输",
            source_material_id="mat_9f2a1c40",
            source_material_name="第5章-传输层.pdf",
            source_page=76,
            source_quote="窗口的大小决定了发送方在收到确认前可以发送的数据量。",
            prerequisite_count=1,
            needs_review=False,
        ),
    ]


def _to_csv(rows: list[ExportKpOut]) -> str:
    """扁平 CSV，含溯源列 —— 便于用 Excel 直接核对。

    用标准库 csv 而不是手拼字符串：字段里有逗号、引号、换行时手拼一定会出错。
    """
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        data = row.model_dump()
        writer.writerow(
            [str(data.get(col, "")) if data.get(col) is not None else "" for col in EXPORT_COLUMNS]
        )
    return buf.getvalue()


@router.get(
    "/export/knowledge-points",
    summary="导出知识点",
    description=(
        "`format=json` 返回全字段 JSON；`format=csv` 返回扁平 CSV（含溯源列）。\n\n"
        "**这是非 JSON 响应**（CSV 分支）：请求标识走 `X-Request-ID` 响应头；"
        "出错时仍返回 JSON 包封（api-spec §1.1 的非 JSON 例外条款）。"
    ),
    response_class=CsvResponse,
)
def export_knowledge_points(
    db: DbSession,
    format: Annotated[str, Query(pattern="^(json|csv)$", description="json 或 csv")] = "json",
):
    rows = _mock_export_rows() if MOCK_MODE else []
    if format == "csv":
        return text_response(_to_csv(rows), "text/csv; charset=utf-8")
    # json 分支返回包封（前端可直接解析）
    #
    # ⚠️ 必须用 `ok()` 助手构造，不能手写 `Envelope(ok=True, data=...)` ——
    # Envelope 的 request_id 是必填字段，手写会漏掉它并直接抛 ValidationError（500）。
    # 这个 bug 是被 tests/test_api_smoke.py 抓到的。
    return text_response(ok(rows).model_dump_json(), "application/json; charset=utf-8")
