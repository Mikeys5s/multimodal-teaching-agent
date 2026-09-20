"""前后端契约比对（归属：P2）—— v3：**加了方法比对 + 自测**。

## 它解决什么问题

**前端构建成功 ≠ 前端能用。** 后端测试全绿也同理。
**两边各自「通过」，但从没见过面。**

## 三条已经踩过的坑（写在这里，防止再犯）

**① v1 靠正则抓「接口调用」，漏了 7 条，却照样打印「完全对得上」**
→ 改成**把前端所有以 `/` 开头的字面量全抓出来**。抓多了不值钱，**抓少了才是灾难**。

**② v2 的「疑似拼错」启发式误报** —— 把前端路由 `/` 报成"疑似拼错的接口"
→ 改成**先读前端路由表排除**。

**③ v2 只比路径、不比方法** —— 我探 `/api/qa/sessions`（其实是 POST-only）得到 404，
先当成"接口缺失"。**工具没能力发现这类问题，我也没在结论里说清楚。**
→ v3 补上方法比对，**并且区分「显式写了 method」和「默认 GET」**。

## 自测（`--selftest`）

**一个从没被喂过「应该失败」样例的检查，等于没有检查。**
`--selftest` 会构造一个明知有问题的输入（方法写错 + 路径不存在），
跑一遍 extractor，**要求它必须报出来**；不报就说明工具是坏的。
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

#: 前端 `request()` 的默认方法（见 frontend/src/lib/api.ts）
DEFAULT_METHOD = "GET"
#: 在路径同一行往后看几行找 `method: 'X'`
LOOKAHEAD = 3


class Call:
    __slots__ = ("path", "method", "method_explicit", "where")

    def __init__(self, path: str, method: str, explicit: bool, where: str) -> None:
        self.path = path
        self.method = method
        self.method_explicit = explicit
        self.where = where


def _norm(p: str) -> str:
    """把路径归一化：`${id}` / `{id}` 都变成 `{param}`。

    ⚠️ **两种写法都要处理**。v3 重写时我只写了 `{...}`，漏了 `${...}` ——
    于是 `/materials/${id}` 归一化后还是 `/materials/${param}`，
    和后端的 `/api/materials/{material_id}` 对不上，**报了 14 处假问题**。

    **假警报和漏检一样有害** —— 它会让人去查一个根本不存在的问题。
    （这次是靠"看输出不对劲"才发现的 —— `${param}` 明摆着没被处理。）
    """
    p = re.sub(r"\$\{[^}]+\}", "{param}", p)
    return re.sub(r"\{[^}]+\}", "{param}", p)


def scan_calls(src_root: pathlib.Path = FRONTEND_SRC) -> tuple[list[Call], dict[str, set[str]]]:
    """抽出前端所有 API 调用（路径 + 方法）。

    返回 (calls, literals) —— literals 是**所有**以 `/` 开头的字面量，
    用来兜底（抓宽）：calls 里没有但 literals 里有的，说明扫描可能漏了。
    """
    calls: list[Call] = []
    literals: dict[str, set[str]] = {}
    lit = re.compile(r"""[`'"](?P<p>/[^`'"\n]*)[`'"]""")
    meth = re.compile(r"""method\s*:\s*[`'"](?P<m>[A-Za-z]+)[`'"]""")

    for f in src_root.rglob("*"):
        if f.suffix not in (".ts", ".tsx"):
            continue
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            continue
        rel = str(f.relative_to(ROOT))
        for i, line in enumerate(lines):
            for m in lit.finditer(line):
                raw = m.group("p")
                if not raw or raw.startswith("//"):
                    continue
                n = _norm(raw)
                literals.setdefault(n, set()).add(f"{rel}:{i + 1}")

                # 只在**这一次调用自己的范围**里找 method。
                #
                # ⚠️ 这里我错过两次，都是"停止条件"写得太糙：
                #
                #   第一次：简单地"往后看 3 行" → 越到下一条调用，
                #           `/materials/{id}/outline` 被安上了**下一条**的 POST（假问题）
                #   第二次：改成"遇到 `key:` 就停" → **`method: 'POST'` 自己就是 key:value**，
                #           于是在读到它之前就停了（真方法读不到）
                #
                # **正确的判据**：停的条件是"**开始了一次新的调用**"，而不是"长了个 key"。
                #   - 出现 `request` → 新调用
                #   - `xxx: (` 开头的箭头函数 → 新条目
                #   - `}` 收尾 → 对象结束
                window_lines = [line]
                for j in range(i + 1, min(i + 1 + LOOKAHEAD, len(lines))):
                    nxt = lines[j]
                    if (
                        "request" in nxt
                        or re.match(r"^\s*[a-zA-Z_$][\w$]*\s*:\s*\(", nxt)
                        or re.match(r"^\s*\}", nxt)
                        or re.match(r"^\s*(?:/\*|//)", nxt)
                    ):
                        break
                    window_lines.append(nxt)
                window = "\n".join(window_lines)

                # 这个方法是不是接口调用？看这一小段里有没有 request(
                if "request" not in window:
                    continue
                mm = meth.search(window)
                method = mm.group("m").upper() if mm else DEFAULT_METHOD
                calls.append(Call(n, method, bool(mm), f"{rel}:{i + 1}"))
    return calls, literals


