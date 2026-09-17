#!/usr/bin/env bash
# 一键搭建虚拟环境（**把 venv 放在项目目录之外**）。
#
# ## 为什么不在项目里建 venv
#
# 实测本机有程序会**批量删除 `D:\muti_tagent` 下的文件**，已经发生过 4 次：
# `.venv/Lib/site-packages/` 被清空（目录结构和 `.dist-info` 还在），
# `.git/objects/pack/` 也被清空过。**加杀毒软件信任区没有挡住。**
#
# 所以把 venv 放到项目外，再用 **junction（目录联接）** 把 `backend/.venv` 指过去：
#   · 文件物理位置在项目外 → 按路径扫描的清理程序碰不到
#   · `backend/.venv/Scripts/python.exe` **路径照旧** → 文档和命令一个字都不用改
#
# ## 用法
#
#   bash scripts/setup-venv.sh              # 首次搭建
#   bash scripts/setup-venv.sh --rebuild    # 环境坏了，推倒重建
#
# 可用环境变量覆盖（便于测试，正常不用管）：
#   XIZHI_VENV_DIR   外部 venv 位置，默认 %USERPROFILE%\.venvs\xizhi-backend
#   XIZHI_VENV_LINK  junction 位置，默认 backend/.venv
#
# ## 两条踩过的坑（改这个脚本时注意）
#
# 1. **不要用 `cygpath`** —— 本环境的 bash 没有它（`chmod` 也没有）。
#    cygpath 失败后会静默回退成 POSIX 路径，让 PowerShell 在**错误的位置**建 junction
#    （实测建到了 `D:\d\muti_tagent\...`）。
# 2. **Windows 的 Python / PowerShell 要用 Windows 路径**（`C:\...`），
#    bash 的 `find` / `[ -f ]` 要用 POSIX 路径（`/c/...`）。
#    混用会让 `python -m venv` 静默建不出 `Scripts/python.exe`。
#    下面的 `$*_WIN` 给前者用，`$*_POSIX` 给后者用 —— 别搞混。

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"
PYPI="https://pypi.org/simple"

to_win() {   # /d/muti_tagent/x  ->  D:\muti_tagent\x
  printf '%s' "$1" | sed -e 's|^/\([a-zA-Z]\)/|\U\1:\\|' -e 's|/|\\|g'
}
to_posix() { # C:\Users\x  ->  /c/Users/x
  printf '%s' "$1" | sed -e 's|^\([a-zA-Z]\):|/\L\1|' -e 's|\\|/|g'
}

LINK_POSIX="${XIZHI_VENV_LINK:-$BACKEND/.venv}"
LINK_WIN="$(to_win "$LINK_POSIX")"
TARGET_WIN="${XIZHI_VENV_DIR:-C:\\Users\\${USERNAME:-admin}\\.venvs\\xizhi-backend}"
TARGET_POSIX="$(to_posix "$TARGET_WIN")"

REBUILD=0
[ "${1:-}" = "--rebuild" ] && REBUILD=1

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  [OK] %s\n' "$*"; }
bad() { printf '  [!!] %s\n' "$*"; }
die() { bad "$*"; exit 1; }

echo "仓库根目录 : $REPO_ROOT"
echo "junction   : $LINK_WIN"
echo "外部 venv  : $TARGET_WIN"

# ---------------------------------------------------------------------------
# 0. 找 Python ≥ 3.11
# ---------------------------------------------------------------------------
say "[0/5] 找 Python"
PY=""
for cand in \
  "C:/Users/${USERNAME:-admin}/.workbuddy/binaries/python/versions/3.13.12/python.exe" \
  "$(command -v python 2>/dev/null || true)" \
  "$(command -v python3 2>/dev/null || true)" ; do
  [ -n "$cand" ] && [ -x "$cand" ] || continue
  if "$cand" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
[ -n "$PY" ] || die "找不到 Python ≥ 3.11（见 docs/dev-environment.md §1）"
ok "$PY  ($("$PY" -c 'import platform; print(platform.python_version())'))"

# ---------------------------------------------------------------------------
# 1. 腾出 junction 位置
# ---------------------------------------------------------------------------
say "[1/5] 腾出 junction 位置"
if [ -e "$LINK_POSIX" ] || [ -L "$LINK_POSIX" ]; then
  if [ "$REBUILD" != "1" ]; then
    ok "$LINK_WIN 已存在（要重建请加 --rebuild）"
    exit 0
  fi
  # ⚠️ 本机删除机制受限（走回收站），一律用 **重命名移走**，不用 rm
  "$PY" - <<PYEOF || die "移走旧 junction 失败"
