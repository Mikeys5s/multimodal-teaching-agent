#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B1-3 学习路径拓扑有序率 —— 带「非真空」判据的验收检查。

SPEC §7.5 B1-3：**抽 10 个目标知识点，检查路径中任一节点都不依赖其后面的节点**，目标 100%。

用法：
    python scripts/check-b1-3-path-order.py --api http://120.77.177.171:8000

⚠️ 为什么这个脚本必须内置"非真空"判据（这是本项目的真实教训）：
    「路径内部一条约束边都没有」时，「有序」是**自动成立**的 ——
    此时的 100% **没有任何信息量**，它只说明**没有约束可违反**。
    ⇒ 所以本脚本同时报告：
        ① 有序率          ② **路径内约束边数**（=0 则该点无信息量）
        ③ **有效样本数**   ④ 「不可测」的明确结论
    只有「有效样本 ≥ N 且 无逆序」才算通过。

⚠️ 抽样口径（两版之间的取舍，都是踩出来的）：
    v1 抽「有前置的点」→ 但**如果抽到的点恰好是根节点**，路径必然 1 步，检查真空。
    v2（本脚本）**只抽「有 hard 入边的点」**，并按各材料的 hard 边数加权分配名额 ——
       否则会出现「抽的 10 个点全来自没有 hard 边的材料」→ 又变成不可测。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

# ⚠️ 本机控制台是 GBK，而下面的输出里有 ✅/❌ —— 不设这个会直接 UnicodeEncodeError 崩掉
#    （2026-09-23 实测：Windows PowerShell 下跑到第 121 行 print 就抛 'gbk' codec can't encode '\u2705'）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def http_json(url: str, timeout: int = 60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_graph(api: str, max_nodes: int = 1000):
    d = http_json("%s/api/knowledge-graph?%s" % (api, urllib.parse.urlencode({"max_nodes": max_nodes})))
    data = d.get("data") or {}
    return data.get("nodes") or [], data.get("edges") or [], data.get("stats") or {}


def fetch_path(api: str, kp_id: str):
    d = http_json("%s/api/learning-path?%s" % (api, urllib.parse.urlencode({"kp_id": kp_id})))
    data = d.get("data")
    if isinstance(data, list):
        return data
    return (data or {}).get("steps") or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://120.77.177.171:8000")
    ap.add_argument("--sample", type=int, default=10, help="抽样目标点数（SPEC 写 10）")
    ap.add_argument("--min-effective", type=int, default=3,
                    help="有效样本下限；低于此值整项记「不可测」而不是「通过」")
    args = ap.parse_args()

    nodes, edges, stats = fetch_graph(args.api)
    print("=" * 92)
    print("B1-3 学习路径拓扑有序率")
    print("=" * 92)
    print("   图：节点 %d / 边 %d；stats: hard=%s soft=%s cycle=%s" % (
        len(nodes), len(edges), stats.get("hard_edge_count"), stats.get("soft_edge_count"),
        stats.get("cycle_count")))

    # 前置集合（source=前置 → target=后置）
    prereq_of: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e.get("source") and e.get("target"):
            prereq_of[e["target"]].add(e["source"])
    hard_edges = [e for e in edges if e.get("relation_type") == "hard"]
    print("   **hard 边 %d 条**（只有 hard 约束先后；为 0 时本项必然不可测）" % len(hard_edges))

    # 抽样：只从「有 hard 入边的点」里抽，按材料加权
    hard_targets = defaultdict(list)
    for e in hard_edges:
        k = e.get("target")
        if k:
            mid = k.split("_")[1] if k.startswith("kp_") and len(k.split("_")) > 1 else "?"
            hard_targets[mid].append(k)
    total = sum(len(v) for v in hard_targets.values())
    print("   有 hard 入边的点：%d 个，分布 = %s" % (
        total, {m: len(v) for m, v in sorted(hard_targets.items())}))

    targets: list[str] = []
    if total == 0:
        print("")
        print("   🔴 **没有任何点有 hard 入边** → 无法抽样，B1-3 记「**不可测**」（不是「通过」）")
        print("      根因通常是「库里没有 hard 边」（见 Issue #94 / #103）。")
        return 0
    # 按材料占比分配名额（至少 1）
    for mid, lst in sorted(hard_targets.items()):
        quota = max(1, round(args.sample * len(lst) / total))
        targets.extend(sorted(lst)[:quota])
    targets = targets[: args.sample]
    print("   抽样 %d 个目标点：%s" % (len(targets), ", ".join(t[-14:] for t in targets)))

    print("")
    print("③ 逐点检查")
    print("-" * 92)
    ordered_ok = effective = 0
    rows = []
    for kp in targets:
        steps = fetch_path(args.api, kp)
        ids = [s.get("kp_id") for s in steps if s.get("kp_id")]
        pos = {k: i for i, k in enumerate(ids)}
        in_path = 0
        viol = []
        for k in ids:
            for p in prereq_of.get(k) or ():
                if p in pos:
                    in_path += 1
                    if pos[p] > pos[k]:
                        viol.append((p, k))
        ok = not viol
        ordered_ok += 1 if ok else 0
        effective += 1 if in_path > 0 else 0
        rows.append((kp, len(ids), in_path, len(viol)))
        print("   %-34s 步数=%-3d 路径内约束边=%-3d 逆序=%-2d %s%s" % (
            kp, len(ids), in_path, len(viol),
            "✅" if ok else "❌",
            "" if in_path else "  ← 无约束边，该点无信息量"))

    print("")
    print("=" * 92)
    print("④ 结论（**含非真空判据**）")
    print("=" * 92)
    print("   抽样 %d 个；有序 %d 个" % (len(targets), ordered_ok))
    print("   **有效样本（路径内 ≥1 条约束边）= %d**" % effective)
    print("   路径内约束边合计 = %d" % sum(r[2] for r in rows))
    print("")
    if effective < args.min_effective:
        print("   🔴 **记「不可测」，不记「通过」** —— 有效样本 %d < %d。" % (effective, args.min_effective))
        print("      「路径内没有约束边」时，『有序』是自动成立的，这个数字没有信息量。")
        return 0
    if ordered_ok == len(targets):
        print("   ✅ B1-3 通过（且**非真空**：有效样本 %d，路径内共 %d 条约束边，无逆序）" % (
            effective, sum(r[2] for r in rows)))
        return 0
    print("   ❌ B1-3 未通过：%d 个点存在逆序" % (len(targets) - ordered_ok))
    return 1


if __name__ == "__main__":
    sys.exit(main())
