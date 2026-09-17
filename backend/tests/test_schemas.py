"""契约层自检（归属：P2）。

**这层测的不是业务，是"契约没被改动过"。**

为什么值得单独写：
  · 契约字段名是**前后端的接口**。把 `material_id` 改成 `materialId` 不会让任何
    后端测试失败，却会让前端所有解析代码在白屏 —— 这类破坏性变更只能靠"钉住字段名"来防。
  · 有些字段**不能为空**（`source.quote` 撑 A2-3、`reason` 撑 B1-5），
    它们必须真的是 required，而不是"文档里写了非空、代码里 optional"。

字段清单是**手写**的，不是从模型里生成 —— 从模型生成就等于自己给自己判卷。
"""

from __future__ import annotations

import importlib

import pydantic
import pytest

SCHEMA_MODULES = [
    "app.schemas.meta",
    "app.schemas.material",
    "app.schemas.knowledge",
    "app.schemas.graph",
    "app.schemas.report",
    "app.schemas.qa",
    "app.schemas.job",
]


# ---------------------------------------------------------------------------
# 1. 所有 schema 模块可导入（先抓语法 / 循环导入问题）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", SCHEMA_MODULES)
def test_schema_module_imports_and_renders_json_schema(module: str) -> None:
    """模块能导入，且其中每个 BaseModel 都能渲染出 JSON Schema。"""
    mod = importlib.import_module(module)
    models = [
        obj
        for obj in vars(mod).values()
        if isinstance(obj, type)
        and issubclass(obj, pydantic.BaseModel)
        and obj is not pydantic.BaseModel
    ]
    assert models, f"{module} 里没有定义任何 BaseModel"

    for model in models:
        schema = model.model_json_schema()
        assert schema.get("type") == "object" or "properties" in schema, (
            f"{model.__name__} 渲染出的 JSON Schema 不像对象"
        )


# ---------------------------------------------------------------------------
# 2. ★ 字段名钉死 —— 这是契约最容易被无声破坏的地方
# ---------------------------------------------------------------------------

