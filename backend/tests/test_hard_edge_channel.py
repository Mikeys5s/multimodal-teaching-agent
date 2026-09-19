"""hard 边通道的验收测试（归属：P2）。

## 这条通道要证明什么

`hard` 边靠语义判断，而运行期不能调外部模型 —— 所以走的是
**「AI 预抽取（构建期）→ 导入 → 人工裁决」**（SPEC §4.8 / D-15）。

**这个文件要证明通道真的通了**，而且**最要紧的一条是最后那条**：

> 采纳一条 hard 边之后，`gap-analysis`（卡点根因回溯）**终于有输入了**。

在那之前它是"接上了、但没有输入"的空转状态 —— 本测试把这条从空转到有输入的过程钉住。

## 四条不变量

| # | 不变量 |
|---|---|
| ① | 导入的边一律 `needs_review=1` —— 候选，不是结论 |
| ② | **成环的导入整批拒收**（依赖图必须无环，B1-2） |
| ③ | `reason` 为空的边拒收（B1-5 要求 100% 完备） |
| ④ | 驳回用 `pruned=1` **软删除留痕**，不物理删除 |
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KnowledgePoint, KpPrerequisite  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
session = Session(engine, expire_on_commit=False)

MAT = "mat_channel_probe"


@pytest.fixture(scope="module", autouse=True)
def _seed() -> None:
    """种一份素材 → 真跑解析 → 真跑抽取，拿到若干真实知识点。

    复用端到端那条链路的做法：**不手工造知识点** —— 手工造的话，
    测的就不是"真实数据上的通道"，而是"夹具上的通道"。
    """
    Base.metadata.create_all(engine)

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), "5 Transport Layer", fontsize=16)
    page.insert_text((72, 120), "The transport layer provides end-to-end communication.", fontsize=11)
    page.insert_text((72, 150), "5.1 Reliable Transfer", fontsize=13)
    page.insert_text((72, 180), "Reliable transfer means no loss and no duplication.", fontsize=11)
    page.insert_text((72, 210), "5.2 Flow Control", fontsize=13)
    page.insert_text((72, 240), "Flow control prevents a fast sender from overwhelming a slow receiver.", fontsize=11)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()

    resp = client.post(
        "/api/materials",
        files={"files": ("channel-probe.pdf", buf.getvalue(), "application/pdf")},
    )
    assert resp.status_code in (200, 201, 202), resp.text[:300]
    mat_id = resp.json()["data"]["accepted"][0]["material_id"]

    # 上传会触发解析（BackgroundTasks 在 TestClient 里会跑完）
    assert client.post("/api/extract/knowledge", json={"material_ids": [mat_id]}).status_code in (
        200,
        202,
    )
    session.expire_all()
    kp_ids = list(
        session.scalars(
            select(KnowledgePoint.id)
            .where(KnowledgePoint.material_id == mat_id)
            .order_by(KnowledgePoint.seq)
        ).all()
    )
    assert len(kp_ids) >= 3, f"抽取产出的知识点太少（{len(kp_ids)}），后面的测试没有依据"
    pytest.KP_IDS = kp_ids  # type: ignore[attr-defined]


def _kps() -> list[str]:
    return list(pytest.KP_IDS)


# ---------------------------------------------------------------------------
# ① 导入：候选一律 needs_review=1
# ---------------------------------------------------------------------------


def test_import_edges_marks_them_as_candidates() -> None:
    ids = _kps()
    resp = client.post(
        "/api/review/import-edges",
        json={
            "edges": [
                {
                    "kp_id": ids[1],
                    "prereq_kp_id": ids[0],
                    "relation_type": "hard",
                    "reason": "不理解传输层提供的端到端抽象，就无法理解可靠传输在保证什么",
                    "confidence": 0.8,
                }
            ],
            "source_note": "测试用：构建期候选",
        },
    )
    data = resp.json()
    assert data.get("ok"), resp.text[:300]
    assert data["data"]["accepted"] == 1
    assert data["data"]["cycle_count"] == 0

    session.expire_all()
    row = session.get(KpPrerequisite, {"kp_id": ids[1], "prereq_kp_id": ids[0]})
    assert row is not None
    assert row.needs_review == 1, "导入的边必须标 needs_review=1 —— 它是候选，不是结论"
    assert row.source_channel == "semantic"


# ---------------------------------------------------------------------------
# ② ★ 成环的导入**整批拒收** —— 不变量不允许被绕过
# ---------------------------------------------------------------------------


def test_import_rejects_cycles_entirely() -> None:
    """把已有的边反过来导，必然成环 —— **必须整批拒收**。

    为什么不是"先写进去再剪"：依赖图必须无环是**工程不变量**（B1-2）。
    让脏数据先进库，就等于声称一个在某段时间里不成立的不变量。
    """
    ids = _kps()
    before = session.get(KpPrerequisite, {"kp_id": ids[1], "prereq_kp_id": ids[0]})
    assert before is not None, "上一条测试应该已经导入过 A<-B 这条边"

    # 反过来导一条 B<-A，与已有的 A<-B 构成环
    resp = client.post(
        "/api/review/import-edges",
        json={
            "edges": [
                {
                    "kp_id": ids[0],
                    "prereq_kp_id": ids[1],
                    "relation_type": "hard",
                    "reason": "故意造环，测试拒收",
                }
            ]
        },
    )
    assert resp.status_code == 400, f"成环的导入应当被拒（400），收到 {resp.status_code}"

    session.expire_all()
    row = session.get(KpPrerequisite, {"kp_id": ids[0], "prereq_kp_id": ids[1]})
    assert row is None, "成环的边**一条都不该落库** —— 这是'整批拒收'的含义"


# ---------------------------------------------------------------------------
# ③ reason 为空 → 拒收
# ---------------------------------------------------------------------------


def test_import_rejects_edges_without_reason() -> None:
    """`reason` 是 B1-5 的硬要求（100% 完备），空的边不能进库。"""
    ids = _kps()
    resp = client.post(
        "/api/review/import-edges",
        json={"edges": [{"kp_id": ids[2], "prereq_kp_id": ids[0], "reason": "   "}]},
    )
    # 整批只有一条且它不合法 → 拒收（有没有被静态过滤掉要看 rejected 字段）
    body = resp.json()
    if body.get("ok"):
        assert body["data"]["accepted"] == 0, "reason 为空的边不该被采纳"
        assert body["data"]["rejected"], "应当说明为什么拒"
    else:
        assert resp.status_code in (400, 422)

    session.expire_all()
    assert (
        session.get(KpPrerequisite, {"kp_id": ids[2], "prereq_kp_id": ids[0]}) is None
    ), "reason 为空的边不该落库"


def test_import_rejects_unknown_kp() -> None:
    """引用了不存在的知识点 → **整批拒收**（不做部分采纳）。"""
    ids = _kps()
    resp = client.post(
        "/api/review/import-edges",
        json={
            "edges": [
                {"kp_id": ids[2], "prereq_kp_id": ids[1], "reason": "合法的一条"},
                {"kp_id": "kp_不存在", "prereq_kp_id": ids[1], "reason": "引用不存在的知识点"},
            ]
        },
    )
    assert resp.status_code == 400
    session.expire_all()

    # ⚠️ 这里**不能断言"这条边不存在"** —— 结构线索很可能已经给出过一条 soft 边。
    #    （第一版就是这么写的，然后被测试打脸：那对节点之间本来就有 soft 边。）
    #    正确的断言是：**被拒的批没有改动既有边** —— 也就是它还是结构线索那条。
    row = session.get(KpPrerequisite, {"kp_id": ids[2], "prereq_kp_id": ids[1]})
    if row is not None:
        assert row.source_channel == "structure", (
            f"被拒的批不该改动既有边，但 source_channel 变成了 {row.source_channel!r}"
        )
        assert row.relation_type == "soft", "被拒的批不该把结构线索的 soft 边改成 hard"

    # 另一个取证角度：整批拒收意味着**这批里的合法边也没进去**
    # （它若进去了，source_channel 会是 semantic 或 both）
    edge_21 = session.get(KpPrerequisite, {"kp_id": ids[2], "prereq_kp_id": ids[1]})
    assert edge_21 is None or edge_21.source_channel != "semantic", (
        "整批拒收失败：同批里那条合法边被单独采纳了"
    )


# ---------------------------------------------------------------------------
# ④ 复核队列 + 裁决
# ---------------------------------------------------------------------------


def test_queue_lists_pending_edges() -> None:
    ids = _kps()
    data = client.get("/api/review/queue").json()["data"]
    pending = [(i["kp_id"], i["prereq_kp_id"]) for i in data["items"]]
    assert (ids[1], ids[0]) in pending, "刚导入的那条应当出现在待复核队列里"


def test_reject_keeps_a_trace_soft_delete() -> None:
    """★ 驳回要**留痕**（`pruned=1`），不物理删除。

    被驳回的边是「人做了判断」的证据 —— 答辩时能说
    「我们检出了 N 条不合理依赖并由人驳回」，比「图很干净」更有说服力。
    """
    ids = _kps()
    resp = client.post(
        "/api/review/decide",
        json={
            "kp_id": ids[1],
            "prereq_kp_id": ids[0],
            "decision": "reject",
            "note": "测试用：这条判断不对",
        },
    )
    assert resp.json().get("ok"), resp.text[:300]

    session.expire_all()
    row = session.get(KpPrerequisite, {"kp_id": ids[1], "prereq_kp_id": ids[0]})
    assert row is not None, "驳回**不该删除**这条边"
    assert row.pruned == 1, "驳回应当标 pruned=1"
    assert row.needs_review == 0, "裁决之后不该再留在待复核队列里"
    assert "人工驳回" in (row.reason or ""), "驳回理由要写进 reason，便于回溯"


# ---------------------------------------------------------------------------
# ⑤ ★ 最要紧的一条：采纳 hard 边之后，卡点回溯**终于有输入了**
# ---------------------------------------------------------------------------


def test_accepting_hard_edge_gives_gap_analysis_its_input() -> None:
    """★ 这条是整条通道的**目的**：让卡点根因回溯从"空转"变成"有输入"。

    背景（今天早些时候的发现）：结构线索只产出 `soft` 边，
    而 `gap-analysis` 沿 **`hard`** 边反向回溯 ——
    所以它在只有结构线索时是「接上了、但没有输入」。

    本测试：导入一条 hard 边 → 采纳 → **目标知识点的 gap-analysis 应当给出这条前置**。
    """
    ids = _kps()
    target, prereq = ids[1], ids[0]

    # 先导入一条新的 hard 边（上一条已被驳回，这里换一对节点重来）
    imported = client.post(
        "/api/review/import-edges",
        json={
            "edges": [
                {
                    "kp_id": target,
                    "prereq_kp_id": prereq,
                    "relation_type": "hard",
                    "reason": "端到端抽象是可靠传输的前提",
                    "confidence": 0.9,
                }
            ]
        },
    ).json()
    assert imported.get("ok"), imported

    # 采纳
    decided = client.post(
        "/api/review/decide",
        json={"kp_id": target, "prereq_kp_id": prereq, "decision": "accept"},
    ).json()
    assert decided.get("ok"), decided
    assert decided["data"]["needs_review"] is False

    # ★ 现在卡点回溯应当能看到这条硬前置
    gap = client.get(f"/api/knowledge-points/{target}/gap-analysis").json()
    assert gap.get("ok"), gap
    hard_ids = [p["kp_id"] for p in gap["data"]["hard_prerequisites"]]
    assert prereq in hard_ids, (
        f"采纳的 hard 边没有进入卡点回溯的输入：{hard_ids} —— "
        "这条通道的目的就是让这里从空转变成有输入"
    )
    for p in gap["data"]["hard_prerequisites"]:
        assert p["reason"], "硬前置必须能说清为什么"

    # 全图仍必须无环
    graph = client.get("/api/knowledge-graph").json()["data"]
    assert graph["stats"]["cycle_count"] == 0
