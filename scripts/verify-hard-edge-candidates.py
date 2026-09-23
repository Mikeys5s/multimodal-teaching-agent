#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验 hard 边候选**能否安全导入**（整批 + 逐条），并给出可直接执行的结论。

用法：
    python scripts/verify-hard-edge-candidates.py --api http://120.77.177.171:8000 \
        --candidates docs/graph/hard-edge-candidates.json

为什么需要它：
    `POST /api/review/import-edges` 的第三道校验是「**成环则整批拒收**」——
    这是对的设计（B1-2「环数 0」是工程不变量），但它的副作用是：
    **候选里只要有 1 条与现有边冲突，整批都进不去**，而且报错不告诉你"要拿掉哪一条"。

    本脚本就是补这个缺口：告诉你 **哪几条能灌、哪几条不能、以及拿掉后剩下的能不能整批过**。

⚠️ 两道防"真空满足"的护栏（本项目踩过 4 次同类问题，所以写死在脚本里）：
    1. **基线边数为 0 或过少 → 直接退出**（基线为空时"逐条都不成环"是必然会发生的假通过）；
    2. **先核对边方向约定**（`graph` 的 source/target 与 `review/queue` 的 prereq/kp 必须同向），
       方向若反了，整张基线就是错的、结论也就反了。

⚠️ 已知坑：`GET /api/knowledge-graph` 的 `max_nodes` **会决定返回哪个子图**
    （实测 `1000 → 625 边/629 节点`、`400 → 396`、`200 → 196`），
    所以本脚本固定用较大的值并**打印实际取到多少**，避免"拿子图当全图"。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