# 只钉关键字段（不是全部），因为新增字段是允许的，改名字和删字段才是破坏性的。
PINNED_FIELDS: dict[str, set[str]] = {
    # --- 元信息 ---
    "HealthOut": {"status", "db", "llm", "version"},
    "HealthPragmaOut": {"pragmas", "db_file"},
    "DbPragmaOut": {"journal_mode", "foreign_keys", "busy_timeout"},
    "CapabilitiesOut": {"supported_material_types", "max_upload_mb", "parse_methods", "llm_mode"},
    # --- 素材 ---
    "UploadAcceptedOut": {"material_id", "filename", "job_id"},
    "UploadRejectedOut": {"filename", "reason"},
    "UploadResultOut": {"accepted", "rejected"},
    "UncertainNoteOut": {"kind", "page", "block_id", "message", "severity"},
    "MaterialItemOut": {
        "id",
        "filename",
        "mime_type",
        "size_bytes",
        "source_type",
        "parse_method",
        "status",
        "page_count",
        "duration_sec",
        "char_count",
        "quality_score",
        "uncertain_count",
        "uncertain_notes",
        "created_at",
    },
    "BlockOut": {
        "id",
        "seq",
        "page_no",
        "line_start",
        "line_end",
        "block_type",
        "heading_level",
        "content_md",
        "image_path",
        "ocr_confidence",
    },
    "OutlineOut": {"material_id", "chapters"},
    "OutlineChapterOut": {"id", "number", "title", "seq", "sections"},
    "OutlineSectionOut": {"id", "number", "title", "seq", "knowledge_point_count"},
    "QuestionOut": {
        "id",
        "material_id",
        "source_page",
        "source_block_id",
        "question_type",
        "stem_md",
        "options_json",
        "answer_md",
        "answer_missing",
        "extraction_confidence",
        "pk_kp_id",
    },
    "ReparseAcceptedOut": {"material_id", "job_id"},
    # --- 知识点 ---
    "KpItemOut": {
        "id",
        "name",
        "summary_md",
        "difficulty",
        "difficulty_reason",
        "kp_type",
        "chapter",
        "section",
        "source",
        "prerequisite_count",
        "example_count",
        "misconception_count",
        "needs_review",
        "confidence",
    },
    "SourceRefOut": {"material_id", "material_name", "page", "block_id", "quote"},
    "PrerequisiteOut": {"kp_id", "name", "relation_type", "reason", "confidence"},
    "ExampleOut": {
        "id",
        "question_type",
        "stem_md",
        "options_json",
        "answer_md",
        "analysis_md",
        "difficulty",
        "source_page",
    },
    "MisconceptionOut": {"id", "description", "cause", "remedy", "source", "confidence"},
    "KpDetailOut": {"prerequisites", "examples", "misconceptions"},
    # --- 图谱 / 路径 / 卡点 ---
    "GraphNodeOut": {"id", "name", "difficulty", "chapter_id", "section_id", "needs_review"},
    "GraphEdgeOut": {"source", "target", "relation_type"},
    "GraphStatsOut": {
        "node_count",
        "edge_count",
        "cycle_count",
        "pruned_count",
        "conflict_count",
        "hard_edge_count",
        "soft_edge_count",
    },
    "GraphOut": {"material_id", "nodes", "edges", "stats"},
    "LearningPathStepOut": {"order", "kp_id", "name", "difficulty", "reason", "is_start_point"},
    "LearningPathOut": {"target_kp_id", "steps"},
    "GapAnalysisOut": {"target_kp", "hard_prerequisites", "likely_gap", "suggestion"},
    "HardPrereqOut": {"kp_id", "name", "depth", "reason"},
    "LikelyGapOut": {"kp_id", "name", "evidence", "source"},
    # --- 答疑 ---
    "SessionCreateIn": {"material_scope", "student_label"},
    "SessionCreatedOut": {"session_id"},
    "TurnOut": {
        "id",
        "seq",
        "role",
        "content_md",
        "turn_type",
        "retrieved_kp_ids",
        "retrieved_block_ids",
        "grounded",
        "diagnosis",
        "latency_ms",
        "created_at",
    },
    "SessionDetailOut": {
        "id",
        "student_label",
        "material_scope",
        "created_at",
        "updated_at",
        "turns",
    },
    "DiagnosisOut": {"knowledge_points", "stuck_at", "next_practice"},
    "StuckAtOut": {"step", "evidence_kp_id", "evidence_misconception_id"},
    "NextPracticeOut": {"kp_id", "task"},
    "QaStateOut": {
        "state",
        "hint_level",
        "consecutive_failures",
        "current_kp_id",
        "next_action",
        "explain_threshold",
    },
    "SessionReportOut": {
        "session_id",
        "turn_count",
        "grounded_rate",
        "stuck_points",
        "suggested_practices",
        "summary_md",
    },
    "AskIn": {"question"},
    "SseRetrievedEvent": {"seq", "kp_ids", "block_ids", "is_out_of_scope"},
    "SseStateEvent": {"seq", "turn_type", "state", "hint_level"},
    "SseDeltaEvent": {"seq", "text"},
    "SseDoneEvent": {"seq", "turn_id", "latency_ms", "usage"},
    "SseDiagnosisEvent": {"seq", "knowledge_points", "stuck_at", "next_practice"},
    # --- 报告 / 导出 ---
    "MaterialStatsOut": {"total", "done", "failed", "avg_quality_score"},
    "KnowledgePointStatsOut": {
        "total",
        "structure_complete_rate",
        "five_field_complete_rate",
        "grounding_rate",
        "needs_review_count",
    },
    "GraphStatsReportOut": {
        "edge_count",
        "cycle_count",
        "pruned_count",
        "conflict_count",
        "reason_complete_rate",
        "prerequisite_sampling_pass_rate",
    },
    "QaStatsOut": {"session_count", "turn_count", "grounded_rate", "refuse_count"},
    "QualityReportOut": {"materials", "knowledge_points", "graph", "qa"},
    "ExportKpOut": {
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
    },
    # --- 任务 ---
    "JobOut": {
        "id",
        "job_type",
        "target_id",
        "status",
        "progress",
        "stage_detail",
        "result_json",
        "error_message",
        "started_at",
        "finished_at",
        "created_at",
    },
    "JobListOut": {"items", "total"},
}


def _all_models() -> dict[str, type[pydantic.BaseModel]]:
    found: dict[str, type[pydantic.BaseModel]] = {}
    for module in SCHEMA_MODULES:
        mod = importlib.import_module(module)
        for name, obj in vars(mod).items():
            if (
                isinstance(obj, type)
                and issubclass(obj, pydantic.BaseModel)
                and obj is not pydantic.BaseModel
                and obj.__module__ == module
            ):
                found[name] = obj
    return found


@pytest.mark.parametrize("model_name", sorted(PINNED_FIELDS))
def test_pinned_field_names_are_intact(model_name: str) -> None:
    """★ 契约守卫：关键字段名一个都不能少、不能改名。

    新增字段是允许的（只断言"包含"），改名和删字段会让前端解析代码直接崩。
    """
    models = _all_models()
    assert model_name in models, f"找不到模型 {model_name} —— 是被改名还是被删了？"

    actual = set(models[model_name].model_fields)
    missing = PINNED_FIELDS[model_name] - actual
    assert not missing, (
        f"{model_name} 缺少字段 {sorted(missing)}。"
        f"如果是有意改名，请同步改 docs/api-spec.md 并告知 P3 —— 这是破坏性变更。"
    )


