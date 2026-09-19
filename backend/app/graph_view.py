"""从库里读依赖图，组装成接口/报告能用的形状（归属：P2）。

## 为什么要有这个模块（而不是在每个端点里各写一遍）

**因为方向映射会写错，而且写错了不报错。**

数据库里：`kp_prerequisites.prereq_kp_id` 是**前置**、`kp_id` 是**后置**；
而 `graph_infer` 要的是 `Edge.src` = 前置、`Edge.dst` = 后置。
**这两套名字一旦映射反了，环检测会失效、学习路径会整个反过来 —— 而没有任何报错。**

所以映射只写一遍，在这里。`app/quality.py` 与 `api/graph.py` 都用它 ——
这也是我在 `docs/api-spec.md` 里把方向写成"硬约定"时说的那句话：
**文档是给人看的，而这里是不让它有机会写错的地方。**

## 三个消费方

| 消费方 | 要什么 |
|---|---|
| `GET /api/knowledge-graph` | 节点 + 边 + 统计（给前端画图） |
| `GET /api/learning-path` | 拓扑序 + 每步的 `reason` |
| `GET /api/knowledge-points/{id}/gap-analysis` | 沿 hard 边反向可达的前置与断层 |
| `scripts/evaluate.py`（质量报告） | 环数 / 理由完备率 / 稀疏性 |

前三个用"这个模块直接给的结果"，最后一个用 `graph_infer.verify()` 的原始输出 ——
**都走同一次映射**。
"""

from __future__ import annotations

import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgePoint, KpPrerequisite


def _algo_dir():
    """复用 `app.quality` 的路径引导（那里已经处理过 skills/ 的定位）。"""
    from app.quality import _ALGO_DIR

    if _ALGO_DIR is not None and str(_ALGO_DIR) not in sys.path:
        sys.path.insert(0, str(_ALGO_DIR))
    return _ALGO_DIR


# 模块级把路径布好，这样"算法"能从这一处统一再导出 ——
# 调用方（api/graph.py、api/knowledge.py）只 import 本模块，不必各自再做一次路径引导。
_algo_dir()
from graph_infer import gap_analysis, learning_path, verify  # noqa: E402

__all__ = [
    "gap_analysis",
    "graph_stats",
    "learning_path",
    "load_graph",
    "verify",
]


def load_graph(session: Session, material_id: str | None = None, chapter_id: str | None = None):
    """读出图数据，返回 `(graph, kp_rows, edge_rows, verify_result)`。

    - `graph` 是 `graph_infer.Graph`，可直接交给 `verify()` / `path()` / `gap()`
    - `kp_rows` / `edge_rows` 是原始行，给需要附加信息（难度、名称）的调用方用
    """
    _algo_dir()
    from graph_infer import Graph, verify

    kp_stmt = select(KnowledgePoint)
    if material_id is not None:
        kp_stmt = kp_stmt.where(KnowledgePoint.material_id == material_id)
    if chapter_id is not None:
        kp_stmt = kp_stmt.where(KnowledgePoint.chapter_id == chapter_id)
    kps = session.scalars(kp_stmt.order_by(KnowledgePoint.seq)).all()
    kp_ids = [k.id for k in kps]

    edges: list[KpPrerequisite] = []
    if kp_ids:
        edges = list(
            session.scalars(
                select(KpPrerequisite).where(KpPrerequisite.kp_id.in_(kp_ids))
            ).all()
        )

    # ★ 方向映射只在这一处（见模块 docstring）
    payload_edges = [
        {
            "prereq_name": e.prereq_kp_id,  # 前置 = src
            "dependent_name": e.kp_id,  # 后置 = dst
            "relation_type": e.relation_type,
            "reason": e.reason or "",
            "confidence": float(e.confidence) if e.confidence is not None else 0.0,
            "pruned": bool(e.pruned),
        }
        for e in edges
    ]
    graph = Graph.from_payload({"nodes": sorted(kp_ids), "edges": payload_edges})
    return graph, list(kps), edges, verify(graph)


def graph_stats(session: Session, material_id: str | None = None) -> dict[str, Any]:
    """给质量报告用的图统计（`evaluate.py` 与 `report/quality` 都用它）。"""
    _, _, edges, result = load_graph(session, material_id=material_id)
    return {
        "edge_count": result["edge_count"],
        "hard_edge_count": result["hard_edge_count"],
        "soft_edge_count": result["soft_edge_count"],
        "cycle_count": result["cycle_count"],
        "pruned_count": result["pruned_edge_count"],
        "reason_complete_rate": result["reason_complete_rate"],
        "conflict_count": sum(1 for e in edges if e.needs_review == 1),
        "sparsity_ok": result["sparsity_ok"],
        "max_in_degree": result["max_in_degree"],
        "max_out_degree": result["max_out_degree"],
        "self_loop_count": len(result["self_loops"]),
        "isolated_node_count": len(result["isolated_nodes"]),
    }