# ⚠️ 本机控制台是 GBK，输出里有 ✅/❌ 等字符 —— 不设这个会直接 UnicodeEncodeError 崩掉
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def http_json(url: str, timeout: int = 60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def load_candidates(path: str) -> list[dict]:
    """支持本地路径或 URL；容忍几种常见的顶层结构。"""
    if path.startswith("http"):
        raw = http_json(path)
        return _pick_list(raw)
    with open(path, encoding="utf-8") as f:
        return _pick_list(json.load(f))


def _pick_list(obj) -> list[dict]:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in ("edges", "candidates", "items", "data"):
            if isinstance(obj.get(k), list):
                return obj[k]
        for v in obj.values():
            if isinstance(v, list):
                return v
    raise SystemExit("!! 解析不出候选列表（顶层既不是 list，也没有 edges/candidates/items/data 字段）")


def fetch_existing_edges(api: str) -> tuple[dict, list[str]]:
    """多路取并集：review/queue（显式 prereq/kp）+ knowledge-graph（source/target）。"""
    edges: dict[str, dict] = {}
    tried: list[str] = []
    for lim in (200, 500):
        try:
            d = http_json("%s/api/review/queue?%s" % (api, urllib.parse.urlencode({"limit": lim})))
            items = (d.get("data") or {}).get("items") or []
            tried.append("queue?limit=%s → %d 条" % (lim, len(items)))
            for e in items:
                if e.get("prereq_kp_id") and e.get("kp_id"):
                    edges["%s|%s" % (e["prereq_kp_id"], e["kp_id"])] = e
        except Exception as exc:  # noqa: BLE001
            tried.append("queue?limit=%s → %s" % (lim, type(exc).__name__))
    for mn in (1000, 400):
        try:
            d = http_json("%s/api/knowledge-graph?%s" % (api, urllib.parse.urlencode({"max_nodes": mn})))
            data = d.get("data") or {}
            es = data.get("edges") or []
            tried.append("graph?max_nodes=%s → %d 边 / %d 节点" % (mn, len(es), len(data.get("nodes") or [])))
            for e in es:
                if e.get("source") and e.get("target"):
                    edges.setdefault("%s|%s" % (e["source"], e["target"]), {
                        "prereq_kp_id": e["source"], "kp_id": e["target"],
                        "relation_type": e.get("relation_type"),
                    })
        except Exception as exc:  # noqa: BLE001
            tried.append("graph?max_nodes=%s → %s" % (mn, type(exc).__name__))
    return edges, tried


def check_direction(api: str, edges: dict) -> tuple[int, int]:
    """graph 的 source/target 是否与 queue 的 prereq/kp 同向。"""
    g_pairs = set()
    try:
        d = http_json("%s/api/knowledge-graph?max_nodes=1000" % api)
        for e in (d.get("data") or {}).get("edges") or []:
            g_pairs.add("%s|%s" % (e.get("source"), e.get("target")))
    except Exception:  # noqa: BLE001
        pass
    try:
        d = http_json("%s/api/review/queue?limit=200" % api)
        items = (d.get("data") or {}).get("items") or []
    except Exception:  # noqa: BLE001
        items = []
    same = rev = 0
    for it in items:
        if "%s|%s" % (it.get("prereq_kp_id"), it.get("kp_id")) in g_pairs:
            same += 1
        elif "%s|%s" % (it.get("kp_id"), it.get("prereq_kp_id")) in g_pairs:
            rev += 1
    return same, rev


def has_cycle(pairs) -> tuple[bool, int]:
    """Kahn；返回 (是否有环, 环内节点数)。"""
    indeg: dict[str, int] = defaultdict(int)
    adj: dict[str, list[str]] = defaultdict(list)
    nodes: set[str] = set()
    for p, k in pairs:
        adj[p].append(k)
        indeg[k] += 1
        nodes.add(p)
        nodes.add(k)
    for n in nodes:
        indeg.setdefault(n, 0)
    q = [n for n in nodes if indeg[n] == 0]
    seen = 0
    while q:
        n = q.pop()
        seen += 1
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    return (seen != len(nodes)), (len(nodes) - seen)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://120.77.177.171:8000")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--min-baseline", type=int, default=100, help="基线边数低于此值直接退出（防真空）")
    args = ap.parse_args()

    print("=" * 92)
    print("① 取现有边（多路并集）")
    print("=" * 92)
    edges, tried = fetch_existing_edges(args.api)
    for t in tried:
        print("   %s" % t)
    base = [(e["prereq_kp_id"], e["kp_id"]) for e in edges.values()]
    print("   **去重后基线 = %d 条边**" % len(base))

    # 护栏 1
    if len(base) < args.min_baseline:
        print("")
        print("   🔴 基线只有 %d 条（< %d）→ **结论一律不可信，直接退出**。" % (len(base), args.min_baseline))
        print("      基线为空时，任何候选都会显示「不成环」——那是真空满足。")
        return 2

    print("")
    print("② 方向约定核对（不能靠假设）")
    same, rev = check_direction(args.api, edges)
    print("   queue 与 graph 同向 %d 条 / 反向 %d 条" % (same, rev))
    if rev > same:
        print("   ⚠️ 反向多于同向 → graph 的 source/target 与 queue 的 prereq/kp **相反**，已在内存中翻转基线")
        base = [(b, a) for (a, b) in base]
    else:
        print("   ✅ 约定一致（source=前置, target=后置）")

    cyc, n_in = has_cycle(base)
    print("   基线自检：has_cycle=%s（环内 %d）← 期望 False" % (cyc, n_in))
    if cyc:
        print("   🔴 基线自身有环 → 方向约定仍不对，结论不可信，退出")
        return 3

    print("")
    print("③ 候选逐条 + 整批")
    cands = load_candidates(args.candidates)
    pairs_all = []
    print("   候选 %d 条" % len(cands))
    for i, c in enumerate(cands, 1):
        p, k = c.get("prereq_kp_id"), c.get("kp_id")
        if not p or not k:
            print("   [%2d] ⚠️ 缺 prereq_kp_id / kp_id，跳过" % i)
            continue
        pairs_all.append((p, k))

    cyc_all, n_all = has_cycle(base + pairs_all)
    print("   整批（基线+%d）→ has_cycle=**%s**（环内 %d）" % (len(pairs_all), cyc_all, n_all))

    # 逐条累计，遇环即排除并继续 —— 找出全部触发者
    acc = list(base)
    triggers, kept = [], []
    for i, (p, k) in enumerate(pairs_all, 1):
        cy, n = has_cycle(acc + [(p, k)])
        if cy:
            triggers.append((p, k))
            print("   [%2d] ❌ 触发者（排除）  %s → %s" % (i, p[-14:], k[-14:]))
        else:
            acc.append((p, k))
            kept.append((p, k))
            print("   [%2d] ✅ 可灌            %s → %s" % (i, p[-14:], k[-14:]))

    print("")
    print("=" * 92)
    print("④ 结论")
    print("=" * 92)
    print("   可灌 = **%d 条**；需排除 = **%d 条**" % (len(kept), len(triggers)))
    cy3, n3 = has_cycle(base + kept)
    if not cy3:
        print("   ✅ 排除触发者后，**基线 + 这 %d 条一起灌不会成环** → 可整批 import-edges" % len(kept))
        print("   ⚠️ 需删的现有边 = 0 条、需改的数据模型 = 无（纯过滤）")
    else:
        print("   ⚠️ 仍有环（环内 %d）→ 触发者之间也会互相成环，需迭代排除" % n3)
    if triggers:
        print("")
        print("   被排除的边（**不要丢**，可作为人工复核的演示素材）：")
        for p, k in triggers:
            print("      · %s → %s" % (p, k))
    return 0


if __name__ == "__main__":
    sys.exit(main())
