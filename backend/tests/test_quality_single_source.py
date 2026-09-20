"""质量报告：**端点与 CLI 必须同源**。

## 这个文件存在的理由

`GET /api/report/quality` 曾经返回一整块**写死的 mock**
（`total=184` / `edge_count=267` / `structure_complete_rate=1.0`…），
而 `scripts/evaluate.py` 从数据库**真算**一遍。

**两套数字一定会分叉，而且分叉了不报错** ——
报告页给评委看的数字，和验收时跑出来的数字不一致，答辩现场解释不清。

本文件的测试就是钉住"**它们现在是同一个来源**"这件事。
**尤其注意 `test_endpoint_is_not_hardcoded`** ——
它专门用来防止"哪天有人又把数字写回去"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in (str(REPO_ROOT / "backend"), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Chapter,
    KnowledgePoint,
    KpPrerequisite,
    Material,
    Section,
    utc_now_iso,
)
from app.quality import check_acceptance, compute  # noqa: E402

# ---------------------------------------------------------------------------
# 造数（与 test_evaluate.py 同一套写法，故意的 —— 两边测的是同一份计算）
# ---------------------------------------------------------------------------


def _material(session: Session, mid: str = "mat_a") -> None:
    session.add(
        Material(
            id=mid,
            filename="第5章.pdf",
            file_hash=mid.ljust(64, "0")[:64],
            stored_path="x.pdf",
            mime_type="application/pdf",
            size_bytes=1,
            source_type="pdf_text",
            status="done",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
    )
    session.commit()


def _kp(session: Session, kp_id: str, name: str) -> None:
    """建一条完整的归属链：材料 → 章 → 节 → 知识点。"""
    if session.get(Material, "mat_a") is None:
        _material(session)
    if session.get(Chapter, "ch_a") is None:
        session.add(Chapter(id="ch_a", material_id="mat_a", title="传输层", seq=0))
        session.commit()
    if session.get(Section, "sec_a") is None:
        session.add(
            Section(id="sec_a", material_id="mat_a", chapter_id="ch_a", title="可靠传输", seq=0)
        )
        session.commit()
    session.add(
        KnowledgePoint(
            id=kp_id,
            section_id="sec_a",
            chapter_id="ch_a",
            material_id="mat_a",
            name=name,
            summary_md="说明",
            difficulty=3,
            kp_type="concept",
            source_material_id="mat_a",
            source_quote="原文片段",
            seq=0,
            created_at=utc_now_iso(),
        )
    )
    session.commit()


def _edge(session: Session, prereq: str, kp: str, reason: str = "不学懂前置会卡住") -> None:
    session.add(
        KpPrerequisite(
            kp_id=kp,
            prereq_kp_id=prereq,
            relation_type="hard",
            reason=reason,
            source_channel="both",
            pruned=0,
            needs_review=0,
        )
    )
    session.commit()


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture
def client(engine: Engine):
    """把端点的 `get_db` 指到测试库。

    **绝不能让它去用 `app.db` 的真实库** —— 那会读到开发数据，
    结论既不可复现，还可能污染它。
    """

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# ★ 1. 核心不变量：端点与 compute() 逐字段一致
# ---------------------------------------------------------------------------


def test_endpoint_numbers_equal_compute(client: TestClient, session: Session) -> None:
    """★ 接口返回的每个数字，都必须等于 `compute()` 算出来的那个。

    这就是"两套数字"的**防分叉断言** ——
    只要有人把端点改回写死，或改动了其中一边的算法，这条立刻红。
    """
    _kp(session, "kp_1", "三次握手")
    _kp(session, "kp_2", "拥塞控制")
    _edge(session, "kp_1", "kp_2")

    resp = client.get("/api/report/quality")
    assert resp.status_code == 200
    api = resp.json()["data"]
    cli = compute(session)

    for section, fields in (
        ("materials", ("total", "done", "failed", "avg_quality_score")),
        (
            "knowledge_points",
            (
                "total",
                "structure_complete_rate",
                "five_field_complete_rate",
                "grounding_rate",
                "needs_review_count",
            ),
        ),
        (
            "graph",
            (
                "edge_count",
                "cycle_count",
                "pruned_count",
                "conflict_count",
                "reason_complete_rate",
                "prerequisite_sampling_pass_rate",
            ),
        ),
        ("qa", ("session_count", "turn_count", "grounded_rate", "refuse_count")),
    ):
        for field in fields:
            assert api[section][field] == cli[section][field], (
                f"{section}.{field} 端点与 compute() 不一致 —— "
                f"端点 {api[section][field]!r} vs 计算 {cli[section][field]!r}"
            )


# ---------------------------------------------------------------------------
# ★ 2. 端点不是写死的（防止有人把 mock 加回来）
# ---------------------------------------------------------------------------


def test_endpoint_is_not_hardcoded(client: TestClient) -> None:
    """★ 空库上 `total` 必须是 **0**。

    这条专门防"哪天有人又把数字写回去" ——
    写死的 `total=184` 在这一条上必红。

    **它同时验证了另一件事**：比率在空库上是 1.0（真空满足），
    而**计数必须如实报 0**。两者混在一起是这套指标最容易被糊弄的地方。
    """
    data = client.get("/api/report/quality").json()["data"]

    assert data["materials"]["total"] == 0
    assert data["knowledge_points"]["total"] == 0
    assert data["graph"]["edge_count"] == 0
    assert data["qa"]["turn_count"] == 0

    # 比率按"真空满足"为 1.0（没有数据 ≠ 有问题），见 app/quality.py::_rate
    assert data["knowledge_points"]["structure_complete_rate"] == 1.0
    assert data["graph"]["cycle_count"] == 0


# ---------------------------------------------------------------------------
# ★ 3. 造**真实的坏数据**，指标必须真的变红
# ---------------------------------------------------------------------------


def test_bad_data_turns_acceptance_red(client: TestClient, session: Session) -> None:
    """★ 造一个**真实的环**，`B1-2 依赖图环数` 必须变 FAIL。

    **为什么必须有这条**：空库全绿毫无意义（真空满足）。
    要证明指标真的在工作，必须喂它一份**真的坏数据**，看它会不会红。

    这里用的是最难发现的一种坏数据：`kp_1 → kp_2 → kp_3 → kp_1` 成环 ——
    它不会让任何查询报错，只会让"学习路径"永远算不出来。
    """
    _kp(session, "kp_1", "A")
    _kp(session, "kp_2", "B")
    _kp(session, "kp_3", "C")
    _edge(session, "kp_1", "kp_2")
    _edge(session, "kp_2", "kp_3")
    _edge(session, "kp_3", "kp_1")  # ← 闭环

    data = client.get("/api/report/quality").json()["data"]

    assert data["graph"]["cycle_count"] >= 1, "三节点成环没被检出来 —— 环检测失效了"

    rows = {r.label: r for r in check_acceptance(compute(session))}
    b12 = rows["B1-2 依赖图环数"]
    assert b12.passed is False, "环数非 0 时 B1-2 必须是 FAIL"
    assert b12.actual is not None and b12.actual >= 1


def test_clean_graph_keeps_acceptance_green(session: Session) -> None:
    """对照组：**无环**的图必须 PASS —— 否则上一条可能是"反正都红"。"""
    _kp(session, "kp_1", "A")
    _kp(session, "kp_2", "B")
    _edge(session, "kp_1", "kp_2")

    rows = {r.label: r for r in check_acceptance(compute(session))}
    assert rows["B1-2 依赖图环数"].passed is True


# ---------------------------------------------------------------------------
# 4. 部署防线：算法必须能从 app 里 import 到
# ---------------------------------------------------------------------------


def test_graph_algo_importable_from_app() -> None:
    """`app.quality` 必须能 import 到 `graph_infer`。

    **这条防的是部署漏拷 `skills/`**：本地仓库完整时一切正常，
    只有容器里才会 `ModuleNotFoundError: graph_infer` ——
    而那时已经在跑线上服务了。

    所以这里直接断言"import 到了"，把这个失败**提前到测试阶段**。
    """
    from app import quality

    assert quality.Graph is not None
    assert callable(quality.verify)
    assert quality._ALGO_DIR is not None, "找不到 graph_infer 所在目录"
