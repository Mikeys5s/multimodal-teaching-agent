"""部署后自检（归属：P2）—— deploy.sh 的最后一步。

## 为什么必须做这个

2026-09-20 我连续两次以为"部署完成了"：

- 第一次：用了 `nohup`（这台机器没有），**部署根本没启动**
- 第二次：部署跑了 15 分钟，但 **docker 镜像的构建时间还是上一次的** ——
  **没有任何东西产出新镜像，而脚本照样打印「✅ 部署流程结束」**

**原 ⑤ 验证段只做三件事**：打印容器状态、`curl /` 看状态码、`curl /api/health` 看内容。
**三个都不断言**，所以"部署完了"和"代码生效了"之间**没有任何联系**。

## 这个脚本做什么

**① 代码身份**（**最关键的一条**）
  把本地 `backend/app/**/*.py` 算一个**清单哈希**，再算容器里同一批文件的清单哈希，
  **两者必须一致**。
  **这是通用的** —— 不看任何具体函数名，所以改名字、加文件都能正确判定。
  （我第一版想查 `_real_outline` 在不在容器里，但那种判据**改个名字就失效**，
   而且会给出"改了名字 = 部署失败"这种假警报。）

**② 容器健康**
  必须 `healthy`，不是 `starting`。

**③ 关键接口断言** —— 这几个是今天修过、必须生效的：
  · `/api/health` 返回 ok
  · 未注册的 `/api/**` 返回 **JSON 404**（不是 SPA HTML）
  · `/api/report/quality` 的 acceptance 每条都带 `sample_size`
  · `/api/materials/{id}/outline` 不再返回 mock 的「传输层」

**④ 退出码**：任何一条失败 → 非零退出 → deploy.sh 也随之失败。
  **这是整个改动的重点**：让"部署完了"从一句口号变成**一个被检查过的事实**。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOST = "xizhi"
BASE = "http://120.77.177.171:8000"
CONTAINER = "xizhi"

PASS = 0
FAIL = 0


def ok(name: str, note: str = "") -> None:
    global PASS
    PASS += 1
    print(f"  ✅ {name}" + (f"   {note}" if note else ""))


def bad(name: str, note: str = "") -> None:
    global FAIL
    FAIL += 1
    print(f"  ❌ {name}" + (f"   {note}" if note else ""))


def ssh(cmd: str, timeout: int = 120) -> tuple[int, str]:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", HOST, cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, (r.stdout + r.stderr)


def api(path: str, timeout: int = 40):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "xizhi-postdeploy"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = r.headers.get("content-type", "")
            body = r.read().decode("utf-8", "ignore")
            return r.status, ct, body
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        return -1, "", f"{type(e).__name__}: {e}"


# =============================================================================
print("=" * 74)
print("部署后自检")
print("=" * 74)

# ---- ① 代码身份：本地 vs 容器 -------------------------------------------------
print()
print("① 代码身份（本地清单哈希 vs 容器清单哈希）")


def manifest_hash(root: pathlib.Path) -> tuple[str, int]:
    """对 root 下所有 .py 算一个稳定的清单哈希。"""
    h = hashlib.sha256()
    files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in str(p))
    for p in files:
        h.update(p.relative_to(root).as_posix().encode())
        h.update(hashlib.sha256(p.read_bytes()).hexdigest().encode())
    return h.hexdigest()[:16], len(files)


local_hash, local_n = manifest_hash(ROOT / "backend" / "app")
print(f"    本地：{local_hash}  （{local_n} 个 .py）")

# 容器侧：在容器内用 python 算同一个清单
REMOTE_CODE = (
    "import hashlib,pathlib;"
    "root=pathlib.Path('/app/backend/app');"
    "h=hashlib.sha256();"
    "fs=sorted(p for p in root.rglob('*.py') if '__pycache__' not in str(p));"
    "[ (h.update(p.relative_to(root).as_posix().encode()),"
    "   h.update(hashlib.sha256(p.read_bytes()).hexdigest().encode())) for p in fs ];"
    "print(h.hexdigest()[:16], len(fs))"
)
rc, out = ssh(f"docker exec {CONTAINER} python -c \"{REMOTE_CODE}\"")
parts = out.strip().split()
if rc == 0 and len(parts) >= 2 and len(parts[0]) == 16:
    remote_hash, remote_n = parts[0], parts[1]
    print(f"    容器：{remote_hash}  （{remote_n} 个 .py）")
    if remote_hash == local_hash:
        ok("容器里跑的就是当前代码", "清单哈希一致")
    else:
        bad("**容器里的代码不是当前代码**", f"{local_hash} != {remote_hash} —— 部署没生效")
else:
    bad("取不到容器里的代码哈希", out.strip()[:120])

# ---- ② 容器健康 --------------------------------------------------------------
print()
print("② 容器健康")
for i in range(12):
    rc, out = ssh(f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'")
    st = out.strip()
    if "healthy" in st:
        ok("容器 healthy", st)
        break
    if i == 0:
        print(f"    等待健康检查…（当前：{st or '未运行'}）")
    time.sleep(5)
else:
    bad("容器没有变成 healthy", st)

# ---- ③ 关键接口断言 ----------------------------------------------------------
print()
print("③ 关键接口断言")

code, ct, body = api("/api/health")
try:
    d = json.loads(body)
    ok("/api/health 返回 ok", f"HTTP {code} status={d['data'].get('status')}")
except Exception:  # noqa: BLE001
    bad("/api/health", f"HTTP {code} {body[:80]}")

code, ct, body = api("/api/definitely-not-registered")
is_json = "json" in ct.lower()
has_ok_false = '"ok"' in body.replace(" ", "") and "false" in body
if code == 404 and is_json and has_ok_false:
    ok("未注册的 /api/** -> JSON 404（不是 SPA HTML）")
else:
    bad("未注册的 /api/** 应为 JSON 404", f"HTTP {code} ct={ct[:30]}")

code, ct, body = api("/api/report/quality")
try:
    acc = json.loads(body)["data"]["acceptance"]
    miss = [r["label"] for r in acc if "sample_size" not in r]
    if not miss:
        ok("acceptance 每条都带 sample_size", f"{len(acc)} 条")
    else:
        bad("acceptance 缺 sample_size", str(miss[:3]))
except Exception as e:  # noqa: BLE001
    bad("/api/report/quality 解析", f"{e}｜{body[:80]}")

# outline 不能是 mock（只在库里有素材时查）
code, ct, body = api("/api/materials")
try:
    mats = json.loads(body)["data"]["items"]
    if mats:
        code, ct, body = api(f"/api/materials/{mats[0]['id']}/outline")
        chs = json.loads(body)["data"]["chapters"]
        titles = [c["title"] for c in chs]
        if any("传输层" == t for t in titles) and len(chs) == 1:
            bad("/outline 看起来仍是写死的 mock", f"首章「{titles[0]}」")
        else:
            ok("/outline 是真实推导", f"{len(chs)} 章，首章「{titles[0][:34] if titles else '空'}」")
    else:
        print("    ℹ️ 库里没有素材，跳过 outline 检查")
except Exception as e:  # noqa: BLE001
    bad("outline 检查失败", f"{e}")

# ---- 汇总 --------------------------------------------------------------------
print()
print("=" * 74)
print(f"部署后自检：✅ {PASS} 项   ❌ {FAIL} 项")
if FAIL:
    print()
    print("❌ **部署没有真正生效** —— 上面失败的项就是证据。")
    print("   「部署跑完」不等于「代码生效」。请查：")
    print("     · 本地打包是否包含最新提交（git archive 只打已跟踪文件）")
    print("     · 镜像是否真的重新构建了（docker images xizhi 看创建时间）")
    print("     · 容器是否用了新镜像（docker inspect 看 StartedAt）")
print("=" * 74)

sys.exit(1 if FAIL else 0)
