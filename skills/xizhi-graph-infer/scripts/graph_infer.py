#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
析知 · 知识依赖图推理器（XiZhi Graph Infer）

本模块是「析知」项目的核心算法实现，承担 SPEC §4.8.3 定义的「运行期零模型依赖」的全部图推理：
    1. verify        —— 图完整性校验：环数 / 稀疏性 / reason 完备率（对应验收项 B1-2 / B1-5）
    2. prune         —— DAG 环路检测与剪枝（按 confidence 升序剪边，软删除保留记录）（B1-2）
    3. path          —— 学习路径生成：沿 hard 边反向可达 + 拓扑排序（B1-3）
    4. gap           —— 卡点根因回溯：定位最可能的断层前置知识点（B1-6）

设计原则：
    · 纯标准库，零第三方依赖 —— 可离线运行、可嵌入任何形态（Skill / CLI / 服务）
    · 全部为确定性算法 —— 相同输入必然得到相同输出（对应验收项 A2-7 可复现性）
    · 不调用任何模型 —— 这是 SPEC §4.8「LLM 移出关键路径」的具体落地

输入格式：SPEC 定义的前置依赖边 JSON（见 docs/prompt-contracts.md P10 契约）
输出格式：全部为 JSON，便于被上层任意形态消费

用法：
    python graph_infer.py verify --input edges.json
    python graph_infer.py prune  --input edges.json [--out pruned.json]
    python graph_infer.py path   --input edges.json --target "快速恢复 Fast Recovery"
    python graph_infer.py gap    --input edges.json --target "快速恢复 Fast Recovery" [--misconception-config misc.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# 常量：与 SPEC / docs/data-model.md 保持一致
# ---------------------------------------------------------------------------

HARD = "hard"
SOFT = "soft"

MAX_IN_DEGREE = 3   # 每个知识点最多 3 条入边（P10 契约的稀疏性约束）
MAX_OUT_DEGREE = 4  # 每个知识点最多 4 条出边


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    """一条前置依赖边：src 是前置，dst 是后置（要学会的那个）。"""
    src: str                     # 前置知识点
    dst: str                     # 后置知识点
    relation_type: str = HARD    # hard / soft
    reason: str = ""
    confidence: float = 0.0
    pruned: bool = False
    pruned_reason: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.src, self.dst)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prereq_name": self.src,
            "dependent_name": self.dst,
            "relation_type": self.relation_type,
            "reason": self.reason,
            "confidence": self.confidence,
            "pruned": self.pruned,
            "pruned_reason": self.pruned_reason,
        }


@dataclass
class Graph:
    """知识依赖图。节点集合由边自动推导，允许孤立节点显式传入。"""
    nodes: set[str] = field(default_factory=set)
    edges: list[Edge] = field(default_factory=list)

    # -- 构建 ---------------------------------------------------------------
    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Graph":
        """从 SPEC 的 P10 契约输出（或其裁剪版）构建图。

        兼容三种输入：
          1. {"edges": [...]}                        —— P10 原始输出
          2. [{"prereq_name": ..., ...}, ...]        —— 裸数组
          3. {"nodes": [...], "edges": [...]}        —— 已带节点列表
        """
        if isinstance(payload, list):
            raw_edges = payload
            raw_nodes: list[str] = []
        else:
            raw_edges = payload.get("edges", [])
            raw_nodes = payload.get("nodes", []) or []

        g = cls()
        for n in raw_nodes:
            if isinstance(n, dict):
                g.nodes.add(n.get("id") or n.get("name") or "")
            else:
                g.nodes.add(str(n))
        g.nodes.discard("")

        for e in raw_edges:
            src = e.get("prereq_name") or e.get("src") or e.get("from")
            dst = e.get("dependent_name") or e.get("dst") or e.get("to")
            if not src or not dst:
                continue  # 缺端点的边直接跳过，不猜
            g.edges.append(Edge(
                src=str(src),
                dst=str(dst),
                relation_type=(e.get("relation_type") or HARD).lower(),
                reason=e.get("reason") or "",
                confidence=float(e.get("confidence") or 0.0),
                pruned=bool(e.get("pruned") or False),
            ))
            g.nodes.add(str(src))
            g.nodes.add(str(dst))
        return g

    # -- 视图 ---------------------------------------------------------------
    def active_edges(self) -> list[Edge]:
        """未被剪枝的边（剪枝边保留记录用于解释，但不参与图计算）。"""
        return [e for e in self.edges if not e.pruned]

    def adjacency(self, relation: str | None = None) -> dict[str, list[str]]:
        """src -> [dst]，可选只取某类关系。"""
        adj: dict[str, list[str]] = {n: [] for n in self.nodes}
        for e in self.active_edges():
            if relation and e.relation_type != relation:
                continue
            adj.setdefault(e.src, []).append(e.dst)
        return adj

    def reverse_adjacency(self, relation: str | None = None) -> dict[str, list[str]]:
        """dst -> [src]，用于反向可达（学习路径与卡点回溯都靠它）。"""
        radj: dict[str, list[str]] = {n: [] for n in self.nodes}
        for e in self.active_edges():
            if relation and e.relation_type != relation:
                continue
            radj.setdefault(e.dst, []).append(e.src)
        return radj

    def edge_lookup(self) -> dict[tuple[str, str], Edge]:
        return {e.key: e for e in self.active_edges()}

    # -- 度数 ---------------------------------------------------------------
    def degrees(self) -> tuple[dict[str, int], dict[str, int]]:
        indeg = {n: 0 for n in self.nodes}
        outdeg = {n: 0 for n in self.nodes}
        for e in self.active_edges():
            outdeg[e.src] = outdeg.get(e.src, 0) + 1
            indeg[e.dst] = indeg.get(e.dst, 0) + 1
        return indeg, outdeg


