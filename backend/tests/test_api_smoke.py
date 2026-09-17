"""接口冒烟测试（归属：P2）。

`test_api_contract.py` 守的是「**端点集合对不对**」；
本文件守的是「**每个端点真的能按约定应答**」—— 两者互补。

逐端点检查四件事：
  1. **可达**（不是 404 / 405 / 500）
  2. **包封**（成功是 `{ok, data, request_id}`，失败是 `{ok:false, error, request_id}`）
  3. **错误码**（参数越界 400、资源不存在 404、任务冲突 409、受理 202）
  4. **`error.message` 是中文** —— 规格明确要求它能直接展示给用户

为什么要写这个：接口冻结的**真正价值在错误分支上**。
正常路径 P3 一眼看得懂，但"参数越界返回什么""id 不存在返回什么"
才是前后端最容易对不齐的地方 —— 而这些恰恰是普通单元测试覆盖不到的。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema() -> None:
    """冒烟测试会真的打到接口，而有些接口会查库（如任务冲突检测）。

    所以在跑之前把表建好 —— 否则会以 500 的形式失败，
    让人误以为接口写错了。
    """
    Base.metadata.create_all(engine)


def _has_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def assert_envelope_ok(resp) -> dict:
    """成功的统一结构：{ok: true, data: ..., request_id: ...}"""
    assert resp.status_code in (200, 201, 202), f"{resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert body.get("ok") is True, body
    assert "data" in body, body
    assert body.get("request_id"), "缺少 request_id"
    return body["data"]


def assert_envelope_error(resp, status: int, code: str) -> dict:
    """失败的统一结构：{ok: false, error: {code, message}, request_id}"""
    assert resp.status_code == status, f"期望 {status}，实际 {resp.status_code}：{resp.text[:200]}"
    body = resp.json()
    assert body.get("ok") is False, body
    err = body.get("error") or {}
    assert err.get("code") == code, f"期望错误码 {code}，实际 {err.get('code')}"
    message = err.get("message") or ""
    assert message, "error.message 不能为空"
    assert _has_chinese(message), f"error.message 必须是中文，实际：{message!r}"
    assert body.get("request_id"), "错误响应也要带 request_id"
    return err


# ---------------------------------------------------------------------------
# 1. 基础端点
# ---------------------------------------------------------------------------


def test_health() -> None:
    data = assert_envelope_ok(client.get("/api/health"))
    assert data["status"] in ("ok", "degraded")
    assert "db" in data and "version" in data


def test_health_pragma_reports_foreign_keys() -> None:
    """★ 这条顺带守住"外键真的开着" —— 它坏掉时症状是数据静默变脏，不是报错。"""
    data = assert_envelope_ok(client.get("/api/health/pragma"))
    assert data["pragmas"]["foreign_keys"] == "1", "外键没生效！"
    assert data["db_file"]


def test_capabilities() -> None:
    data = assert_envelope_ok(client.get("/api/meta/capabilities"))
    assert ".pdf" in data["supported_material_types"]
    assert data["max_upload_mb"] > 0
    assert data["llm_mode"] == "not_in_use"


# ---------------------------------------------------------------------------
# 2. 素材组（端点 4–12）
# ---------------------------------------------------------------------------


def test_upload_accepts_supported_and_rejects_others() -> None:
    """★ 契约核心：**部分文件被拒绝时仍返回 202**，且给可读原因 —— 不得整批失败。"""
    resp = client.post(
        "/api/materials",
        files=[
            ("files", ("第5章.pdf", b"%PDF-1.7 ok", "application/pdf")),
            ("files", ("笔记.pages", b"whatever", "application/octet-stream")),
        ],
    )
    assert resp.status_code == 202, resp.text[:200]
    data = resp.json()["data"]

    assert len(data["accepted"]) == 1, "PDF 应该被接收"
    assert data["accepted"][0]["filename"] == "第5章.pdf"
    assert data["accepted"][0]["material_id"].startswith("mat_")
    assert data["accepted"][0]["job_id"].startswith("job_")

    assert len(data["rejected"]) == 1, "pages 应该被拒绝"
    rej = data["rejected"][0]
    assert rej["filename"] == "笔记.pages"
    assert _has_chinese(rej["reason"]), f"拒绝原因必须是中文：{rej['reason']!r}"


def test_upload_id_is_content_addressed() -> None:
    """★ 同一份文件重复上传必须得到**同一个 material_id** —— 成本控制 C2 的基础。"""
    payload = b"%PDF-1.7 identical content"
    r1 = client.post("/api/materials", files=[("files", ("a.pdf", payload, "application/pdf"))])
    r2 = client.post("/api/materials", files=[("files", ("b.pdf", payload, "application/pdf"))])
    id1 = r1.json()["data"]["accepted"][0]["material_id"]
    id2 = r2.json()["data"]["accepted"][0]["material_id"]
    assert id1 == id2, "内容相同却生成了不同的 material_id —— 确定性 ID 被破坏了"


def test_upload_without_files_is_400() -> None:
    resp = client.post("/api/materials", files=[])
    assert resp.status_code in (400, 422), resp.text[:200]


def test_materials_list_pagination_defaults() -> None:
    data = assert_envelope_ok(client.get("/api/materials"))
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert isinstance(data["items"], list)


def test_materials_list_rejects_bad_status() -> None:
    err = assert_envelope_error(client.get("/api/materials?status=finished"), 400, "INVALID_PARAM")
    assert "allowed" in (err.get("detail") or {}), "非法取值应告知允许的取值"


@pytest.mark.parametrize(
    "query",
    ["page=0", "page=-1", "page_size=0", "page_size=101", "page_size=999"],
)
def test_materials_list_rejects_out_of_range_pagination(query: str) -> None:
    """★ 分页越界必须 400 且是中文 —— 不静默夹取（夹取会让调用方以为拿到了全部数据）。"""
    assert_envelope_error(client.get(f"/api/materials?{query}"), 400, "INVALID_PARAM")


def test_material_detail_mock_roundtrip() -> None:
    data = assert_envelope_ok(client.get("/api/materials/mat_9f2a1c40"))
    assert data["id"] == "mat_9f2a1c40"
    assert data["uncertain_count"] == len(data["uncertain_notes"])
    # 存疑处必须能给出可读说明 —— 「显式不确定性」的对外体现
    for note in data["uncertain_notes"]:
        assert note["message"] and _has_chinese(note["message"])


def test_material_detail_404_on_bad_id() -> None:
    assert_envelope_error(client.get("/api/materials/nonsense"), 404, "NOT_FOUND")


def test_material_blocks_and_filters() -> None:
    data = assert_envelope_ok(client.get("/api/materials/mat_9f2a1c40/blocks"))
    assert isinstance(data, list) and data
    assert {"id", "seq", "block_type", "content_md"} <= set(data[0])

    only_headings = assert_envelope_ok(
        client.get("/api/materials/mat_9f2a1c40/blocks?block_type=heading")
    )
    assert all(b["block_type"] == "heading" for b in only_headings)


def test_material_blocks_rejects_bad_block_type() -> None:
    assert_envelope_error(
        client.get("/api/materials/mat_9f2a1c40/blocks?block_type=vibes"),
        400,
        "INVALID_PARAM",
    )


def test_markdown_is_non_json_with_request_id_header() -> None:
    """★ 非 JSON 响应约定：内容原样返回，**请求标识走 X-Request-ID 响应头**。"""
    resp = client.get("/api/materials/mat_9f2a1c40/markdown")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.headers.get("x-request-id"), "非 JSON 响应必须带 X-Request-ID 头"
    assert "# 第 5 章" in resp.text


def test_outline_shape() -> None:
    data = assert_envelope_ok(client.get("/api/materials/mat_9f2a1c40/outline"))
    assert data["material_id"] == "mat_9f2a1c40"
    assert data["chapters"] and data["chapters"][0]["sections"]


def test_questions_marks_missing_answers() -> None:
    """★ `answer_missing=true` 是「存疑处」的对外体现，不能伪装成完整数据。"""
    data = assert_envelope_ok(client.get("/api/materials/mat_9f2a1c40/questions"))
    assert data
    missing = [q for q in data if q["answer_missing"]]
    assert missing, "样例里应包含一道材料未给答案的题"
    for q in missing:
        assert q["answer_md"] is None, "标了缺失就不能同时有答案"


def test_reparse_returns_202() -> None:
    data = assert_envelope_ok(client.post("/api/materials/mat_9f2a1c40/reparse"))
    assert data["job_id"].startswith("job_")


def test_reparse_404_on_bad_id() -> None:
    assert_envelope_error(client.post("/api/materials/nonsense/reparse"), 404, "NOT_FOUND")


def test_delete_material() -> None:
    data = assert_envelope_ok(client.delete("/api/materials/mat_9f2a1c40"))
    assert data["deleted"] == "mat_9f2a1c40"


# ---------------------------------------------------------------------------
# 3. 抽取 / 知识点（端点 13–15、28）
# ---------------------------------------------------------------------------


def test_extract_requires_material_ids() -> None:
    resp = client.post("/api/extract/knowledge", json={"material_ids": []})
    assert resp.status_code in (400, 422), resp.text[:200]


def test_extract_accepted() -> None:
    data = assert_envelope_ok(
        client.post("/api/extract/knowledge", json={"material_ids": ["mat_9f2a1c40"]})
    )
    assert data["job_id"]
    assert data["estimated_seconds"] > 0


def test_kp_list_and_filters() -> None:
    data = assert_envelope_ok(client.get("/api/knowledge-points"))
    assert data["page"] == 1 and data["page_size"] == 20

    data = assert_envelope_ok(client.get("/api/knowledge-points?difficulty_min=2&difficulty_max=4"))
    assert isinstance(data["items"], list)


@pytest.mark.parametrize(
    "query",
    [
        "difficulty_min=0",
        "difficulty_max=9",
        "kp_type=vibes",
        "needs_review=1",  # v1.3 明确只接受布尔，不静默兼容 0/1
        "difficulty_min=5&difficulty_max=2",
    ],
)
def test_kp_list_rejects_invalid_params(query: str) -> None:
    assert_envelope_error(client.get(f"/api/knowledge-points?{query}"), 400, "INVALID_PARAM")


def test_kp_list_accepts_boolean_needs_review() -> None:
    for value in ("true", "false"):
        assert_envelope_ok(client.get(f"/api/knowledge-points?needs_review={value}"))


def test_kp_detail_has_explainable_prerequisites() -> None:
    """★ 支柱：`reason` 必须非空 —— 「为什么这个要排在前面」要能逐条说清。"""
    data = assert_envelope_ok(client.get("/api/knowledge-points/kp_9f2a1c40_000_002_003"))
    assert data["prerequisites"], "样例应含前置依赖"
    for p in data["prerequisites"]:
        assert p["reason"], f"依赖边缺少理由：{p}"
        assert p["relation_type"] in ("hard", "soft")
    # 溯源同样非空 —— A2-3 的对外体现
    assert data["source"]["quote"]
    assert data["source"]["material_name"]


def test_kp_detail_404() -> None:
    assert_envelope_error(client.get("/api/knowledge-points/nonsense"), 404, "NOT_FOUND")


def test_gap_analysis_explains_itself() -> None:
    data = assert_envelope_ok(
        client.get("/api/knowledge-points/kp_9f2a1c40_000_002_003/gap-analysis")
    )
    assert data["target_kp"]["kp_id"]
    assert data["hard_prerequisites"], "应给出硬前置链"
    assert data["likely_gap"]["evidence"], "断层判断必须给出判据，不能只给结论"
    assert "第 88 页" in data["suggestion"] or "88" in data["suggestion"], (
        "建议里应给出可执行的页码指引"
    )


def test_gap_analysis_accepts_repeated_student_evidence() -> None:
    """★ v1.3 约定：`student_evidence` 是**可重复**查询参数。"""
    data = assert_envelope_ok(
        client.get(
            "/api/knowledge-points/kp_9f2a1c40_000_002_003/gap-analysis"
            "?student_evidence=mis_a&student_evidence=mis_b"
        )
    )
    assert "误区" in data["likely_gap"]["evidence"]


def test_gap_analysis_ignores_unknown_evidence() -> None:
    """★ 无效的 student_evidence **忽略而不报错** —— 它只影响排序精度，不该让请求失败。"""
    resp = client.get(
        "/api/knowledge-points/kp_9f2a1c40_000_002_003/gap-analysis?student_evidence=not_a_real_id"
    )
    assert_envelope_ok(resp)


# ---------------------------------------------------------------------------
# 4. 图谱 / 路径（端点 16、17）
# ---------------------------------------------------------------------------


def test_graph_stats_expose_engineering_invariants() -> None:
    """★ 这几个数字是给评委看的 —— 不只是内部调试信息。"""
    data = assert_envelope_ok(client.get("/api/knowledge-graph"))
    stats = data["stats"]
    assert stats["cycle_count"] == 0, "依赖图必须无环（工程不变量）"
    # 「检出并剪除了 N 条成环边」比只报「环数 0」更有说服力
    assert stats["pruned_count"] >= 0
    assert "conflict_count" in stats
    for e in data["edges"]:
        assert e["relation_type"] in ("hard", "soft")


def test_graph_max_nodes_limits_result() -> None:
    data = assert_envelope_ok(client.get("/api/knowledge-graph?max_nodes=1"))
    assert len(data["nodes"]) <= 1


def test_graph_rejects_bad_max_nodes() -> None:
    assert_envelope_error(client.get("/api/knowledge-graph?max_nodes=0"), 400, "INVALID_PARAM")


def test_learning_path_is_ordered_and_explainable() -> None:
    data = assert_envelope_ok(client.get("/api/learning-path?kp_id=kp_9f2a1c40_000_002_003"))
    steps = data["steps"]
    assert steps
    assert [s["order"] for s in steps] == list(range(1, len(steps) + 1)), "order 必须连续"
    assert steps[0]["is_start_point"] is True and steps[0]["reason"] is None
    # 除起点外，每一步都要有理由 —— 否则学习路径就成了黑盒拓扑排序
    for s in steps[1:]:
        assert s["reason"], f"第 {s['order']} 步缺少理由"


def test_learning_path_requires_kp_id() -> None:
    resp = client.get("/api/learning-path")
    assert resp.status_code in (400, 422), resp.text[:200]


# ---------------------------------------------------------------------------
# 5. 报告 / 导出 / 任务（端点 18、19、26、27）
# ---------------------------------------------------------------------------


def test_quality_report_covers_all_four_sections() -> None:
    data = assert_envelope_ok(client.get("/api/report/quality"))
    assert {"materials", "knowledge_points", "graph", "qa"} <= set(data)
    kp = data["knowledge_points"]
    assert kp["structure_complete_rate"] <= 1.0
    assert kp["grounding_rate"] <= 1.0
    assert data["graph"]["cycle_count"] == 0
    # 拒答次数要能被单独统计 —— 拒答是能力，不是缺陷
    assert "refuse_count" in data["qa"]


def test_export_csv_has_provenance_columns() -> None:
    """★ 导出必须含溯源列，否则没法用 Excel 逐条核对。"""
    resp = client.get("/api/export/knowledge-points?format=csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.headers.get("x-request-id")
    header = resp.text.splitlines()[0]
    for col in ("id", "name", "difficulty", "source_quote", "source_page"):
        assert col in header, f"CSV 缺少列 {col}"


def test_export_json_is_enveloped() -> None:
    resp = client.get("/api/export/knowledge-points?format=json")
    assert resp.status_code == 200
    body = json.loads(resp.text)
    assert body["ok"] is True and isinstance(body["data"], list)


def test_export_rejects_bad_format() -> None:
    resp = client.get("/api/export/knowledge-points?format=xml")
    assert resp.status_code in (400, 422), resp.text[:200]


def test_job_detail_has_readable_stage_detail() -> None:
    """★ `stage_detail` 是给用户看的中文进度，前端直接展示、不加工。"""
    data = assert_envelope_ok(client.get("/api/jobs/job_9f2a1c40"))
    assert 0 <= data["progress"] <= 100
    assert _has_chinese(data["stage_detail"]), f"stage_detail 必须是中文：{data['stage_detail']!r}"


def test_job_list_filters() -> None:
    data = assert_envelope_ok(client.get("/api/jobs"))
    assert "items" in data and "total" in data
    assert_envelope_ok(client.get("/api/jobs?job_type=parse"))
    assert_envelope_error(client.get("/api/jobs?job_type=explode"), 400, "INVALID_PARAM")


def test_job_404() -> None:
    assert_envelope_error(client.get("/api/jobs/nonsense"), 404, "NOT_FOUND")


# ---------------------------------------------------------------------------
# 6. 答疑（端点 20–25）—— 含 SSE
# ---------------------------------------------------------------------------


def test_create_session() -> None:
    resp = client.post("/api/qa/sessions", json={"material_scope": [], "student_label": "demo"})
    assert resp.status_code in (200, 201), resp.text[:200]
    data = resp.json()["data"]
    assert data["session_id"].startswith("qs_")


def test_session_detail_has_turns_and_diagnosis() -> None:
    data = assert_envelope_ok(client.get("/api/qa/sessions/qs_9f2a1c40_001"))
    assert data["turns"]
    tutor_turns = [t for t in data["turns"] if t["role"] == "tutor"]
    assert tutor_turns, "会话里应有导师轮次"
    # 每轮答疑必须输出三件事
    diag = tutor_turns[0]["diagnosis"]
    assert diag is not None
    assert {"knowledge_points", "stuck_at", "next_practice"} <= set(diag)
    assert diag["stuck_at"]["step"]


def test_session_state_exposes_socratic_machine() -> None:
    """★ 把"看不见的引导逻辑"暴露成接口 —— 让评委看得见策略的存在。"""
    data = assert_envelope_ok(client.get("/api/qa/sessions/qs_9f2a1c40_001/state"))
    assert data["state"]
    assert data["next_action"]
    assert data["explain_threshold"] == 2, "连续 2 次答不上来就降级 —— 阈值要能被前端展示"


def test_session_report_aggregates() -> None:
    data = assert_envelope_ok(client.get("/api/qa/sessions/qs_9f2a1c40_001/report"))
    assert data["turn_count"] > 0
    assert 0.0 <= data["grounded_rate"] <= 1.0
    assert data["summary_md"]


def test_delete_session() -> None:
    data = assert_envelope_ok(client.delete("/api/qa/sessions/qs_9f2a1c40_001"))
    assert data["deleted"]


def test_qa_404_on_bad_session_id() -> None:
    assert_envelope_error(client.get("/api/qa/sessions/nonsense"), 404, "NOT_FOUND")
    assert_envelope_error(
        client.post("/api/qa/sessions/nonsense/ask", json={"question": "x"}), 404, "NOT_FOUND"
    )


def test_ask_streams_sse_in_fixed_order() -> None:
    """★ SSE 契约：事件顺序固定，且**每个事件都带 `id:`**（`Last-Event-ID` 续推依赖它）。

    这几条不写测试就只是文档里的一句话；写成断言才真的守住。
    """
    resp = client.post(
        "/api/qa/sessions/qs_9f2a1c40_001/ask", json={"question": "这题为什么用快排不用冒泡？"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    raw = resp.text
    events = []
    ids = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        name = None
        ev_id = None
        data_line = None
        for line in block.splitlines():
            if line.startswith("id: "):
                ev_id = line[4:]
            elif line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data_line = line[6:]
        assert name, f"SSE 块缺少 event 行：{block[:80]!r}"
        assert ev_id is not None, f"★ 事件 {name} 缺少 id 行 —— Last-Event-ID 无法工作"
        assert data_line, f"事件 {name} 缺少 data 行"
        payload = json.loads(data_line)
        assert "seq" in payload, f"事件 {name} 的 data 里缺少 seq"
        assert str(payload["seq"]) == ev_id, f"id 行({ev_id}) 与 data.seq({payload['seq']}) 不一致"
        events.append(name)
        ids.append(int(ev_id))

    assert events[0] == "retrieved", "retrieved 必须是第一个事件（前端据此先渲染溯源卡片）"
    assert events[-1] == "done"
    assert "state" in events and "delta" in events and "diagnosis" in events
    assert ids == sorted(ids), f"seq 必须单调递增：{ids}"

    idx_retrieved = events.index("retrieved")
    idx_first_delta = events.index("delta")
    assert idx_retrieved < idx_first_delta, "★ retrieved 必须先于任何 delta"


def test_ask_requires_question() -> None:
    resp = client.post("/api/qa/sessions/qs_9f2a1c40_001/ask", json={})
    assert resp.status_code in (400, 422), resp.text[:200]
