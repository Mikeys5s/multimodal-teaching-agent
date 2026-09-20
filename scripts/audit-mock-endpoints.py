#!/usr/bin/env python
"""★ 判定哪些端点返回的是假数据（归属：P2）。

## 为什么需要它

本项目有一段**骨架期**：接口先冻结，业务数据返回 mock（团队约定 D-22）。
那段时期是有价值的 —— 它让前端能立刻对接。

但它的**代价是一个看不见的状态**：代码完整、测试全绿、界面上有数据，
**而数据是编的**。没有仪器的话，你无法从外部区分这两种情况。

**这个脚本就是那台仪器。**

## 判据：**在一个空库上打每个端点**

| 空库上的表现 | 结论 |
|---|---|
| 返回空 / 404 / 400 | ✅ **真实** —— 数据来自库 |
| **返回非空数据** | ⚠️ **必然是编的** |

这就是「真空满足」检查的用法：**如果一个指标在空库上不空，它就不可能是真数据。**

## 为什么读代码不行（这一条是踩出来的）

判定这件事，我先后用过四种办法，**前四种都错**：

| # | 办法 | 错在哪 |
|---|---|---|
| 1 | 看 `MOCK_MODE = True` 的模块 | 漏掉**同一文件里**只对某个端点生效的开关 |
| 2 | grep 函数体 5000 字符里有没有 `MOCK_MODE` | 窗口太短、且有的端点压根没写开关 |
| 3 | 按 `_mock_*` 前缀找 | 有的假数据是**内联**的，没有 `_mock_` 前缀 |
| 4 | AST 递归判 helper | 判据仍是"有没有 mock"，`POST /extract` 返回写死的 job_id 也逃过了 |
| **5** | **空库实测** ✅ | **不需要理解代码 —— 只观察行为** |

**教训：判断"系统实际会做什么"时，观察行为比读实现可靠。**
读代码需要你猜对所有分支，而实测只需要系统自己跑一遍。

## 用法

```bash
backend/.venv/Scripts/python.exe scripts/audit-mock-endpoints.py
```

**零副作用**：用一个临时库，不碰开发数据。

**建议在 D9（功能冻结）之前跑一次**：那时应该**全部是 ✅**。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "skills" / "xizhi-graph-infer" / "scripts"))

# ⚠️ 必须在 import app 之前把库指向一个空的临时库
_TMP = Path(tempfile.mkdtemp(prefix="xizhi-audit-"))
os.environ["DB_PATH"] = str(_TMP / "audit.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(engine)  # 建表，但**不插任何数据**
client = TestClient(app, raise_server_exceptions=False)

#: 覆盖所有"读取"端点。新增端点时**请加进来** ——
#: 一个"没人检查真假"的端点，正是这套机制要防的东西。
GETS = [
    "/api/materials",
    "/api/materials/mat_probe/blocks",
    "/api/materials/mat_probe/markdown",
    "/api/materials/mat_probe/outline",
    "/api/materials/mat_probe/questions",
    "/api/knowledge-points",
    "/api/knowledge-points/kp_probe",
    "/api/knowledge-points/kp_probe/gap-analysis",
    "/api/knowledge-graph",
    "/api/learning-path?kp_id=kp_probe",
    "/api/jobs/job_probe",
    "/api/jobs",
    "/api/report/quality",
    "/api/export/knowledge-points?format=json",
    "/api/qa/sessions/qa_probe",
    "/api/qa/sessions/qa_probe/state",
    "/api/qa/sessions/qa_probe/report",
]


def data_volume(data: Any) -> tuple[int, str]:
    """估出「这份响应里有多少条真实数据」。

    ⚠️ 不要数 dict 的**键** —— 一个"结构完整但内容为空"的真实响应
    （如空库上的质量报告：五段都在、每段都是 0）会被误判成假数据。
    这个 bug 在本脚本的第一版里出现过。
    """
    if data is None:
        return 0, "null"
    if isinstance(data, list):
        return len(data), f"list[{len(data)}]"
    if not isinstance(data, dict):
        return 1, str(data)[:40]

    if isinstance(data.get("items"), list):
        return len(data["items"]), f"items[{len(data['items'])}]"
    if isinstance(data.get("total"), int):
        return data["total"], f"total={data['total']}"
    # ⚠️ **白名单要够宽，否则会落到最后的 `leaves` 检查上去。**
    #
    # 2026-09-20 实测：`/outline` 返回 `{material_id, chapters: [...]}`，
    # `chapters` 不在下面这行里 → 落到 `leaves`（只有 `material_id` 非空）→
    # **`return 1, "有非空字段"`** —— 于是 **mock 和真实返回同一个值 `n=1`**：
    # 既可能漏检，也可能误报（真实的空 outline 也被判"假数据"）。
    for key in (
        "nodes", "edges", "steps", "hard_prerequisites", "turns",
        # ★ 结构型字段：返回"章/节/块"的端点，直接数它才是它们的"数据条数"
        "chapters", "sections", "blocks", "sessions", "turns", "items",
    ):
        if isinstance(data.get(key), list):
            return len(data[key]), f"{key}[{len(data[key])}]"
    for section in ("materials", "knowledge_points"):
        sec = data.get(section)
        if isinstance(sec, dict) and isinstance(sec.get("total"), int):
            return sec["total"], f"{section}.total={sec['total']}"

    # ★ **递归数一遍叶子里的列表**（白名单没命中时的兜底）。
    #
    # 为什么需要它：白名单只能列举"我知道的结构"，而**响应形状会变**。
    # 兜底用"数所有列表元素的条数"是**形状无关**的 ——
    # mock 的 1 章「传输层」和真实的 0 章，这才区分得开。
    found = _count_list_items(data)
    if found:
        return found, f"递归统计 {found} 条"

    leaves = [v for v in data.values() if not isinstance(v, (dict, list))]
    if all(v in (None, "", 0, False, []) for v in leaves):
        return 0, "全空"
    return 1, "有非空字段"


def _count_list_items(node: Any) -> int:
    """递归数出这个响应体里**所有列表的元素总数**。

    形状无关 —— 不依赖任何具体字段名。
    `chapters: [{sections: [a, b]}]` -> 1 + 2 = 3 条。
    """
    if isinstance(node, list):
        return len(node) + sum(_count_list_items(x) for x in node)
    if isinstance(node, dict):
        return sum(_count_list_items(v) for v in node.values())
    return 0


# ---------------------------------------------------------------------------
# 轮 2 · 有数据的库：用**真实存在的 id** 打一遍
# ---------------------------------------------------------------------------
#
# ⚠️ **这才是能发现 P3 那类问题的一轮。**
#
# 轮 1 用不存在的 id（`mat_probe`）—— 它验的是"空库上不该有数据"。
# 但**库里有数据时，读端点必须返回非空**；返回空就说明它没在读库（还在走 mock）。
#
# 不跑这一轮，就会漏掉「三份材料返回一模一样的 outline」这种：
# 它每一份都"有数据"（都不是空），轮 1 完全看不出来。

#: 轮 2 要打的端点 —— `{mid}` / `{kid}` 会被替换成**临时库里真实存在**的 id。
ROUND2_PATHS = [
    "/api/materials",
    "/api/materials/{mid}/blocks",
    "/api/materials/{mid}/outline",
    "/api/knowledge-points",
    "/api/knowledge-graph",
    "/api/report/quality",
]


def _seed_minimal(db_path: str) -> tuple[str, str]:
    """在临时库里插一份**最小真实数据**，返回 (material_id, kp_id)。

    故意做得"最小"：1 份素材 / 1 章 / 1 节 / 2 个知识点 / 1 条边 ——
    足够让每个读端点都返回非空，又不会让脚本变慢或难懂。
    """
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import (
        Chapter,
        KnowledgePoint,
        KpPrerequisite,
        Material,
        MaterialBlock,
        Section,
    )

    eng = create_engine(f"sqlite:///{db_path}", future=True)
    with Session(eng) as s:
        s.add(Material(
            id="mat_audit_r2", filename="audit-probe.pdf", file_hash="a" * 64,
            stored_path=db_path, mime_type="application/pdf", size_bytes=1,
            source_type="pdf", parse_method="text_extract", status="done",
            page_count=1, char_count=100, quality_score=0.9,
        ))
        s.add(Chapter(id="ch_audit_r2", material_id="mat_audit_r2",
                      number="1", title="审计用章", seq=0))
        s.add(Section(id="sec_audit_r2", material_id="mat_audit_r2",
                      chapter_id="ch_audit_r2", number="1.1", title="审计用节", seq=0))
        s.add(MaterialBlock(id="blk_audit_r2", material_id="mat_audit_r2",
                            seq=0, page_no=1, block_type="heading",
                            content_md="1.1 审计用节"))
        for i, name in enumerate(("审计用知识点甲", "审计用知识点乙")):
            s.add(KnowledgePoint(
                id=f"kp_audit_r2_{i}", section_id="sec_audit_r2",
                chapter_id="ch_audit_r2", material_id="mat_audit_r2",
                name=name, summary_md=name, difficulty=3,
                difficulty_reason="审计用", kp_type="concept",
                source_material_id="mat_audit_r2", source_page=1,
                source_block_id="blk_audit_r2", source_quote=name,
                confidence=0.5, needs_review=1, seq=i,
            ))
        s.add(KpPrerequisite(
            kp_id="kp_audit_r2_1", prereq_kp_id="kp_audit_r2_0",
            relation_type="hard", reason="审计用：甲先于乙",
            evidence_quote="审计用知识点甲", source_channel="structure",
            confidence=0.6, needs_review=1, pruned=0,
        ))
        s.commit()
    eng.dispose()
    return "mat_audit_r2", "kp_audit_r2_0"


def audit_round2(client) -> list[tuple[str, int, str]]:
    """轮 2：用真实 id 打一遍，返回 [(path, code, note)]。

    判据**与轮 1 相反**：**有数据的库上，读端点必须返回非空**。
    返回空（或 404）= 端点没在读库。
    """
    from app.config import settings

    mid, kid = _seed_minimal(str(settings.db_file))
    out: list[tuple[str, int, str]] = []

    for tmpl in ROUND2_PATHS:
        path = tmpl.format(mid=mid, kid=kid)
        resp = client.get(path)
        code = resp.status_code
        if code != 200:
            out.append((path, code, f"**有数据的库上返回 {code}** —— 端点没读库？"))
            continue
        try:
            body = resp.json()
            data = body.get("data") if isinstance(body, dict) else body
        except Exception:  # noqa: BLE001
            data = None
        n, summary = data_volume(data)
        if n == 0:
            out.append((path, code, f"**200 但 0 条（{summary}）** —— 库里有数据却没读出来"))
        else:
            out.append((path, code, f"非空（{summary}）"))
    return out


def main(argv: list[str] | None = None) -> int:
    mock: list[str] = []
    real: list[str] = []

    print("=" * 84)
    print("空库实测 —— 有真实数据即判为假")
    print("=" * 84)
    print(f"临时库：{os.environ['DB_PATH']}（已建表，0 行）")
    print()

    for path in GETS:
        resp = client.get(path)
        code = resp.status_code
        if code in (400, 404, 422):
            real.append(path)
            note = f"{code}（空库上正确地报错）"
        else:
            try:
                body = resp.json()
                data = body.get("data") if isinstance(body, dict) else body
            except Exception:  # noqa: BLE001
                data = None
            n, summary = data_volume(data)
            if n == 0:
                real.append(path)
                note = f"200 但 0 条（{summary}）"
            else:
                mock.append(path)
                note = f"200 且有 {n} 条（{summary}）"
        print(f"  {'⚠️ 假数据' if path in mock else '✅ 真实  ':<10} {path:<48} {note}")

    print()
    print("=" * 84)
    print(f"⚠️ 假数据 {len(mock)} 个")
    for p in mock:
        print(f"      {p}")
    print(f"\n✅ 真实 {len(real)} 个")
    print()
    if mock:
        print("=> 还有假数据。**D9 功能冻结前应为 0**。")
        return 1
    print("=> 全部真实 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