# ---------------------------------------------------------------------------
# 算法 1：拓扑排序与环检测
# ---------------------------------------------------------------------------

def topological_sort(graph: Graph) -> tuple[list[str] | None, list[str]]:
    """Kahn 算法。

    返回 (拓扑序, 未排序节点)。
    拓扑序为 None 表示存在环；此时未排序节点即「处于环中或环的下游」的节点集合。
    """
    indeg, _ = graph.degrees()
    adj = graph.adjacency()
    queue = deque(sorted(n for n in graph.nodes if indeg.get(n, 0) == 0))
    order: list[str] = []

    while queue:
        u = queue.popleft()
        order.append(u)
        for v in sorted(adj.get(u, [])):
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)

    remaining = [n for n in graph.nodes if n not in set(order)]
    return (order if not remaining else None), remaining


def find_one_cycle(graph: Graph) -> list[str] | None:
    """DFS 三色标记，找出一个环并返回环上的节点序列（首尾相接，末尾重复起点）。"""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph.nodes}
    parent: dict[str, str] = {}
    adj = graph.adjacency()

    def dfs(u: str) -> list[str] | None:
        color[u] = GRAY
        for v in sorted(adj.get(u, [])):
            if color.get(v, WHITE) == GRAY:
                # 回边：v 在递归栈中 → 构环
                chain = [v]
                cur = u
                while cur != v and cur in parent:
                    chain.append(cur)
                    cur = parent[cur]
                chain.append(v)
                return list(reversed(chain))
            if color.get(v, WHITE) == WHITE:
                parent[v] = u
                found = dfs(v)
                if found:
                    return found
        color[u] = BLACK
        return None

    for n in sorted(graph.nodes):
        if color.get(n, WHITE) == WHITE:
            found = dfs(n)
            if found:
                return found
    return None


def prune_cycles(graph: Graph, max_rounds: int = 50) -> dict[str, Any]:
    """环路剪枝：反复找出一个环，剪掉环上 confidence 最低的边，直到无环。

    刻意采用「软删除」：被剪的边保留在图上并标记 pruned / pruned_reason，
    因为「检出了哪些会成环的边」本身就是系统在自检的证据（SPEC §2.5 注）。
    """
    log: list[dict[str, Any]] = []

    for rnd in range(1, max_rounds + 1):
        cycle = find_one_cycle(graph)
        if cycle is None:
            break

        lookup = graph.edge_lookup()
        cycle_edges: list[Edge] = []
        for i in range(len(cycle) - 1):
            pair = (cycle[i], cycle[i + 1])
            if pair in lookup:
                cycle_edges.append(lookup[pair])

        if not cycle_edges:
            log.append({"round": rnd, "error": "检出环但无法定位环上的边", "cycle": cycle})
            break

        # 剪 confidence 最低者；confidence 相同时按 (src, dst) 稳定排序，保证可复现
        victim = min(cycle_edges, key=lambda e: (e.confidence, e.src, e.dst))
        victim.pruned = True
        victim.pruned_reason = "cycle_detected"
        log.append({
            "round": rnd,
            "cycle": cycle,
            "pruned_edge": {"prereq_name": victim.src, "dependent_name": victim.dst},
            "pruned_confidence": victim.confidence,
            "candidates": [
                {"prereq_name": e.src, "dependent_name": e.dst, "confidence": e.confidence}
                for e in sorted(cycle_edges, key=lambda e: e.confidence)
            ],
        })

    remaining_cycle = find_one_cycle(graph)
    return {
        "pruned_count": len(log),
        "rounds": log,
        "cycle_count_after": 0 if remaining_cycle is None else 1,
    }


# ---------------------------------------------------------------------------
# 算法 2：学习路径（沿 hard 边反向可达 + 拓扑排序）
# ---------------------------------------------------------------------------

