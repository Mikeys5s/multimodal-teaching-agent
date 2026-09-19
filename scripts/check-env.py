"""环境恢复自检（归属：P2）。

## 它测什么

2026-09-19 20:45 起，本机的「删除」和「改名」被安全沙箱拦下
（`[safe-delete][SAFE_DELETE_FAIL_CLOSED] reason=windows-sandbox-recycle-bin-unavailable`），
连带 **git 的全部写操作失效** —— 因为 git 写 index 走的是「临时文件 + 改名」。

这个脚本把受损的**每一项能力单独测一遍**，最后给一个明确结论。
**别只看 git 报不报错** —— 那样只能知道"不行"，不知道"哪一层不行"。

## 用法

    python .learnbuddy/_gh/check_env.py

## ⚠️ 它不留垃圾

测试用的临时文件建在**系统临时目录**（不是仓库里），
测完尝试清理；**清不掉正是故障本身**，脚本会说明。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(r"D:\muti_tagent")
WORK = ROOT / ".learnbuddy" / "_work"   # 测试 git 用的克隆副本（不动主仓库）

results: list[tuple[str, bool, str]] = []


def rec(name: str, ok: bool, note: str = "") -> None:
    results.append((name, ok, note))
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f"  —— {note}" if note else ""))


def brief(e: BaseException) -> str:
    s = f"{type(e).__name__}: {e}"
    for key in ("SAFE_DELETE_FAIL_CLOSED", "windows-sandbox-recycle-bin-unavailable"):
        if key in s:
            return "被安全沙箱拦下（回收站不可用 → fail closed）"
    return s[:110]


print("=" * 68)
print("环境恢复自检")
print("=" * 68)

tmp = pathlib.Path(tempfile.mkdtemp(prefix="xizhi_envcheck_"))
print(f"临时目录：{tmp}")
print()

# ---- ① 建文件 ---------------------------------------------------------
target = tmp / "probe.txt"
try:
    target.write_text("hello", encoding="utf-8")
    rec("① 建文件", True)
except Exception as e:  # noqa: BLE001
    rec("① 建文件", False, brief(e))

# ---- ② 改名（这是 git 的关键依赖）-------------------------------------
renamed = tmp / "probe_renamed.txt"
try:
    os.rename(target, renamed)
    rec("② 改名 os.rename", True)
except Exception as e:  # noqa: BLE001
    rec("② 改名 os.rename", False, brief(e))
    renamed = target

# ---- ③ 改名覆盖（git 写 index 用的是这种）-----------------------------
over = tmp / "probe_over.txt"
try:
    over.write_text("x", encoding="utf-8")
    os.replace(renamed, over)
    rec("③ 覆盖式改名 os.replace", True)
except Exception as e:  # noqa: BLE001
    rec("③ 覆盖式改名 os.replace", False, brief(e))

# ---- ④ 删除 -----------------------------------------------------------
try:
    os.remove(over if over.exists() else renamed)
    rec("④ 删除 os.remove", True)
except Exception as e:  # noqa: BLE001
    rec("④ 删除 os.remove", False, brief(e))

# ---- ⑤ sed -i（它也要临时文件 + 改名）---------------------------------
#
# ⚠️ **必须在同一个盘里测**。第一版把目标放在系统临时目录（C:），
#    而 sed 的临时文件建在当前目录（仓库在 D:）—— 两者不同盘，
#    sed 报 `Invalid cross-device link`。
#    **那是测试写错了，不是环境的错** —— 差点让我得出错误结论。
sedfile = ROOT / "_env_probe_sed.txt"
try:
    sedfile.write_text("old\n", encoding="utf-8")
    p = subprocess.run(
        ["sed", "-i", "s/old/new/", sedfile.name],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    ok = p.returncode == 0 and "new" in sedfile.read_text(encoding="utf-8")
    rec("⑤ sed -i（同盘）", ok, (p.stderr or "").strip()[:90] if not ok else "")
    try:
        os.remove(sedfile)
    except Exception:  # noqa: BLE001
        pass
except Exception as e:  # noqa: BLE001
    rec("⑤ sed -i（同盘）", False, brief(e))

# ---- ⑥ git：切分支 ----------------------------------------------------
if not (WORK / ".git").exists():
    rec("⑥ git 切分支", False, f"测试用的克隆不存在：{WORK}")
else:
    p = subprocess.run(
        ["git", "switch", "-c", "env-probe"],
        cwd=WORK, capture_output=True, text=True, timeout=60,
    )
    rec("⑥ git 切分支", p.returncode == 0, (p.stderr or p.stdout).strip()[:110])

# ---- ⑦ git：提交 ------------------------------------------------------
if (WORK / ".git").exists():
    probe = WORK / "_env_probe.txt"
    probe.write_text("probe", encoding="utf-8")
    subprocess.run(["git", "add", "_env_probe.txt"], cwd=WORK, capture_output=True, timeout=60)
    p = subprocess.run(
        ["git", "-c", "user.name=probe", "-c", "user.email=probe@local",
         "commit", "-m", "env probe"],
        cwd=WORK, capture_output=True, text=True, timeout=60,
    )
    ok = p.returncode == 0
    rec("⑦ git 提交", ok, (p.stderr or p.stdout).strip()[:110])
    if ok:
        subprocess.run(["git", "reset", "--hard", "HEAD~1"], cwd=WORK, capture_output=True, timeout=60)
        subprocess.run(["git", "switch", "main"], cwd=WORK, capture_output=True, timeout=60)
        subprocess.run(["git", "branch", "-D", "env-probe"], cwd=WORK, capture_output=True, timeout=60)

# ---- 汇总 -------------------------------------------------------------
#
# ⚠️ 第一版的结论句是**写死的**：「删除/改名仍被拦，git 写操作仍然不可用」。
#    结果环境恢复那次，它明明 7 项里过了 6 项，**结论还是那句话** ——
#    一条永远输出同样结论的诊断，比没有诊断更坏：它会让人误判。
#
#    现在结论**从失败项推导**：哪些能力真的坏了，才说哪些。
print()
print("=" * 68)

failed = {name: note for name, ok, note in results if not ok}
ok_names = {name for name, ok, _ in results if ok}
rename_ok = "② 改名 os.rename" in ok_names and "③ 覆盖式改名 os.replace" in ok_names
git_ok = "⑥ git 切分支" in ok_names and "⑦ git 提交" in ok_names

if not failed:
    print("✅ 全部恢复 —— git 可正常提交")
else:
    print(f"❌ 有 {len(failed)} 项不可用：")
    for name, note in failed.items():
        print(f"    · {name}  {note}")

    print()
    # 结论**从失败项推导**，不再写死
    if not rename_ok:
        print("   → **改名不可用** → git 写操作（提交 / 切分支）必然失败")
        print("   → 按 docs/env-fix-delete-blocked.md 的 4 步处置")
    elif not git_ok:
        print("   → 改名可用，但 **git 仍写不了** —— 这不是同一个故障，")
        print("     要单独查仓库本身（`.git` 里是否还有陈旧锁）")
    else:
        print("   → **文件操作与 git 都正常** —— 失败的只是别的能力")
        print("     （如 `sed -i`，它在本机另有 EXDEV 的问题），**不影响提交**")
print("=" * 68)

# 清理（清不掉是正常的，那正是故障本身）
try:
    shutil.rmtree(tmp)
except Exception:  # noqa: BLE001
    print(f"（临时目录没清掉 —— 这本身就是故障：{tmp}）")

sys.exit(1 if failed else 0)
