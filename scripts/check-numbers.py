#!/usr/bin/env python3
"""录制 / 答辩前的数据口径核验。

**为什么需要它**：文档、PPT、演示脚本里写死的数字会过期 ——
数据显示，同一天 08:00 与 09:15 两次读取，QA 会话数就从 83 涨到 119。
带着过期数字上镜，是最容易在答辩现场被抓的一类硬伤。

用法：
    python scripts/check-numbers.py                       # 用默认演示地址
    XIZHI_BASE=http://127.0.0.1:8000 python scripts/check-numbers.py

退出码：0 = 不变量全部成立；1 = 有不变量被破坏（必须是 0 的项非 0）
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("XIZHI_BASE", "http://120.77.177.171:8000").rstrip("/")

# 只用标准库，且显式禁用代理 —— 内网/演示机常因代理变量导致请求失败
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path: str, **params) -> dict:
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    with _opener.open(url, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def main() -> int:
    print(f"数据口径核验 · {BASE}\n")

    try:
        quality = get("/api/report/quality")["data"]
        graph = get("/api/knowledge-graph", max_nodes=1000)["data"]["stats"]
        kp = get("/api/knowledge-points", page=1, page_size=1)["data"]
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        print(f"[!!] 取不到数据：{exc}")
        print("     确认服务已启动；若走了代理，请设置 XIZHI_BASE 指向可直连的地址。")
        return 1

    print("── 随数据变更（不要写进文档的硬数字）")
    print(f"   知识点条目数        {kp['total']}")
    print(f"   节点 / 边           {graph['node_count']} / {graph['edge_count']}")
    print(f"   hard / soft 边      {graph['hard_edge_count']} / {graph['soft_edge_count']}")
    print(f"   未经人复核的边      {graph['conflict_count']}")
    print(f"   材料 总数 / 完成    {quality['materials']['total']} / {quality['materials']['done']}")
    print(f"   平均质量分          {quality['materials']['avg_quality_score']}")

    print("\n── 随使用增长（同样不要写死）")
    print(f"   QA 会话 / 轮次      {quality['qa']['session_count']} / {quality['qa']['turn_count']}")
    print(f"   其中拒答            {quality['qa']['refuse_count']}")

    print("\n── 工程不变量（**可以写死，也是要承诺的**）")
    checks: list[tuple[str, bool, str]] = []

    checks.append(("依赖图环数为 0", graph["cycle_count"] == 0, f"实测 {graph['cycle_count']}"))
    checks.append(
        (
            "溯源覆盖率 = 1.0",
            quality["knowledge_points"]["grounding_rate"] == 1.0,
            f"实测 {quality['knowledge_points']['grounding_rate']}",
        )
    )
    checks.append(
        (
            "三级结构完整率 = 1.0",
            quality["knowledge_points"]["structure_complete_rate"] == 1.0,
            f"实测 {quality['knowledge_points']['structure_complete_rate']}",
        )
    )
    checks.append(
        (
            "五项字段完整率 = 1.0",
            quality["knowledge_points"]["five_field_complete_rate"] == 1.0,
            f"实测 {quality['knowledge_points']['five_field_complete_rate']}",
        )
    )

    passed = 0
    for label, ok, detail in checks:
        print(f"   [{'PASS' if ok else 'FAIL'}] {label:<22} {detail}")
        passed += ok
    print(f"   → {passed}/{len(checks)} 项成立")

    print("\n── 接口自报的验收项")
    for item in quality["acceptance"]:
        mark = "PASS" if item["passed"] else "FAIL"
        print(
            f"   [{mark}] {item['label']:<28} "
            f"expected={item['expected']:<5} actual={item['actual']:<5} n={item['sample_size']}"
        )

    print("\n提示：`/graph` 前端默认 max_nodes=200 —— 面板显示的是**子图**统计，不是全图。")
    print("      录制前要么把节点上限拉满，要么按面板实际显示的数字讲。")

    if passed != len(checks):
        print("\n[!!] 不变量被破坏，先查清再录。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