def test_every_schema_model_is_covered_or_intentionally_excluded() -> None:
    """防止"新加的模型没人管"：不在钉死清单里的模型要在下面的白名单里说明原因。"""
    # 允许不钉的模型（纯内部结构 / 只做嵌套用）
    allowed_unpinned = {
        "ChapterRefOut",
        "SectionRefOut",
        "DiagnosisKpOut",
        "KpBriefOut",
        "GapSourceOut",
        "SseUsageOut",
        "ExportHashOut",
    }
    uncovered = set(_all_models()) - set(PINNED_FIELDS) - allowed_unpinned
    assert not uncovered, (
        f"这些模型既没钉字段名也没进白名单：{sorted(uncovered)}。"
        "新增契约模型时请补进 PINNED_FIELDS。"
    )


# ---------------------------------------------------------------------------
# 3. 语义守卫：几个字段必须真的是 required
# ---------------------------------------------------------------------------


def test_source_quote_is_required() -> None:
    """★ `source.quote` 撑 A2-3「溯源覆盖率 100%」—— 它必须非空。

    数据库层是 NOT NULL，契约层也必须是 required：否则前端会以为"可能没有原文"，
    于是把引用展示做成了可选分支，验收时才发现根本不该存在这种分支。
    """
    from app.schemas.knowledge import SourceRefOut

    assert SourceRefOut.model_fields["quote"].is_required()

    with pytest.raises(pydantic.ValidationError):
        SourceRefOut(material_id="mat_a", material_name="a.pdf")


def test_prerequisite_reason_is_required() -> None:
    """★ `reason` 撑 B1-5「边理由完备率 100%」—— 同上，必须 required。"""
    from app.schemas.knowledge import PrerequisiteOut

    assert PrerequisiteOut.model_fields["reason"].is_required()

    with pytest.raises(pydantic.ValidationError):
        PrerequisiteOut(kp_id="kp_x", name="前置", relation_type="hard")


def test_reject_reason_is_required() -> None:
    """被拒绝的上传必须给出原因 —— 「不得整批失败」的前提是"说清楚为什么"。"""
    from app.schemas.material import UploadRejectedOut

    assert UploadRejectedOut.model_fields["reason"].is_required()


def test_stage_detail_documented_as_chinese_progress() -> None:
    """`stage_detail` 的用途必须在契约里写清楚 —— 否则会被当成技术日志字段填英文。"""
    from app.schemas.job import JobOut

    desc = JobOut.model_fields["stage_detail"].description or ""
    assert "中文" in desc or "人类可读" in desc, "stage_detail 的说明没有强调「给人看」"


def test_job_progress_is_bounded() -> None:
    """进度条的入参必须有界，否则前端进度条会画出界。"""
    from app.schemas.job import JobOut

    with pytest.raises(pydantic.ValidationError):
        JobOut(
            id="job_1",
            job_type="parse",
            status="running",
            progress=150,
            created_at="2026-09-17T12:00:00+00:00",
        )


# ---------------------------------------------------------------------------
# 4. 分页契约
# ---------------------------------------------------------------------------


def test_pagination_defaults_match_spec() -> None:
    """默认值必须与 api-spec §1.3 一致（v1.3 才补上，是最容易被各写一套的地方）。"""
    from app.core.pagination import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

    assert DEFAULT_PAGE == 1
    assert DEFAULT_PAGE_SIZE == 20
    assert MAX_PAGE_SIZE == 100


def test_pagination_rejects_out_of_range_with_chinese_message() -> None:
    """越界要返回我们的 INVALID_PARAM（中文），不是 FastAPI 默认的英文 422。"""
    from app.core.errors import ApiError, ErrorCode
    from app.core.pagination import PageParams

    with pytest.raises(ApiError) as exc:
        PageParams.as_dependency(page=1, page_size=999)
    assert exc.value.code is ErrorCode.INVALID_PARAM
    assert any("\u4e00" <= ch <= "\u9fff" for ch in exc.value.message)

    with pytest.raises(ApiError):
        PageParams.as_dependency(page=0, page_size=20)


def test_page_data_of_keeps_page_and_size() -> None:
    from app.core.pagination import PageData, PageParams

    params = PageParams(page=2, page_size=5)
    data = PageData[int].of([1, 2, 3], total=13, params=params)
    assert (data.page, data.page_size, data.total) == (2, 5, 13)
