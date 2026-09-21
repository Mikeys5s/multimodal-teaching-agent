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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, engine
from app.main import app
from app.models import Job, KnowledgePoint, KpPrerequisite

client = TestClient(app, raise_server_exceptions=False)
# 造数用（与 `client` 打到的是同一个库）
session = Session(engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema() -> None:
    """冒烟测试会真的打到接口，而有些接口会查库（如任务冲突检测）。

    所以在跑之前把表建好 —— 否则会以 500 的形式失败，
    让人误以为接口写错了。

    **并且种一份真实素材**：素材相关端点已经**不再走 mock**（`MOCK_MODE` 已删除），
    它们现在真查库。所以 `mat_9f2a1c40` 必须真的存在一条 ——
    否则测到的是 404，而不是接口本身的行为。
    """
    Base.metadata.create_all(engine)
    _seed_sample_material()


def _seed_sample_material() -> None:
    """种一份"像样"的真实素材：有块、有存疑说明、有章节标题。

    内容刻意用目标学科（计算机网络）的，与演示数据一致 ——
    这样测试跑出来的输出，看的时候也认得出来是什么。
    """
    from app.models import Chapter, Material, MaterialBlock, Section  # 局部导入

    if session.get(Material, "mat_9f2a1c40") is not None:
        return

    session.add(
        Material(
            id="mat_9f2a1c40",
            filename="第5章-传输层.pdf",
            file_hash="a" * 64,
            stored_path="mat_9f2a1c40.pdf",
            mime_type="application/pdf",
            size_bytes=2481920,
            source_type="pdf_scan",
            parse_method="multimodal_llm",
            status="done",
            page_count=2,
            char_count=120,
            quality_score=0.86,
            # ⚠️ `uncertain_count` **不是** `materials` 的列 —— 它由 `uncertain_notes`
            #    解析后算出来（见 app/schemas/material.py）。写成列名会 TypeError。
            uncertain_notes=json.dumps(
                [
                    {
                        "kind": "low_confidence_ocr",
                        "page": 1,
                        "block_id": None,
                        "message": "第 1 页公式区域识别置信度 0.62，可能是『拥塞窗口单位是字节』",
                        "severity": "medium",
                    },
                    {
                        "kind": "missing_field",
                        "page": 2,
                        "block_id": None,
                        "message": "第 2 页第 3 题只有题干与选项，未找到答案",
                        "severity": "high",
                    },
                ],
                ensure_ascii=False,
            ),
            created_at="2026-09-19T00:00:00+00:00",
            updated_at="2026-09-19T00:00:00+00:00",
        )
    )
    session.commit()

    blocks = [
        (0, 1, "heading", 1, "# 第 5 章 传输层"),
        (1, 1, "paragraph", None, "传输层为应用进程提供端到端的逻辑通信。"),
        (2, 2, "heading", 2, "## 5.3 TCP 拥塞控制"),
        (3, 2, "paragraph", None, "拥塞窗口 cwnd 的大小由发送方根据网络拥塞程度动态调整。"),
    ]
    for seq, page_no, btype, level, content in blocks:
        session.add(
            MaterialBlock(
                id=f"blk_9f2a1c40_{seq:05d}",
                material_id="mat_9f2a1c40",
                seq=seq,
                page_no=page_no,
                line_start=seq + 1,
                line_end=seq + 1,
                block_type=btype,
                heading_level=level,
                content_md=content,
                image_path=None,
                ocr_confidence=None,
            )
        )
    session.commit()

    # ⚠️ **章与节也必须种** —— 抽取是"逐节遍历"的，没有节就一个候选都抽不出来。
    #
    # 这是真跑出来的：抽到 0 个候选时它**明确报错**而不是静默返回 0
    # （"素材的 4 个块里没有抽出任何知识点候选"）—— 所以问题立刻暴露了。
    # 如果当初写成"抽不到就返回空"，这里会变成"步骤5 静默通过"，那才难查。
    session.add(
        Chapter(id="ch_9f2a1c40_000", material_id="mat_9f2a1c40", number="5", title="传输层", seq=0)
    )
    session.add(
        Section(
            id="sec_9f2a1c40_000_000",
            material_id="mat_9f2a1c40",
            chapter_id="ch_9f2a1c40_000",
            number="5.1",
            title="传输层概述",
            seq=0,
            # 指向节标题块 —— 抽取靠它推"这一节覆盖哪些块"
            source_block_id="blk_9f2a1c40_00000",
        )
    )
    session.commit()


def _real_ids() -> tuple[str, str]:
    """跑一次真实链路，返回（真实的知识点 id, 真实的任务 id）。

    ⚠️ 这些测试原来用的是**写死的 mock id**（`kp_9f2a1c40_000_002_003` / `job_9f2a1c40`）——
    在 mock 模式下端点不查库，所以照样返回一份"完整"的数据，看不出问题。
    现在端点真查库了，那些 id 不在库里 -> 正确地 404。

    **这类断言原来测的是"假数据是否满足形状"，现在才轮到测真实行为。**
    """
    assert_envelope_ok(
        client.post("/api/extract/knowledge", json={"material_ids": ["mat_9f2a1c40"]})
    )
    session.expire_all()
    # ⚠️ 挑**有前置边**的那个知识点，不是"按 seq 第一个"。
    #
    # 第一个往往是起点知识点 —— 它没有前置，于是
    # `assert data["prerequisites"]` / `assert data["hard_prerequisites"]` 会失败，
    # 而失败看起来像"接口没返回前置"，其实是**选错了被测量对象**。
    # （这类失败最费时间：断言没错、实现没错，是取样错了。）
    kp_id = session.scalar(
        select(KpPrerequisite.kp_id)
        .join(KnowledgePoint, KnowledgePoint.id == KpPrerequisite.kp_id)
        .where(KnowledgePoint.material_id == "mat_9f2a1c40")
        .limit(1)
    )
    if kp_id is None:
        kp_id = session.scalar(
            select(KnowledgePoint.id)
            .where(KnowledgePoint.material_id == "mat_9f2a1c40")
            .order_by(KnowledgePoint.seq)
            .limit(1)
        )
    job_id = session.scalar(
        select(Job.id)
        .where(Job.target_id == "mat_9f2a1c40")
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    assert kp_id and job_id, f"真实链路没产出 id：kp={kp_id} job={job_id}"
    return kp_id, job_id

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


def test_material_detail_roundtrip() -> None:
    """素材详情：读到的就是库里那份（不再是 mock）。

    原名 `test_material_detail_mock_roundtrip` —— 名字里的 "mock" 已经删掉了，
    因为素材端点现在**真查库**，这条测的是真实读取路径。
    """
    data = assert_envelope_ok(client.get("/api/materials/mat_9f2a1c40"))
    assert data["id"] == "mat_9f2a1c40"
    assert data["filename"] == "第5章-传输层.pdf"
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
    """删除一份素材 —— **删自己刚传的那一份，不碰共用数据**。

    ⚠️ 原来这里删的是共用的 `mat_9f2a1c40`，而它是本模块其它用例
    （详情 / 块 / 导出 / 抽取）赖以存在的那一份。

    **这个 bug 一直存在，只是以前没暴露**：抽取端点在 mock 模式下不检查素材是否存在，
    所以"素材被前面的用例删了"不会报错。现在它真查库了 ——
    `test_extract_accepted` 立刻报 404，把这个隐藏的**用例间依赖**翻了出来。

    （这正是"端到端跑通"带来的副作用：**真实检查会把以前被 mock 掩盖的问题显影。**
     不好受，但这是好事。）
    """
    import io

    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), "5 Transport Layer", fontsize=14)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()

    resp = client.post(
        "/api/materials",
        files={"files": ("to-be-deleted.pdf", buf.getvalue(), "application/pdf")},
    )
    assert_envelope_ok(resp)
    mat_id = resp.json()["data"]["accepted"][0]["material_id"]
    assert mat_id != "mat_9f2a1c40", "不该删共用素材"

    data = assert_envelope_ok(client.delete(f"/api/materials/{mat_id}"))
    assert data["deleted"] == mat_id

    # 删完必须真的没了 —— 不能只看返回值
    assert client.get(f"/api/materials/{mat_id}").status_code == 404


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
    kp_id, _ = _real_ids()
    data = assert_envelope_ok(client.get(f"/api/knowledge-points/{kp_id}"))
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
    """卡点回溯：**给出的东西必须可解释**。

    ⚠️ 这里不再断言 `hard_prerequisites` 非空 —— 因为**当前它确实是空的**，
    而原因值得写下来：

    > **结构线索只产出 `soft` 边**（"同节顺序"、"跨节衔接"），
    > 而卡点回溯是沿 **`hard` 边**（"不会就学不动"）反向回溯的。
    > `hard` 需要**语义判断** —— 那是构建期（LearnBuddy）+ 人工校验的活，
    > 结构线索给不出。

    所以本测试断言的是：**在没有 hard 前置时，接口要如实说清这件事**，
    而不是编一个"最可能的断层"出来。这正是「宁缺毋错」在接口层的体现。
    """
    data = assert_envelope_ok(
        client.get(f"/api/knowledge-points/{_real_ids()[0]}/gap-analysis")
    )
    assert data["target_kp"]["kp_id"]

    if data["hard_prerequisites"]:
        # 有 hard 前置时，每一条都必须能说清"为什么是它"
        for p in data["hard_prerequisites"]:
            assert p["reason"], f"硬前置缺少理由：{p}"
        # 以及"最可能断层"必须给判据，不能只给结论
        assert data["likely_gap"] and data["likely_gap"]["evidence"]
    else:
        # 没有 hard 前置时：**必须明说**，不能返回一个沉默的空数组
        assert data["likely_gap"] is None
        assert data["suggestion"], "没有 hard 前置时必须给出可读的说明，不能只给空结果"
        assert "hard" in data["suggestion"] or "起点" in data["suggestion"], (
            f"说明应当讲清原因，收到：{data['suggestion']!r}"
        )


