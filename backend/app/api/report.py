"""质量报告与导出（归属：P2）。对应 docs/api-spec.md §4.5 / §4.6，端点 18、19。

质量报告页是 Demo 视频里的一个亮点镜头 —— **把工程严谨度可视化**。
所以这里的每个比率都直接对应一条验收指标，不是为了好看而堆的仪表盘。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.response import CsvResponse, Envelope, ok, text_response
from app.db import get_db
from app.kp_view import load_kp_items
from app.models import KnowledgePoint
from app.quality import acceptance_sample_sizes
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
            acceptance=_acceptance_rows(report),
        )
    )


def _acceptance_rows(report: dict[str, Any]) -> list[AcceptanceRowOut]:
    """把验收行 + 样本量拼起来。

    原先只返回行本身 —— 于是 0 个知识点时报告显示"五项全绿"。
    `passed=None` 表示"样本为 0，无从判定"；`sample_size=0` 说明为什么。
    """
    sizes = acceptance_sample_sizes(report)
    out: list[AcceptanceRowOut] = []
    for row in quality_check_acceptance(report):
        d = dict(row._asdict())
        d["sample_size"] = sizes.get(row.label)
        out.append(AcceptanceRowOut(**d))
    return out


# ---------------------------------------------------------------------------
# 端点 18：导出
# ---------------------------------------------------------------------------



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
    material_id: Annotated[str | None, Query(description="只导出某份材料的，不传则导全部")] = None,
):
    # ★ 真读库。装配走 `app.kp_view`（与列表/详情**同一份实现**）——
    #   否则"列表页显示难度 3、导出里是 4"这种不一致迟早出现，而且不报错。
    kps = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.material_id == material_id)
        if material_id is not None
        else select(KnowledgePoint)
    ).all()
    kps = sorted(kps, key=lambda k: (k.material_id, k.seq or 0))
    items = load_kp_items(db, list(kps))

    # 扁平化：导出是给 Excel 看的，嵌套引用要摊平
    rows = [
        ExportKpOut(
            id=i.id,
            name=i.name,
            summary_md=i.summary_md,
            difficulty=i.difficulty,
            difficulty_reason=i.difficulty_reason,
            kp_type=i.kp_type,
            chapter_number=i.chapter.number,
            chapter_title=i.chapter.title,
            section_number=i.section.number,
            section_title=i.section.title,
            source_material_id=i.source.material_id,
            source_material_name=i.source.material_name,
            source_page=i.source.page,
            source_quote=i.source.quote,
            prerequisite_count=i.prerequisite_count,
            needs_review=i.needs_review,
        )
        for i in items
    ]
    if format == "csv":
        return text_response(_to_csv(rows), "text/csv; charset=utf-8")
    # json 分支返回包封（前端可直接解析）
    #
    # ⚠️ 必须用 `ok()` 助手构造，不能手写 `Envelope(ok=True, data=...)` ——
    # Envelope 的 request_id 是必填字段，手写会漏掉它并直接抛 ValidationError（500）。
    # 这个 bug 是被 tests/test_api_smoke.py 抓到的。
    return text_response(ok(rows).model_dump_json(), "application/json; charset=utf-8")
