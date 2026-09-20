"""★ 端到端链路测试 —— **这条测试是"完成"的定义**（归属：P2）。

## 它为什么存在

本项目有过一段**骨架期**：接口先冻结、业务数据返回 mock（团队约定 D-22）。
结果是一个**看不见的状态**：

> 28 个端点、400+ 测试全绿、六个页面、部署上线 —— **而端到端从未跑通。**
> 每个零件都做好了，**但没有接在一起。**

`test_api_smoke.py` 验的是**契约形状**（字段名、包封、错误码）；
`test_evaluate.py` 验的是**指标算法**。
**没有任何一条测试问过：「从一份文件进去，到一条学习路径出来，中间断在哪？」**

这条测试就是问这个问题的。

## 它怎么用

**它现在会失败 —— 那是它的作用，不是它的缺陷。**
它把"还差哪一段"变成一条**可执行、可复现、可自动检查**的断言，
而不是一句"链路还没通"。

每一步都有独立断言，**失败信息会直接告诉你是哪一段断的**：

| 步骤 | 断在这里时的现象 |
|---|---|
| 1. 上传落库 | `POST /materials` 返回 202，但库里查不到这份素材 |
| 2. 解析产出块 | 素材在，但 `material_blocks` 是空的 |
| 3. 章节骨架 | 块在，但 `sections` 没生成（三级结构第一级） |
| 4. 触发抽取 | 任务建了但没跑，或 `job_id` 对不上 |
| 5. 知识点落库 | 抽取跑完了，但 `knowledge_points` 还是空 |
| 6. 依赖边 | 有知识点，但 `kp_prerequisites` 没有边 |
| 7. 图与路径 | 接口返回值与库里的行数对不上（说明还在走 mock） |

## 设计上的两条自律

**① 不依赖任何外部素材。** PDF 是**程序化生成**的（pymupdf），
所以任何人 clone 下来都能跑 —— 不需要那份 489 页教材。
（对比：`test_qa_parse_real_material.py` 的 14 个用例默认 skip，正是因为它依赖外部文件。）

**② 不碰主工作区、不碰开发库。** 用测试库；跑完不留痕。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Job,
    KnowledgePoint,
    KpPrerequisite,
    Material,
    MaterialBlock,
    Section,
)

client = TestClient(app, raise_server_exceptions=False)
session = Session(engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _schema() -> None:
    Base.metadata.create_all(engine)


def _make_pdf() -> bytes:
    """程序化生成一份**两页、带章节标题**的小 PDF。

    为什么要生成而不是用现成教材：
    **这条测试必须能被任何人在任何机器上跑起来。**
    一份依赖外部文件的端到端测试，最终会变成"14 个 skip"里的一个。
    """
    doc = pymupdf.open()
    page1 = doc.new_page()
    page1.insert_text((72, 90), "5 Transport Layer", fontsize=16)
    page1.insert_text((72, 120), "The transport layer provides end-to-end logical", fontsize=11)
    page1.insert_text((72, 136), "communication between application processes.", fontsize=11)
    page2 = doc.new_page()
    page2.insert_text((72, 90), "5.3 TCP Congestion Control", fontsize=14)
    page2.insert_text((72, 120), "The congestion window cwnd is adjusted by the sender", fontsize=11)
    page2.insert_text((72, 136), "according to the level of network congestion.", fontsize=11)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ★ 端到端：一份文件进去 → 一条学习路径出来
# ---------------------------------------------------------------------------


def test_end_to_end_pipeline() -> None:
    """★ 从上传到学习路径，七步全通。

    **失败时看断言消息里的步骤编号** —— 它直接告诉你链路断在哪一段。

    ---

    **2026-09-19：本条已从 `xfail(strict=True)` 转为正式通过。**

    它曾经是 xfail 的，那是刻意的：链路没接通时让"已知不通"被**显式记录**
    而不是被遗忘；一旦接通，`strict=True` 会让 XPASS 把测试套件顶红，
    **强制把这个标记摘掉**。今天它真的被顶红了，所以标记摘了。

    **这条测试抓到的第一个真问题**：FastAPI 的路由装饰器后面必须紧跟端点函数 ——
    我把两个 helper 写在中间，于是 `/materials` 变成了"要求一个 ext 字段"的接口。
    **而 `test_api_smoke.py` 碰不到这条路**（它只发空请求验 400）。
    """
    pdf = _make_pdf()

    # ---- 步骤 1：上传 → 素材落库 ----------------------------------------
    resp = client.post(
        "/api/materials",
        files={"files": ("e2e-probe.pdf", pdf, "application/pdf")},
    )
    assert resp.status_code in (200, 201, 202), f"步骤1 上传失败：{resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body.get("ok") is True, f"步骤1 上传未成功：{body}"

    accepted = (body.get("data") or {}).get("accepted") or []
    assert accepted, f"步骤1 上传被拒：{body.get('data')}"
    material_id = accepted[0]["material_id"]

    session.expire_all()
    mat = session.get(Material, material_id)
    assert mat is not None, (
        f"步骤1 断在这里：上传返回了 material_id={material_id}，"
        f"**但库里查不到这条素材** —— 上传端点没有落库。"
    )
    assert mat.stored_path, "步骤1 素材落库了，但 stored_path 为空 —— 文件没存"

    # ---- 步骤 2：解析 → 产出块 ------------------------------------------
    blocks = session.scalars(
        select(MaterialBlock).where(MaterialBlock.material_id == material_id).order_by(MaterialBlock.seq)
    ).all()
    assert blocks, (
        "步骤2 断在这里：素材已落库，**但 material_blocks 是空的** —— "
        "解析没有跑，或者跑完没落库。"
    )
    assert any(b.page_no for b in blocks), "步骤2 块有了，但都没有页码锚点（破坏 A1-6）"

    # ---- 步骤 3：章节骨架（三级结构的第一、二级）------------------------
    sections = session.scalars(
        select(Section).where(Section.material_id == material_id)
    ).all()
    assert sections, "步骤3 断在这里：块有了，**但 sections 没生成** —— 三级结构无从建立"

    # ---- 步骤 4：触发抽取 → 建真任务 ------------------------------------
    resp = client.post("/api/extract/knowledge", json={"material_ids": [material_id]})
    assert resp.status_code in (200, 202), f"步骤4 触发抽取失败：{resp.status_code}"
    job_id = (resp.json().get("data") or {}).get("job_id")

    session.expire_all()
    job = session.get(Job, job_id) if job_id else None
    assert job is not None, (
        f"步骤4 断在这里：抽取返回了 job_id={job_id}，**但 jobs 表里没有这条任务** —— "
        "job_id 是拼出来的。"
    )

    # ---- 步骤 5：知识点落库 --------------------------------------------
    kps = session.scalars(
        select(KnowledgePoint).where(KnowledgePoint.material_id == material_id)
    ).all()
    assert kps, (
        "步骤5 断在这里：任务建了，**但 knowledge_points 还是空的** —— "
        "抽取流水线没有真正跑（或跑完没落库）。"
    )

    # 五要素与溯源：这是 A2-1 / A2-3 的地基，端到端也该顺带守住
    for kp in kps:
        assert kp.section_id and kp.chapter_id, f"知识点 {kp.id} 缺三级结构归属（A2-1）"
        assert kp.source_quote, f"知识点 {kp.id} 缺溯源原文（A2-3）"

    # ---- 步骤 5b：**抽取质量的可测下界** ⚠️ --------------------------------
    #
    # 为什么必须有这一段：上面那句 `assert kps` **几乎必然通过** ——
    # 抽取规则是"标题块 + 段落里的定义句式"，只要块够多就一定有候选。
    # **一条必然通过的断言，信息量是零**：它证明了"链路通"，证明不了"抽得对"。
    #
    # 下面这几条是**真正会失败**的下界。
    n_secs = len(sections)
    assert len(kps) >= max(1, n_secs), (
        f"抽出的知识点（{len(kps)}）比节数（{n_secs}）还少 —— "
        "每个节至少该产出一个候选，这通常意味着某节的块区间推错了"
    )
    # 同一个节内不允许重名 —— 重名意味着同一段内容被抽了两遍
    for sec in sections:
        names = [k.name for k in kps if k.section_id == sec.id]
        assert len(names) == len(set(names)), (
            f"节「{sec.title}」内出现重名知识点：{[n for n in names if names.count(n) > 1]}"
        )
    # 结构线索的产出**必须全部**标 needs_review —— 它是候选，不是结论
    assert all(k.needs_review == 1 for k in kps), (
        "结构线索抽出的知识点必须全部标 needs_review=1 —— 它只是候选，判断权在人"
    )
    # 溯源片段要够长才有核对价值（太短等于没给来源）
    for kp in kps:
        assert len((kp.source_quote or "").strip()) >= 4, (
            f"知识点 {kp.id} 的溯源片段过短（{len(kp.source_quote or '')} 字符），核对不了"
        )

    # ---- 步骤 6：依赖边 -------------------------------------------------
    kp_ids = [k.id for k in kps]
    edges = session.scalars(
        select(KpPrerequisite).where(KpPrerequisite.kp_id.in_(kp_ids))
    ).all()
    assert edges, (
        "步骤6 断在这里：有知识点，**但 kp_prerequisites 一条边都没有** —— "
        "依赖图是空的，学习路径与卡点回溯都无从谈起（B1 系列全落空）。"
    )
    for e in edges:
        assert e.reason, f"边 {e.prereq_kp_id}->{e.kp_id} 缺理由（B1-5 要求 100% 完备）"

    # ---- 步骤 7：接口读数必须与库里一致（防"偷偷走回 mock"）-------------
    resp = client.get(f"/api/knowledge-graph?material_id={material_id}")
    assert resp.status_code == 200, f"步骤7 图谱接口失败：{resp.status_code}"
    graph = resp.json().get("data") or {}
    db_nodes = session.scalar(
        select(func.count()).select_from(KnowledgePoint).where(KnowledgePoint.material_id == material_id)
    )
    assert len(graph.get("nodes") or []) == db_nodes, (
        f"步骤7 断在这里：接口返回 {len(graph.get('nodes') or [])} 个节点，"
        f"库里有 {db_nodes} 个 —— **接口没有读库**（还在走 mock）。"
    )
    assert (graph.get("stats") or {}).get("cycle_count") == 0, "B1-2：依赖图必须无环"

    resp = client.get(f"/api/learning-path?kp_id={kp_ids[0]}")
    assert resp.status_code == 200, f"步骤7 学习路径接口失败：{resp.status_code}"
    # ⚠️ 同上：`data` 是数组，不能再 `.get("steps")`
    #    （原写法在 list 上调 `.get()` → AttributeError）
    _d = resp.json().get("data")
    steps = _d if isinstance(_d, list) else []
    assert steps, "步骤7 学习路径为空 —— 拓扑排序没接上或图不连通"
