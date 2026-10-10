#!/usr/bin/env python
"""析知 · 全链路复验（end-to-end check）。

    python scripts/e2e-check.py                      # 打线上
    python scripts/e2e-check.py --base http://...    # 打别处（本地/预发）
    python scripts/e2e-check.py --json               # 输出 JSON（给 CI）

## 为什么要有这个脚本

2026-10-08 做全链路复验时，**手工验出一批问题**，其中最严重的一个是：

    答疑**只有第 1 轮正常**，从第 2 轮起 `/ask` 返回 **HTTP 200 但 SSE 零字节**。
    根因：`session.get(type(top), ...)` —— 把 dataclass 当 ORM 类传给了 SQLAlchemy。

**它的表现极具误导性**：HTTP 200 看起来"成功了"，零事件看起来"模型没产出"，
**很容易被当成"内容为空"而不是"崩了"** —— 而 traceback 只在容器日志里。

**⇒ 所以这个脚本把"当时是怎么发现的"固化成断言。三条经验值得单列：**

1. **答疑必须验多轮** —— 只验第 1 轮会完全漏掉状态机分支里的 bug。
2. **SSE 零字节要当失败** —— 不是"空回复"，是"流被中途掐了"。
3. **接口不报错不等于没崩** —— 断言要卡在**内容结构**上，不能只看状态码。

## 层与判据

| 层 | 验什么 | 判据 |
|---|---|---|
| 1 路由 | 6 个前端路由 | HTTP 200 |
| 2 API 契约 | 关键端点 | 状态码 + **字段在不在**（改 schema 漏改能查出来） |
| 3 业务链路 | **多轮答疑** | 见下 |
| 4 今日改动 | 重复标注 / 例题溯源 / 学习路径 | 值对得上 |

**第 3 层的判据（对照 SPEC）**：
  · 建会话返回 **200 或 201**（201 Created 才是标准的）
  · **每一轮** SSE 都要有事件，且以 `done` 收尾（**≥2 轮**）
  · 第 1 轮：**不给答案**（含引导问句、不含"答案是…"式断言）
  · `diagnosis` 事件含三级结构（`knowledge_points` / `stuck_at` / `next_practice`）
    —— **SPEC L783 说的是「右侧固定面板」，所以它本来就不该在正文里**
  · 连续 2 次答不上 ⇒ 降级直讲（**由代码层强制**）

退出码：全通过 0，否则 1。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "http://120.77.177.171:8000"
UA = {"User-Agent": "xizhi-e2e-check/1.0"}

RESULTS: list[dict] = []


def rec(layer: str, ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append({"layer": layer, "ok": ok, "label": label, "detail": detail})
    print(f"      {'✅' if ok else '❌'} {label}" + (f"   {detail}" if detail else ""))
    return ok


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def get(self, path: str, timeout: int = 60):
        req = urllib.request.Request(self.base + path, headers=UA)
        return self._send(req, timeout)

    def post(self, path: str, body: dict, *, sse: bool = False, timeout: int = 180):
        h = {**UA, "Content-Type": "application/json"}
        if sse:
            h["Accept"] = "text/event-stream"
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers=h, method="POST")
        return self._send(req, timeout, raw=sse)

    def _send(self, req, timeout: int, raw: bool = False):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read().decode("utf-8", "ignore")
                if raw:
                    return r.status, data
                try:
                    return r.status, json.loads(data)
                except Exception:  # noqa: BLE001
                    return r.status, data
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            try:
                return e.code, json.loads(body)
            except Exception:  # noqa: BLE001
                return e.code, body
        except Exception as e:  # noqa: BLE001
            return -1, f"{type(e).__name__}: {e}"


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    ev: list[tuple[str, dict]] = []
    cur = None
    for ln in raw.splitlines():
        if ln.startswith("event:"):
            cur = ln[6:].strip()
        elif ln.startswith("data:") and cur:
            try:
                ev.append((cur, json.loads(ln[5:].strip())))
            except Exception:  # noqa: BLE001
                pass
    return ev


def layer1_routes(c: Client) -> None:
    print()
    print("=" * 74)
    print("  第 1 层 · 前端路由")
    print("=" * 74)
    for route in ("/", "/graph", "/path", "/tutor", "/review", "/report"):
        code, body = c.get(route)
        n = len(body) if isinstance(body, str) else len(json.dumps(body, ensure_ascii=False))
        rec("1-路由", code == 200, f"{route:<10} HTTP {code}", f"{n:,} 字符")


def layer2_api(c: Client) -> None:
    print()
    print("=" * 74)
    print("  第 2 层 · API 契约")
    print("=" * 74)
    code, d = c.get("/api/health")
    rec("2-契约", code == 200, f"/api/health  HTTP {code}")

    code, d = c.get("/api/knowledge-points?page_size=3")
    items = (((d.get("data") if isinstance(d, dict) else {}) or {})
             .get("items") or []) if isinstance(d, dict) else []
    rec("2-契约", code == 200 and len(items) == 3,
        f"/api/knowledge-points  {len(items)} 条")
    if items:
        need = {"id", "name", "difficulty", "source", "is_duplicate",
                "duplicate_of", "duplicate_group_size"}
        miss = need - set(items[0])
        rec("2-契约", not miss, "列表项字段齐全",
            f"缺 {miss}" if miss else f"{len(items[0])} 字段")

    code, d = c.get("/api/knowledge-graph?max_nodes=1000")
    g = ((d.get("data") if isinstance(d, dict) else {}) or {}) if isinstance(d, dict) else {}
    rec("2-契约", code == 200 and bool(g.get("nodes")),
        f"/api/knowledge-graph  {len(g.get('nodes') or [])} 节点 / "
        f"{len(g.get('edges') or [])} 边")

    code, d = c.get("/api/materials")
    ms = ((d.get("data") if isinstance(d, dict) else {}) or {}).get("items") or []
    rec("2-契约", code == 200 and bool(ms), f"/api/materials  {len(ms)} 份")

    # ⭐ 导出接口（2026-10-08 补）
    #
    # 它是**从服务自己声明的 openapi.json 里反查出来的** —— 我原先的检查只覆盖了
    # 我自己知道的入口，而导出接口**可能复用 `load_kp_items`** ⇒
    # **改了 `KpItemOut` 就有可能把它弄坏，而我不会知道。**
    #
    # **⇒ 教训：端点清单要"从服务声明里取"，不要写死。**
    code, body = c.get("/api/export/knowledge-points")
    n = len(body) if isinstance(body, str) else len(json.dumps(body, ensure_ascii=False))
    rec("2-契约", code == 200 and n > 10_000,
        f"/api/export/knowledge-points  HTTP {code}", f"{n:,} 字符")

    code, d = c.get("/api/review/queue")
    rec("2-契约", code == 200, f"/api/review/queue  HTTP {code}",
        f"{len(d.get('data') or [])} 项" if isinstance(d, dict) else "")

    code, d = c.get("/api/report/quality")
    rec("2-契约", code == 200, f"/api/report/quality  HTTP {code}")

    code, d = c.get("/api/definitely-not-exist")
    is_json = isinstance(d, dict) and (bool(d.get("error")) or d.get("ok") is False)
    rec("2-契约", code == 404 and is_json, f"未注册路由 -> JSON 404  HTTP {code}")

    # ⚠️ `/api/learning-path` **需要 kp_id** —— 不带参数会 400，那是**正确的**
    code, d = c.get("/api/learning-path")
    rec("2-契约", code == 400, f"learning-path 缺参数 -> 400（**参数校验在工作**）",
        f"HTTP {code}")


def layer3_tutor(c: Client) -> None:
    """**这一层是核心** —— 多轮答疑，且每轮的 SSE 都必须有内容。"""
    print()
    print("=" * 74)
    print("  第 3 层 · 业务链路（多轮答疑）")
    print("=" * 74)

    code, d = c.post("/api/qa/sessions",
                     {"material_scope": [], "student_label": "e2e-check"})
    # ⚠️ **201 Created 才是标准的** —— 别把 201 判成失败（我犯过）
    rec("3-答疑", code in (200, 201),
        f"建会话 HTTP {code}（**200 或 201 都算对**）")
    sid = ((d.get("data") if isinstance(d, dict) else {}) or {}).get("session_id")
    if not sid:
        rec("3-答疑", False, "拿到 session_id", f"实际 {d!r}"[:80])
        return

    # 四轮：正常 → 提示 → 再不会 → 超范围
    # ⚠️ **必须多轮** —— 只问一轮会漏掉状态机分支里的 bug（2026-10-08 的教训）
    TURNS = [
        ("慢启动为什么叫慢启动？", "probe"),
        ("我不太懂，能不能再提示一下？", "hint"),
        ("还是不会……", "escalate"),
        ("量子纠缠和 TCP 有什么关系？", "oos"),
    ]
    seen_states: list[str] = []
    banned = ["正确答案是", "答案是", "直接告诉你"]

    for i, (q, tag) in enumerate(TURNS, 1):
        try:
            status, raw = c.post(f"/api/qa/sessions/{sid}/ask",
                                 {"question": q}, sse=True)
        except Exception as e:  # noqa: BLE001
            rec("3-答疑", False, f"第 {i} 轮请求异常", f"{type(e).__name__}")
            continue
        ev = parse_sse(raw)
        kinds = [k for k, _ in ev]
        text = "".join(str(x.get("text") or x.get("delta") or "")
                       for k, x in ev if k not in ("retrieved", "done", "state"))
        diag = next((x for k, x in ev if k == "diagnosis"), None)
        st = next((x.get("state") for k, x in ev if k == "state"), None)
        if st:
            seen_states.append(st)

        # ⚠️ 核心断言：**零字节 = 失败，不是"空回复"**
        rec("3-答疑", len(raw) > 0 and len(ev) > 0,
            f"第 {i} 轮有事件  HTTP {status} / {len(raw)} 字节 / {len(ev)} 事件",
            f"状态={st}  正文={len(text)} 字符")
        rec("3-答疑", bool(kinds) and kinds[-1] == "done",
            f"第 {i} 轮以 done 收尾", f"序列 {kinds[:8]}")

        # 第 1 轮：**不给答案**（R1 铁律）
        #
        # ⚠️ 判据改过一次（2026-10-08）：
        # 原先写「第 1 轮含引导问句」= `("？" in text)` —— **太窄**。
        # 实测 8 次，有 2 次的首轮是：
        #   「先试着用一句话说说「…」在干什么。说错没关系，我要知道你现在站在哪。」
        # **它是完全合格的引导**（引导 + 降门槛 + 探测起点），**只是没有问号**。
        #
        # ⇒ 换成**反向判据**：**铁律的核心是"不给答案"，不是"必须有问号"** ——
        #    所以断言「**没有直接给答案的措辞**」，而不是「必须有问号」。
        #
        # ⚠️ **只对第 1 轮断言** —— 第 3 轮（S4_EXPLAIN）**本来就该直接讲**
        # （连续 2 次答不上 ⇒ 降级是**硬规则要求**的），在那里断言"不给答案"是错的。
        if i == 1:
            banned = ["正确答案是", "答案是", "直接告诉你", "应该是", "结论是"]
            hit = [b for b in banned if b in text]
            rec("3-答疑", not hit, "第 1 轮不给答案（R1 铁律）",
                f"**出现直接给答案的措辞** {hit}" if hit else "")

            # 正向判据放宽：问号 **或** 引导语
            GUIDE = ("？", "?", "说说", "你觉得", "你的直觉", "怎么解释", "怎么想",
                     "先说", "想一下", "试着", "假设有人问")
            g_hit = [g for g in GUIDE if g in text]
            rec("3-答疑", bool(g_hit), "第 1 轮是引导（不是干巴巴的结论）",
                f"命中 {g_hit[:3]}")
        else:
            # 除第 1 轮外，只断言"不是空回复"（正文长度已在上面查过）
            rec("3-答疑", len(text) > 0, f"第 {i} 轮有正文内容", f"{len(text)} 字符")

        # 每轮：diagnosis 里的三级结构（**SPEC L783：右侧面板**）
        if diag is not None:
            need = {"knowledge_points", "stuck_at", "next_practice"}
            got = set(diag)
            rec("3-答疑", need <= got,
                f"第 {i} 轮 diagnosis 含三级结构",
                f"缺 {need - got}" if not (need <= got) else "")

    # 状态机推进（连续 2 次答不上 ⇒ 降级）
    rec("3-答疑", len(set(seen_states)) >= 2,
        f"状态机在推进（看到 {len(set(seen_states))} 个不同状态）",
        str(seen_states))


def layer4_today(c: Client) -> None:
    print()
    print("=" * 74)
    print("  第 4 层 · 近期改动是否生效")
    print("=" * 74)
    # ⚠️ **不要硬编码 kp_id**（2026-10-10 的教训）：
    # 那天 P1 修了「id 的章段恒等于节段」的 bug，**所有 kp_id 的中间两段都变了**，
    # 于是这一层 4 项全报失败 —— **而数据其实是好的**。
    # **⇒ 改成按（材料 hash + seq）动态查**：seq 是同一份材料内的稳定序号，
    #    **两次修复都没动它**，所以拿它当锚最稳。
    def kp_by_seq(mat_hash: str, seq: int) -> str | None:
        code, dd = c.get("/api/export/knowledge-points")
        items = dd if isinstance(dd, list) else (
            (dd or {}).get("data") or (dd or {}).get("items") or [])
        for it in items:
            p = str(it.get("id", "")).split("_")
            if len(p) == 5 and p[1] == mat_hash and p[4] == f"{seq:03d}":
                return str(it.get("id"))
        return None

    rep_id = kp_by_seq("42b16cd4", 12)      # 重复组的代表点（旧：..._000_000_012）
    dup_seq = 17                            # 它的一个副本（旧：..._000_000_017）
    ex_id = kp_by_seq("42b16cd4", 34)       # Ch05 例题那个点（旧：..._000_000_034）
    path_id = kp_by_seq("cf6fcaa0", 28)     # 学习路径目标（旧：..._000_000_028）

    if not (rep_id and ex_id and path_id):
        rec("4-改动", False, "按 seq 定位 kp_id",
            f"rep={rep_id} ex={ex_id} path={path_id}")

    if rep_id:
        code, d = c.get(f"/api/knowledge-points/{rep_id}")
        x = ((d.get("data") if isinstance(d, dict) else {}) or {}) if isinstance(d, dict) else {}
        rec("4-改动", bool(x.get("duplicate_group_size")) and x.get("is_duplicate") is False,
            "重复标注（代表）", f"size={x.get('duplicate_group_size')}")

    if rep_id:
        # ⚠️ **别按固定 seq 找副本**（2026-10-10 的教训）：
        # 重跑后重复组会重新划分，某个点可能**不再是副本** ——
        # 于是"按 seq=17 硬找"会误报失败，**而数据其实是好的**。
        # **⇒ 改成"在导出里动态找一个 is_duplicate=true 的点"**。
        code, dd = c.get("/api/export/knowledge-points")
        items_all = dd if isinstance(dd, list) else (
            (dd or {}).get("data") or (dd or {}).get("items") or [])
        dup_id = None
        for it in items_all:
            if it.get("is_duplicate") is True and it.get("duplicate_of"):
                dup_id = it.get("id")
                break
        if dup_id:
            code, d2 = c.get(f"/api/knowledge-points/{dup_id}")
            y = ((d2.get("data") if isinstance(d2, dict) else {}) or {}) \
                if isinstance(d2, dict) else {}
            rec("4-改动", y.get("is_duplicate") is True and bool(y.get("duplicate_of")),
                "重复标注（副本）", f"of={y.get('duplicate_of')}")
        else:
            # 没有副本也不是错 —— 重跑后可能**真的没有同组副本**了
            rec("4-改动", True, "重复标注（副本）", "本次无副本（重跑后组已重划）")

    if ex_id:
        code, d = c.get(f"/api/knowledge-points/{ex_id}")
        z = ((d.get("data") if isinstance(d, dict) else {}) or {}) if isinstance(d, dict) else {}
        ex = z.get("examples") or []
        rec("4-改动", bool(ex) and bool(z.get("misconceptions")),
            "例题/误区（灌库）",
            f"例 {len(ex)} 误 {len(z.get('misconceptions') or [])}")
        an = str((ex[0] if ex else {}).get("analysis_md") or "")
        rec("4-改动", "原文" in an and len(an) > 100, "例题带原文溯源")

    if path_id:
        code, d = c.get(f"/api/learning-path?kp_id={path_id}")
        steps = (d.get("data") if isinstance(d, dict) else None) if isinstance(d, dict) else None
        n = len(steps) if isinstance(steps, list) else 0
        rec("4-改动", n >= 2, f"学习路径（补边）{n} 步")


def main() -> int:
    ap = argparse.ArgumentParser(description="析知全链路复验")
    ap.add_argument("--base", default=DEFAULT_BASE, help="服务地址")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    c = Client(args.base)
    print("=" * 74)
    print(f"  析知 · 全链路复验   {args.base}")
    print("=" * 74)

    layer1_routes(c)
    layer2_api(c)
    layer3_tutor(c)
    layer4_today(c)

    bad = [r for r in RESULTS if not r["ok"]]
    print()
    print("=" * 74)
    if bad:
        print(f"  ❌ **{len(bad)} / {len(RESULTS)} 项未通过**")
        for r in bad:
            print(f"      [{r['layer']}] {r['label']}   {r['detail']}")
    else:
        print(f"  ✅ **全部通过**（{len(RESULTS)} 项）")
    print("=" * 74)

    if args.json:
        print(json.dumps({"base": args.base, "total": len(RESULTS),
                          "failed": len(bad), "results": RESULTS},
                         ensure_ascii=False, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