import os, pathlib, time, subprocess
p = pathlib.Path(r"""$LINK_WIN""")
arch = pathlib.Path(r"""$REPO_ROOT/.learnbuddy""") / f"_old_venv_{int(time.time())}"
arch.parent.mkdir(parents=True, exist_ok=True)
if p.is_symlink():
    p.unlink(); print("  旧的链接已移除")
elif p.exists():
    r = subprocess.run(["cmd", "/c", "rmdir", str(p)], capture_output=True, text=True)
    if r.returncode == 0:
        print("  junction 已移除")
    else:
        os.rename(p, arch); print(f"  旧的已改名留档 → {arch.name}（没有删除）")
PYEOF
else
  ok "位置本来就是空的"
fi

# ---------------------------------------------------------------------------
# 2. 在项目外建 venv
# ---------------------------------------------------------------------------
say "[2/5] 在项目外建 venv"
if [ -e "$TARGET_POSIX" ]; then
  "$PY" - <<PYEOF || die "移走旧的外部 venv 失败"
import os, pathlib, time
p = pathlib.Path(r"""$TARGET_WIN""")
dst = p.with_name(p.name + f"_old_{int(time.time())}")
try:
    os.rename(p, dst); print(f"  旧的外部 venv 已改名留档 → {dst.name}（没有删除）")
except Exception as e:
    print(f"  [!!] {type(e).__name__}: {e}"); raise SystemExit(1)
PYEOF
fi

mkdir -p "$TARGET_POSIX" 2>/dev/null
[ -d "$TARGET_POSIX" ] || die "建不出 $TARGET_WIN"

# 用 Windows 路径喂给 Windows 的 Python
"$PY" -m venv "$TARGET_WIN" || die "创建 venv 失败"
VPY="$TARGET_POSIX/Scripts/python.exe"
[ -f "$VPY" ] || die "venv 里没有 python.exe（检查是不是把 POSIX 路径传给了 Windows Python）"
ok "已建在 $TARGET_WIN"

# ---------------------------------------------------------------------------
# 3. 装依赖
# ---------------------------------------------------------------------------
say "[3/5] 装依赖"
"$VPY" -m ensurepip >/dev/null 2>&1 || true

# 先补 setuptools：pip 的构建隔离会去下载它，镜像抽风时整个安装会挂（见坑 1b）
"$VPY" -m pip install -q setuptools wheel -i "$PYPI" 2>&1 | grep -v '^\[notice\]' || true

# --no-build-isolation：跳过构建隔离，避免为装本项目再去下 setuptools
( cd "$BACKEND" && "$VPY" -m pip install -q -e ".[dev]" --no-build-isolation -i "$PYPI" ) \
  || die "装依赖失败 —— 可换源重试，见 docs/dev-environment.md 坑 1b"
ok "依赖安装完成"

# ---------------------------------------------------------------------------
# 4. 建 junction
# ---------------------------------------------------------------------------
say "[4/5] 把 junction 指过去"
powershell.exe -NoProfile -Command "
try {
  New-Item -ItemType Junction -Path '$LINK_WIN' -Target '$TARGET_WIN' -ErrorAction Stop | Out-Null
  Write-Output '  [OK] junction 已创建'
} catch { Write-Output ('  [!!] 创建失败: ' + \$_.Exception.Message) }
" 2>&1 | tail -2

# ---------------------------------------------------------------------------
# 5. 验证
# ---------------------------------------------------------------------------
say "[5/5] 验证"
FAIL=0
[ -f "$LINK_POSIX/Scripts/python.exe" ] \
  && ok "junction 下的 python.exe 可用（路径没变）" \
  || { bad "路径不可用"; FAIL=1; }

"$LINK_POSIX/Scripts/python.exe" -c "import fastapi, sqlalchemy, alembic.config, pytest, ruff" 2>/dev/null \
  && ok "关键依赖都能 import" \
  || { bad "有依赖 import 不了"; FAIL=1; }

COUNT=$(find "$LINK_POSIX" -maxdepth 3 -type f 2>/dev/null | wc -l)
if [ "$COUNT" -lt 20 ]; then
  ok "项目内实际文件数 = $COUNT（确认文件在项目外）"
else
  bad "项目内有 $COUNT 个文件 —— junction 可能没生效"
  FAIL=1
fi

echo
if [ "$FAIL" = "0" ]; then
  echo "环境就绪。跑测试："
  echo "    cd backend && .venv/Scripts/python.exe -m pytest -q"
else
  echo "有检查未通过，请按上面提示处理"
fi
exit "$FAIL"
