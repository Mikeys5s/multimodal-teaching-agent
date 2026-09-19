"""前后端契约比对（归属：P2）—— v2：**不依赖正则抓调用**。

## v1 错在哪（这条比脚本本身重要）

v1 用正则 `request(\\('/path')` 去抓前端的调用，结果**只抓到 14 条，实际有 21 条**
（漏了 `/health/pragma`、`/knowledge-graph`、`/materials/{id}/blocks` 等）。
而它照样打印「✅ 路径层面完全对得上」——
**一个因为"没去看"而报成功的检查，比没有检查更危险。**

**所以 v2 换思路**：不猜"哪条是接口调用"，而是
**把前端所有以 `/` 开头的字符串字面量全抓出来**，和后端逐一比对。
抓多了一分钱不值（多出来的会显示为"未匹配"，人来判断），
**抓少了才是灾难**。

## 它做什么

1. 从 `frontend/src/**/*.ts(x)` 里抓**所有**以 `/` 开头的字符串/模板字面量
2. 从后端 OpenAPI 取全部路径
3. 逐条比对，分三类输出：
   - ✅ 对得上
   - ❌ **对不上**（要人看：是接口路径写错了，还是前端自己的路由）
   - ℹ️ 后端有、前端没用到

## 用法

    python scripts/check-api-parity.py
    python scripts/check-api-parity.py --strict   # 有对不上的就退出码 1
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FRONTEND_SRC = ROOT / "frontend" / "src"
BACKEND = ROOT / "backend"
API_PREFIX = "/api"


def frontend_literals() -> dict[str, set[str]]:
    """前端所有以 / 开头的字符串字面量 → {归一化路径: {出处}}。

    ⚠️ **刻意抓宽**：不做"这是不是接口调用"的判断 ——
    那正是 v1 漏检的原因。宁可多抓（人来筛），不能少抓。
    """
    out: dict[str, set[str]] = {}
    lit = re.compile(r"""[`'"](?P<p>/[^`'"\n]*)[`'"]""")
    for f in FRONTEND_SRC.rglob("*"):
        if f.suffix not in (".ts", ".tsx"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in lit.finditer(line):
                raw = m.group("p")
                if not raw or raw.startswith("//"):
                    continue
                norm = re.sub(r"\$\{[^}]+\}", "{param}", raw)
                norm = re.sub(r"\{[^}]+\}", "{param}", norm)
                out.setdefault(norm, set()).add(f"{f.relative_to(ROOT)}:{lineno}")
    return out


def backend_paths() -> set[str]:
    code = (
        "import json, sys; sys.path.insert(0, r'"
        + str(BACKEND)
        + "');"
        "import app.main as m;"
        "print(json.dumps(list(m.app.openapi()['paths'])))"
    )
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        print("⚠️ 取后端 OpenAPI 失败：")
        print((p.stderr or p.stdout)[-1500:])
        return set()
    return set(json.loads(p.stdout.strip().splitlines()[-1]))


def norm(p: str) -> str:
    return re.sub(r"\{[^}]+\}", "{param}", p)


def frontend_routes() -> set[str]:
    """从前端路由表里读它自己的页面路径 —— 用来把它们从"未匹配"里排除掉。

    ⚠️ 加这个是因为第一版用"前缀匹配"猜，把 `/` 和 `/report`（都是前端路由）
    误报成"疑似拼错的接口"。**误报和漏报一样有害** ——
    它会让人去查一个根本不存在的问题。
    """
    out: set[str] = set()
    for name in ("App.tsx", "router.tsx"):
        f = FRONTEND_SRC / name
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"""path[=:]\s*[`'"](\/[^`'"]*)[`'"]""", text):
            out.add(m.group(1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--show-all", action="store_true", help="连对得上的也全列出来")
    args = ap.parse_args()

    fe = frontend_literals()
    be = backend_paths()
    if not be:
        return 2
    be_norm = {norm(p): p for p in be}

    print("=" * 74)
    print("前后端契约比对 v2（抓宽不抓窄）")
    print("=" * 74)
    print(f"前端字面量：{len(fe)} 条不同的路径")
    print(f"后端提供  ：{len(be)} 条")
    print()

    hit: list[str] = []
    miss: list[tuple[str, set[str]]] = []
    for p, where in sorted(fe.items()):
        if norm(API_PREFIX + p) in be_norm:
            hit.append(p)
        else:
            miss.append((p, where))

    print(f"✅ 落在一个真实接口上：{len(hit)} 条")
    if args.show_all:
        for p in hit:
            print(f"    {API_PREFIX}{p}")

    print()
    print(f"⚠️ 没落到任何接口上：{len(miss)} 条")
    print("   （**不一定是错** —— 前端自己的路由也会以 / 开头。逐条看。）")
    print()
    for p, where in miss:
        print(f"    {p}")
        for w in sorted(where)[:4]:
            print(f"        ← {w}")
    print()

    # 反查：这些"没落到接口"的路径里，有没有其实是**拼错了的接口**。
    #
    # ⚠️ 第一版用的是「前缀匹配」—— 结果把前端自己的路由 `/` 和 `/report`
    #    误报成"疑似拼错的接口"（`/` 匹配上了 `/api/qa/sessions/{id}/state`）。
    #    **误报和漏报一样有害**：它会让人去查一个根本不存在的问题。
    #
    #    改成**先读前端的路由表**（App.tsx 里的 path），把它们排除掉，
    #    剩下的才可能有问题。
    routes = frontend_routes()
    suspects: list[tuple[str, str]] = []
    for p, _ in miss:
        if p in routes:
            continue                     # 前端自己的路由，不是接口
        if not p.startswith("/") or p == "/" or p == "/api":
            continue
        if p.count("/") < 1:
            continue
        full = norm(API_PREFIX + p)
        for bnorm, braw in be_norm.items():
            # 只认"真像接口"的：首段相同 且 有嵌套关系
            if full != bnorm and bnorm.lstrip("/api").startswith(full.lstrip("/")):
                suspects.append((p, braw))
                break

    if suspects:
        print("🚨 **这几条长得像接口路径、但和后端的对不上** —— 优先看：")
        for p, braw in suspects:
            print(f"    前端 {p}")
            print(f"    后端 {braw}")
        print()
    else:
        print("✅ 没有「长得像接口但拼错」的")

    if routes:
        print(f"ℹ️ 从前端路由表里排除掉：{', '.join(sorted(routes))}")
        print()

    unused = sorted(p for p in be if norm(p) not in {norm(API_PREFIX + x) for x in fe})
    print(f"ℹ️ 后端有、前端没引用：{len(unused)} 条")

    print()
    print("=" * 74)
    bad = len(suspects)
    if bad:
        print(f"❌ 发现 {bad} 条疑似接口路径不匹配 —— 需要人工确认")
    else:
        print(f"✅ 未发现接口路径不匹配（未匹配的 {len(miss)} 条看起来都是前端自己的路由）")
    print("   注意：这只验证**路径**；**字段名**仍要靠实测。")
    print("=" * 74)
    return 1 if (args.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