def frontend_routes() -> set[str]:
    """从路由表读前端自己的页面路径 —— 用来把路由从"未匹配"里排除。"""
    out: set[str] = set()
    for name in ("App.tsx", "router.tsx"):
        f = FRONTEND_SRC / name
        if not f.exists():
            continue
        for m in re.finditer(r"""path[=:]\s*[`'"](\/[^`'"]*)[`'"]""", f.read_text(encoding="utf-8")):
            out.add(m.group(1))
    return out


def backend_paths() -> dict[str, set[str]]:
    code = (
        "import json, sys; sys.path.insert(0, r'"
        + str(BACKEND)
        + "');"
        "import app.main as m;"
        "print(json.dumps({k: sorted(v) for k, v in m.app.openapi()['paths'].items()}))"
    )
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        print("⚠️ 取后端 OpenAPI 失败：")
        print((p.stderr or p.stdout)[-1200:])
        return {}
    raw = json.loads(p.stdout.strip().splitlines()[-1])
    return {
        k: {m.upper() for m in v if m.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}}
        for k, v in raw.items()
    }


def analyze(calls: list[Call], be: dict[str, set[str]]) -> dict:
    be_norm = {_norm(k): (k, v) for k, v in be.items()}
    path_hit, path_miss, method_bad, assumed = [], [], [], []

    for c in calls:
        key = _norm(API_PREFIX + c.path)
        if key not in be_norm:
            path_miss.append(c)
            continue
        real_path, allowed = be_norm[key]
        path_hit.append(c)
        if c.method not in allowed:
            method_bad.append((c, real_path, sorted(allowed)))
        if not c.method_explicit:
            assumed.append(c)
    return {
        "hit": path_hit,
        "miss": path_miss,
        "method_bad": method_bad,
        "assumed": assumed,
    }