def learning_path(graph: Graph, target: str, include_soft: bool = False) -> dict[str, Any]:
    """生成「从地基到目标」的学习路径。

    默认只沿 hard 边回溯 —— 因为软前置不构成阻塞，把它们排进必经路径会虚增学习量。
    include_soft=True 时把软前置也纳入（用于展示「学有余力的补充」）。
    """
    if target not in graph.nodes:
        return {"ok": False, "error": f"目标知识点不在图中：{target}"}

    relation = None if include_soft else HARD
    radj = graph.reverse_adjacency(relation=relation)

    # BFS 反向可达，记录最短层级
    depth: dict[str, int] = {target: 0}
    queue = deque([target])
    while queue:
        u = queue.popleft()
        for pre in radj.get(u, []):
            if pre not in depth:
                depth[pre] = depth[u] + 1
                queue.append(pre)

    sub_nodes = set(depth.keys())
    sub = Graph(nodes=sub_nodes, edges=[
        e for e in graph.active_edges()
        if e.src in sub_nodes and e.dst in sub_nodes
        and (include_soft or e.relation_type == HARD)
    ])

    order, remaining = topological_sort(sub)
    if order is None:
        return {"ok": False, "error": "子图存在环，无法生成有序路径", "in_cycle": remaining}

    lookup = graph.edge_lookup()
    steps = []
    for i, node in enumerate(order, start=1):
        # 该节点在路径中依赖了哪些更强的前置
        prereqs = []
        for pre in sub.reverse_adjacency().get(node, []):
            e = lookup.get((pre, node))
            if e:
                prereqs.append({
                    "prereq_name": pre,
                    "relation_type": e.relation_type,
                    "reason": e.reason,
                    "confidence": e.confidence,
                })
        steps.append({
            "order": i,
            "knowledge_point": node,
            "is_start_point": not prereqs,
            "is_target": node == target,
            "breadth": depth.get(node),
            "prerequisites": sorted(prereqs, key=lambda x: x["prereq_name"]),
        })

    return {
        "ok": True,
        "target": target,
        "include_soft": include_soft,
        "total_steps": len(steps),
        "start_points": [s["knowledge_point"] for s in steps if s["is_start_point"]],
        "topologically_sorted": True,
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# 算法 3：卡点根因回溯
# ---------------------------------------------------------------------------

def gap_analysis(
    graph: Graph,
    target: str,
    misconception_hits: Iterable[str] = (),
) -> dict[str, Any]:
    """学生在 target 上卡住时，沿 hard 边反向回溯，定位最可能的断层前置。

    启发式排序（全部可解释，不是黑盒打分）：
        1. 命中误区的知识点优先（学生本轮确实在这一点上暴露了问题）
        2. 其次按「断层深度」—— 越深（离 target 越远）越可能是根因，
           因为深处的断层会连锁影响整条链
        3. 同级时，被依赖次数多的（越基础）优先
    """
    hits = set(misconception_hits)
    path = learning_path(graph, target, include_soft=False)
    if not path.get("ok"):
        return path

    steps = path["steps"]
    # 「被依赖次数」= 出边数（有多少知识点依赖它），不是入边数 —— 后者数的是它自己的前置
    _, outdeg = graph.degrees()

    candidates = []
    for s in steps:
        kp = s["knowledge_point"]
        if kp == target:
            continue
        candidates.append({
            "knowledge_point": kp,
            "breadth_from_target": s["breadth"],
            "depended_by_count": outdeg.get(kp, 0),
            "misconception_hit": kp in hits,
        })

    def sort_key(c: dict[str, Any]) -> tuple[int, int, int, str]:
        return (
            0 if c["misconception_hit"] else 1,   # 命中误区优先
            -(c["breadth_from_target"] or 0),     # 断层越深越优先
            -c["depended_by_count"],              # 越基础越优先
            c["knowledge_point"],                 # 稳定排序
        )

    ranked = sorted(candidates, key=sort_key)

    if not ranked:
        return {
            "ok": True,
            "target": target,
            "likely_gap": None,
            "message": f"「{target}」没有 hard 前置，它本身就是起点知识点 —— 卡点就在它自身，"
                       f"建议直接回到该知识点本身而非回头补其他内容。",
            "candidates": [],
        }

    top = ranked[0]
    reason_bits = []
    if top["misconception_hit"]:
        reason_bits.append("本轮回答中命中了该知识点的常见误区")
    if (top["breadth_from_target"] or 0) >= 2:
        reason_bits.append(f"它距目标有 {top['breadth_from_target']} 层依赖，属于断层较深的位置")
    if top["depended_by_count"] >= 2:
        reason_bits.append(f"后续有 {top['depended_by_count']} 个知识点依赖它，是关键地基")
    if not reason_bits:
        reason_bits.append("它是目标最近的硬前置，且未发现更深层的断层")

    return {
        "ok": True,
        "target": target,
        "likely_gap": top,
        "why": reason_bits,
        "message": f"你这一题卡在「{target}」，但根因更可能是「{top['knowledge_point']}」没吃透 —— "
                   f"建议先回去补它，再回来学目标知识点。",
        "candidates": ranked,
    }


# ---------------------------------------------------------------------------
# 算法 4：图完整性校验（对应 B1-2 / B1-5）
# ---------------------------------------------------------------------------

def verify(graph: Graph) -> dict[str, Any]:
    indeg, outdeg = graph.degrees()
    order, remaining = topological_sort(graph)

    missing_reason = [
        {"prereq_name": e.src, "dependent_name": e.dst}
        for e in graph.active_edges() if not e.reason.strip()
    ]
    sparsity_violations = [
        {"node": n, "in_degree": indeg.get(n, 0), "out_degree": outdeg.get(n, 0)}
        for n in sorted(graph.nodes)
        if indeg.get(n, 0) > MAX_IN_DEGREE or outdeg.get(n, 0) > MAX_OUT_DEGREE
    ]
    self_loops = [
        {"node": e.src} for e in graph.active_edges() if e.src == e.dst
    ]

    total = len(graph.active_edges())
    ok_reason_rate = 1.0 if total == 0 else (total - len(missing_reason)) / total

    # 孤立节点：既无入边也无出边。可能是「本来就是地基知识点」（正常），
    # 也可能是「抽取时漏了边」（缺陷）—— 必须显式列出由人工判断，不能默认忽略。
    isolated = [
        n for n in sorted(graph.nodes)
        if indeg.get(n, 0) == 0 and outdeg.get(n, 0) == 0
    ]
    no_prereq = [
        n for n in sorted(graph.nodes)
        if indeg.get(n, 0) == 0 and outdeg.get(n, 0) > 0
    ]

    return {
        "node_count": len(graph.nodes),
        "edge_count": total,
        "hard_edge_count": sum(1 for e in graph.active_edges() if e.relation_type == HARD),
        "soft_edge_count": sum(1 for e in graph.active_edges() if e.relation_type == SOFT),
        "pruned_edge_count": sum(1 for e in graph.edges if e.pruned),
        "cycle_count": 0 if order is not None else 1,
        "nodes_in_cycle": remaining,
        "self_loops": self_loops,
        "reason_complete_rate": round(ok_reason_rate, 4),
        "missing_reason": missing_reason,
        "sparsity_ok": not sparsity_violations,
        "sparsity_violations": sparsity_violations,
        "max_in_degree": max(indeg.values()) if indeg else 0,
        "max_out_degree": max(outdeg.values()) if outdeg else 0,
        "isolated_nodes": isolated,
        "no_prereq_nodes": no_prereq,
        "checks": {
            "B1-2_cycle_zero": order is not None,
            "B1-5_reason_complete": len(missing_reason) == 0,
            "no_self_loop": len(self_loops) == 0,
            "sparsity_within_limit": not sparsity_violations,
            "no_isolated_node": len(isolated) == 0,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dump(obj: Any, path: str | None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"[wrote] {path}")
    else:
        print(text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="graph_infer",
        description="析知 · 知识依赖图推理器（纯确定性算法，零模型依赖）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, help_text in [
        ("verify", "图完整性校验：环数 / 稀疏性 / reason 完备率"),
        ("prune", "环路检测与剪枝（软删除，保留可解释记录）"),
        ("path", "学习路径生成（沿 hard 边反向可达 + 拓扑排序）"),
        ("gap", "卡点根因回溯"),
    ]:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--input", required=True, help="P10 契约输出的 JSON 文件")
        sp.add_argument("--out", help="结果写入文件（省略则打印到 stdout）")
        if name in ("path", "gap"):
            sp.add_argument("--target", required=True, help="目标知识点名称")
        if name == "path":
            sp.add_argument("--include-soft", action="store_true", help="把软前置也纳入路径")
        if name == "gap":
            sp.add_argument("--misconception", nargs="*", default=[],
                            help="本轮命中误区的知识点名称（可多个）")

    args = p.parse_args(argv)
    graph = Graph.from_payload(_load(args.input))

    if args.cmd == "verify":
        _dump(verify(graph), args.out)
    elif args.cmd == "prune":
        result = prune_cycles(graph)
        result["edges_after_prune"] = [e.to_dict() for e in graph.edges]
        result["verify_after_prune"] = verify(graph)
        _dump(result, args.out)
    elif args.cmd == "path":
        _dump(learning_path(graph, args.target, include_soft=args.include_soft), args.out)
    elif args.cmd == "gap":
        _dump(gap_analysis(graph, args.target, misconception_hits=args.misconception), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