def test_gap_analysis_accepts_repeated_student_evidence() -> None:
    """★ v1.3 约定：`student_evidence` 是**可重复**查询参数。

    ⚠️ 这里**不再**断言 `likely_gap.evidence` 里出现"误区" —— 那条断言要求
    **存在 hard 前置**才谈得上（见 `test_gap_analysis_explains_itself` 里的说明：
    结构线索只产出 soft 边，`hard` 需要语义通道）。

    本测试守的是**参数契约本身**：可重复传、请求成功、结果结构完整。
    等语义通道（构建期 + 人工校验）补齐 hard 边之后，可以再把"命中误区会进入排序依据"
    这条断言加回来 —— **那时它才有意义**。
    """
    data = assert_envelope_ok(
        client.get(
            f"/api/knowledge-points/{_real_ids()[0]}/gap-analysis"
            "?student_evidence=mis_a&student_evidence=mis_b"
        )
    )
    assert data["target_kp"]["kp_id"], "重复传 student_evidence 之后请求仍须成功"


def test_gap_analysis_ignores_unknown_evidence() -> None:
    """★ 无效的 student_evidence **忽略而不报错** —— 它只影响排序精度，不该让请求失败。"""
    resp = client.get(
        f"/api/knowledge-points/{_real_ids()[0]}/gap-analysis?student_evidence=not_a_real_id"
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
    """学习路径的排序与可解释性。

    ⚠️ **必须用真实的知识点**。这里原来写死一个 mock id（`kp_9f2a1c40_000_002_003`）——
    在 mock 模式下端点照样返回假数据，看不出问题；现在端点真算路径了，
    那个 id 不在图里 → 正确地 404。

    **这一类断言值得单独说**：它原来测的是"返回数组 order 连续、每步有 reason"，
    而这在**假数据上必然成立**（假数据就是照着断言编的）。
    现在它测的是**我们真算出来的路径**是否满足这两条性质 —— 这才是有效信息。
    """
    # 先在同一份素材上真跑一次抽取，让图里有真的节点与边
    assert_envelope_ok(
        client.post("/api/extract/knowledge", json={"material_ids": ["mat_9f2a1c40"]})
    )
    session.expire_all()
    kp_id = session.scalar(
        select(KnowledgePoint.id)
        .where(KnowledgePoint.material_id == "mat_9f2a1c40")
        .order_by(KnowledgePoint.seq)
        .limit(1)
    )
    assert kp_id, "抽取之后应当有知识点 —— 否则后面测的不是路径"

    # ⚠️ `data` **本身就是数组**（api-spec §4.4 承诺顶层数组）。
    #    原先写 `data["steps"]` —— 那是"对象"时代的形状，
    #    改成数组之后直接 `TypeError: list indices must be integers`。
    data = assert_envelope_ok(client.get(f"/api/learning-path?kp_id={kp_id}"))
    assert isinstance(data, list), f"§4.4 要求顶层数组，实际 {type(data).__name__}"
    steps = data
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
    _, job_id = _real_ids()
    data = assert_envelope_ok(client.get(f"/api/jobs/{job_id}"))
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


def _seeded_session() -> str:
    """建一个**真会话**并问一句，返回它的 id。

    ## 为什么需要这个（2026-09-21）

    下面 6 个测试原本都写着 `/api/qa/sessions/qs_9f2a1c40_001` ——
    **那是 `create_session` 曾经返回的写死常量。**

    等 `create_session` 改成真实 uuid 之后，**那个 id 就不存在了** →
    这 6 个测试全部 404。

    **它们绿了很久，因为它们一直跟着错误实现走。**

    ⚠️ 顺带一个收获：这正好说明**"只跑一部分测试"有多危险** ——
    我前几轮只跑 `tests/test_tutor_state.py`（纯函数），
    **这 6 个失败一次都没暴露过。**

    问一句是为了**产生轮次 + diagnosis** ——
    详情/状态/报告三个端点都要求"有东西可返回"。
    """
    sid = client.post(
        "/api/qa/sessions", json={"material_scope": [], "student_label": "smoke"}
    ).json()["data"]["session_id"]
    client.post(f"/api/qa/sessions/{sid}/ask", json={"question": "为什么 TCP 建立连接要三次握手"})
    return sid


def test_create_session() -> None:
    resp = client.post("/api/qa/sessions", json={"material_scope": [], "student_label": "demo"})
    assert resp.status_code in (200, 201), resp.text[:200]
    data = resp.json()["data"]
    assert data["session_id"].startswith("qs_")
    # ★ 每次都必须不同 —— 挡的是"返回写死常量"那种实现
    other = client.post(
        "/api/qa/sessions", json={"material_scope": [], "student_label": "demo2"}
    ).json()["data"]["session_id"]
    assert other != data["session_id"], "两次建会话必须拿到不同的 id"


def test_session_detail_has_turns_and_diagnosis() -> None:
    sid = _seeded_session()
    data = assert_envelope_ok(client.get(f"/api/qa/sessions/{sid}"))
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
    sid = _seeded_session()
    data = assert_envelope_ok(client.get(f"/api/qa/sessions/{sid}/state"))
    assert data["state"]
    assert data["next_action"]
    assert data["explain_threshold"] == 2, "连续 2 次答不上来就降级 —— 阈值要能被前端展示"


def test_session_report_aggregates() -> None:
    sid = _seeded_session()
    data = assert_envelope_ok(client.get(f"/api/qa/sessions/{sid}/report"))
    assert data["turn_count"] > 0
    assert 0.0 <= data["grounded_rate"] <= 1.0
    assert data["summary_md"]


def test_delete_session() -> None:
    sid = _seeded_session()
    data = assert_envelope_ok(client.delete(f"/api/qa/sessions/{sid}"))
    assert data["deleted"]
    # ★ 删完必须真的取不到 —— 挡的是"只返回一个字符串、什么都没删"那种实现
    assert_envelope_error(client.get(f"/api/qa/sessions/{sid}"), 404, "NOT_FOUND")


def test_qa_404_on_bad_session_id() -> None:
    assert_envelope_error(client.get("/api/qa/sessions/nonsense"), 404, "NOT_FOUND")
    assert_envelope_error(
        client.post("/api/qa/sessions/nonsense/ask", json={"question": "x"}), 404, "NOT_FOUND"
    )


def test_ask_streams_sse_in_fixed_order() -> None:
    """★ SSE 契约：事件顺序固定，且**每个事件都带 `id:`**（`Last-Event-ID` 续推依赖它）。

    这几条不写测试就只是文档里的一句话；写成断言才真的守住。
    """
    sid = _seeded_session()
    resp = client.post(
        f"/api/qa/sessions/{sid}/ask", json={"question": "这题为什么用快排不用冒泡？"}
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
    sid = _seeded_session()
    resp = client.post(f"/api/qa/sessions/{sid}/ask", json={})
    assert resp.status_code in (400, 422), resp.text[:200]