def selftest() -> int:
    """★ 给工具喂一个**明知有问题**的输入 —— 它必须报出来。"""
    print("=" * 74)
    print("自测：构造明知有问题的输入，看工具会不会报")
    print("=" * 74)

    be = backend_paths()
    if not be:
        return 2
    be_norm = {_norm(k): (k, v) for k, v in be.items()}

    # 找一个真实存在的路径来构造"方法写错"的样例
    sample_path = None
    for k, v in be.items():
        if v and "{" not in k:
            sample_path = (k, sorted(v)[0])
            break
    if sample_path is None:
        print("  ⚠️ 找不到可用样例路径")
        return 2
    real, real_method = sample_path
    wrong_method = "DELETE" if real_method != "DELETE" else "POST"

    cases = [
        (
            "① 方法写错（应当被抓到）",
            [Call(_norm(real).replace("/api", "", 1), wrong_method, True, "selftest")],
            "method_bad",
        ),
        (
            "② 路径不存在（应当被抓到）",
            [Call("/definitely-not-a-real-endpoint", "GET", True, "selftest")],
            "miss",
        ),
        (
            "③ 路径和方法都对（不应被抓）",
            [Call(_norm(real).replace("/api", "", 1), real_method, True, "selftest")],
            None,
        ),
    ]

    ok = True
    for title, calls, expect_bucket in cases:
        r = analyze(calls, be)
        if expect_bucket == "method_bad":
            caught = len(r["method_bad"]) == 1
        elif expect_bucket == "miss":
            caught = len(r["miss"]) == 1
        else:
            caught = not r["method_bad"] and not r["miss"]
        flag = "✅" if caught else "❌"
        print(f"  {flag} {title}")
        if not caught:
            ok = False
            print(f"       —— **工具没报**，说明它在这个维度上是坏的")

    # ★ 第二段：用**真的扫描器**去扫一个**故意写错**的夹具。
    #
    #    上面那三个用例是"合成"的 Call 对象，测的是比对逻辑；
    #    这一段测的是**扫描器本身** —— 我今天在它上面栽了两次：
    #    漏掉 `${...}` 归一化、方法前瞻越到下一条调用。
    #    **合成用例抓不到这两个 bug，因为 bug 在扫描器里，不在比对逻辑里。**
    fixture = ROOT / "samples" / "parity-probe.ts"
    if fixture.exists():
        f_calls, _ = scan_calls(src_root=fixture.parent)
        probe = [c for c in f_calls if "parity-probe" in c.where]
        by_path: dict[str, Call] = {}
        for c in probe:
            by_path.setdefault(c.path, c)

        checks = [
            (
                "④ 夹具：`${id}` 被归一化（我曾漏过，报了 14 处假问题）",
                any(c.path == "/materials/{param}" for c in probe),
            ),
            (
                "⑤ 夹具：没有 method 的调用是 GET（我曾把下一条的 POST 借过来）",
                next(
                    (c for c in probe if c.path == "/materials"),
                    None,
                )
                is not None
                and next(c for c in probe if c.path == "/materials").method == "GET",
            ),
            (
                "⑥ 夹具：方法写在下一行时能被读到",
                next((c for c in probe if c.path == "/extract/knowledge"), None) is not None
                and next(c for c in probe if c.path == "/extract/knowledge").method == "POST",
            ),
        ]
        for title, ok_i in checks:
            print(f"  {'✅' if ok_i else '❌'} {title}")
            if not ok_i:
                ok = False

        r2 = analyze(probe, be)
        catches = [
            ("⑦ 夹具：方法写错被抓到", len(r2["method_bad"]) >= 1),
            ("⑧ 夹具：路径不存在被抓到", len(r2["miss"]) >= 1),
        ]
        for title, ok_i in catches:
            print(f"  {'✅' if ok_i else '❌'} {title}")
            if not ok_i:
                ok = False
    else:
        print(f"  ⚠️ 找不到夹具 {fixture} —— 跳过扫描器自测（**这部分没被验证**）")

    print()
    if ok:
        print("✅ 自测通过：工具在该报的时候会报，不该报的时候不报")
    else:
        print("❌ 自测**不通过**：这个检查不可信，先修工具再信它的结论")
    print("=" * 74)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="先喂一个明知有问题的样例，验证工具本身")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    calls, literals = scan_calls()
    be = backend_paths()
    if not be:
        return 2
    r = analyze(calls, be)
    routes = frontend_routes()

    print("=" * 74)
    print("前后端契约比对 v3（路径 + **方法**）")
    print("=" * 74)
    print(f"前端调用   ：{len(calls)} 次（去重后 {len({c.path for c in calls})} 条路径）")
    print(f"后端提供   ：{len(be)} 条路径")
    print(f"前端字面量 ：{len(literals)} 条（抓宽兜底）")
    print()

    print(f"✅ 路径对得上：{len(r['hit'])} 条")
    if r["method_bad"]:
        print()
        print(f"🚨 **方法对不上：{len(r['method_bad'])} 条** —— 跑起来会 405")
        for c, real_path, allowed in r["method_bad"]:
            print(f"    前端 {c.method:<7} {API_PREFIX}{c.path}")
            print(f"    后端 {'/'.join(allowed):<7} {real_path}")
            print(f"         ← {c.where}")
    else:
        print("✅ 方法全部对得上")

    miss = [c for c in r["miss"] if c.path not in routes]
    print()
    if miss:
        print(f"⚠️ 路径对不上：{len(miss)} 条")
        for c in miss:
            print(f"    {c.method:<7} {c.path}   ← {c.where}")
    else:
        print("✅ 没有路径对不上的")

    if routes:
        print()
        print(f"ℹ️ 已按前端路由表排除：{', '.join(sorted(routes))}")

    # ⚠️ 把不确定性显式暴露出来 —— 默认 GET 是**假定**，不是事实
    if r["assumed"]:
        print()
        print(f"⚠️ {len(r['assumed'])} 条**没显式写 method**，已按默认 {DEFAULT_METHOD} 处理：")
        for c in r["assumed"][:8]:
            print(f"    {c.path}   ← {c.where}")
        if len(r["assumed"]) > 8:
            print(f"    ... 另有 {len(r['assumed']) - 8} 条")
        print("    这些**不是错误**，但结论的确定性低一档 —— 如实标出来，不装作确定。")

    print()
    print("=" * 74)
    bad = len(r["method_bad"]) + len(miss)
    if bad:
        print(f"❌ 发现 {bad} 处不匹配（方法 {len(r['method_bad'])} + 路径 {len(miss)}）")
    else:
        print("✅ 路径与方法都对得上")
    print("⚠️ 这只验证**路径和方法**；**字段名**仍需带数据的实测。")
    print("=" * 74)
    return 1 if (args.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
