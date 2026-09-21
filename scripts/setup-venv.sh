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
#   bash scripts/setup-venv.sh --check      # **只读自检**：不改任何文件，只报告环境健康
#   bash scripts/setup-venv.sh --check --repo <路径>   # 自检另一个仓库副本（测试用）
#
# `--check` 的退出码：**0 = 健康，1 = 有问题**（venv 未建 / 建在了项目内 /
# python.exe 跑不起来 / `[dev]` 依赖缺失 / **基础依赖缺失**（pymupdf / docx / pptx，
# 缺了 test 收集阶段就全灭，见 Issue #73）都会给 1）。
# 它只读，不建目录、不装依赖、不动 junction —— 出任何问题都只说怎么修。
#
# `--repo <路径>` 只影响 `--check`（和将来可能的只读模式）：把"仓库根"指到别处，
# 于是 `backend/.venv` 等路径都相对那个目录解析。给 `tmp_path` 造情形测试用。
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

# ---------------------------------------------------------------------------
# 参数解析（必须在算 REPO_ROOT 之前，因为 --repo 会改它）
# ---------------------------------------------------------------------------
REBUILD=0
CHECK=0
REPO_ARG=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --rebuild) REBUILD=1 ;;
    --check)   CHECK=1 ;;
    --repo)    shift; REPO_ARG="${1:-}" ;;
    --repo=*)  REPO_ARG="${1#--repo=}" ;;
    *)
      echo "未知参数：$1" >&2
      echo "用法：bash scripts/setup-venv.sh [--rebuild|--check] [--repo <路径>]" >&2
      exit 2
      ;;
  esac
  shift
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -n "$REPO_ARG" ]; then
  # 允许传 Windows 路径（C:\...）或 POSIX 路径（/c/...）
  REPO_ROOT="$(cd "${REPO_ARG//\\//}" 2>/dev/null && pwd)" \
    || { echo "找不到仓库路径：$REPO_ARG" >&2; exit 2; }
fi
BACKEND="$REPO_ROOT/backend"
PYPI="https://pypi.org/simple"

to_win() {   # /d/muti_tagent/x  ->  D:\muti_tagent\x
  # 路径**存在**时优先问 MSYS 自己（`pwd -W` 直接给带盘符的 Windows 形式）。
  # 原因：Git Bash 有挂载映射 —— 例如 `%TEMP%` 会显示成 `/tmp/...`，
  # 纯字符串替换会把它变成**没有盘符**的 `\tmp\...`，后续所有存在性判断都会错。
  #
  # ⚠️ 只能对**父目录**用 `pwd -W`，最后一段自己拼：`cd` 会**穿透 junction**，
  #    对它用 `pwd -W` 会返回**目标**的路径 —— 那样 `backend/.venv` 就会被
  #    误判成"项目内的真实目录"（自检的核心判定全错）。
  local dir name w
  dir="$(dirname "$1")"
  name="$(basename "$1")"
  if [ -n "$dir" ] && [ -d "$dir" ]; then
    w="$(cd "$dir" 2>/dev/null && pwd -W 2>/dev/null)"
    if [ -n "$w" ]; then
      printf '%s\\%s' "$(printf '%s' "$w" | sed -e 's|/|\\|g')" "$name"
      return
    fi
  fi
  printf '%s' "$1" | sed -e 's|^/\([a-zA-Z]\)/|\U\1:\\|' -e 's|/|\\|g'
}
to_posix() { # C:\Users\x  ->  /c/Users/x
  printf '%s' "$1" | sed -e 's|^\([a-zA-Z]\):|/\L\1|' -e 's|\\|/|g'
}

# ⚠️ 找「用户主目录」时不要用 `$USERNAME` 拼 ——
#    `$USERNAME` 是**登录名**，它和主目录名**可以不一样**
#    （实测本机主目录是 `C:\Users\XiaoZH`，而 `$USERNAME` 不是这个；
#     某些环境下 `$USERNAME` 干脆是空的）。用 `$USERNAME` 拼出来的路径不存在，
#     venv 会建到一个奇怪的地方去。**优先用 `$USERPROFILE` / `$HOME`。**
detect_home_win() {
  if [ -n "${USERPROFILE:-}" ] && [ -d "$(to_posix "$USERPROFILE")" ]; then
    printf '%s' "$USERPROFILE"; return
  fi
  if [ -n "${HOME:-}" ] && [ -d "$HOME" ]; then
    to_win "$HOME"; return
  fi
  # 最后才退回 $USERNAME（并明确提示这是不保险的兜底）
  printf 'C:\\Users\\%s' "${USERNAME:-admin}"
}

HOME_WIN="$(detect_home_win)"
VENV_HOME_WIN="${XIZHI_VENV_HOME:-${HOME_WIN}\\.venvs}"

LINK_POSIX="${XIZHI_VENV_LINK:-$BACKEND/.venv}"
LINK_WIN="$(to_win "$LINK_POSIX")"
TARGET_WIN="${XIZHI_VENV_DIR:-${VENV_HOME_WIN}\\xizhi-backend}"
TARGET_POSIX="$(to_posix "$TARGET_WIN")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  [OK] %s\n' "$*"; }
bad() { printf '  [!!] %s\n' "$*"; }
die() { bad "$*"; exit 1; }

# --check 专用的三种标记
c_ok()   { printf '  ✅ %s\n' "$*"; }
c_warn() { printf '  ⚠️ %s\n' "$*"; }
c_bad()  { printf '  ❌ %s\n' "$*"; }

find_python() {  # 打印一个 ≥3.11 的 python 路径；找不到则返回非 0
  local cand
  for cand in \
    "$(to_posix "$HOME_WIN")/.workbuddy/binaries/python/versions/3.13.12/python.exe" \
    "$(command -v python 2>/dev/null || true)" \
    "$(command -v python3 2>/dev/null || true)" \
    "/c/Python313/python.exe" \
    "/c/Python312/python.exe" ; do
    [ -n "$cand" ] && [ -x "$cand" ] || continue
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; then
      printf '%s' "$cand"; return 0
    fi
  done
  return 1
}

echo "仓库根目录 : $REPO_ROOT"
echo "用户主目录 : $HOME_WIN"
echo "junction   : $LINK_WIN"
echo "外部 venv  : $TARGET_WIN"

# ===========================================================================
# --check：**只读自检**。不建目录、不装依赖、不动 junction、不删任何东西。
# 退出码：0 = 健康，1 = 有问题。
# ===========================================================================
if [ "$CHECK" = "1" ]; then
  RC=0
  CPY="$(find_python || true)"

  echo
  echo "=================================================="
  echo " 析知后端环境自检（只读，不会修改任何文件）"
  echo "=================================================="

  # -------------------------------------------------------------------------
  # [1] junction 位置：不存在 / 真实目录 / junction
  # -------------------------------------------------------------------------
  echo
  echo "[1] backend/.venv 的形态（本应是指向项目外的 junction）"
  VENV_TYPE="UNKNOWN"
  VENV_TARGET=""
  if [ -n "$CPY" ]; then
    VENV_PROBE="$("$CPY" - "$LINK_WIN" <<'PYEOF' 2>/dev/null
import os, stat, sys
p = sys.argv[1]
try:
    st = os.lstat(p)
except OSError:
    print("TYPE=MISSING")
    raise SystemExit(0)
# junction / 软链在 Windows 上都是 reparse point；os.path.islink 对 junction 不可靠
attrs = getattr(st, "st_file_attributes", 0)
reparse = bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
if reparse:
    print("TYPE=REPARSE")
elif stat.S_ISDIR(st.st_mode):
    print("TYPE=REALDIR")
else:
    print("TYPE=OTHER")
if reparse:
    try:
        print("TARGET=" + os.readlink(p))
    except OSError:
        pass
PYEOF
)"
    VENV_TYPE="$(printf '%s\n' "$VENV_PROBE" | sed -n 's/^TYPE=//p')"
    VENV_TARGET="$(printf '%s\n' "$VENV_PROBE" | sed -n 's/^TARGET=//p')"
  fi

  case "$VENV_TYPE" in
    MISSING)
      c_bad "未建 —— $LINK_WIN 不存在"
      echo "      环境还没搭。建它："
      echo "          bash scripts/setup-venv.sh"
      RC=1
      ;;
    REALDIR)
      c_bad "这是一个**真实目录** —— venv 建在了项目内！"
      echo "      ⚠️ 本机的清理程序会成批删除项目目录里的文件："
      echo "         .venv/Lib/site-packages/ 被清空过多次，你的依赖会被删。"
      echo "      修法（把 venv 挪到项目外，命令路径一个字都不变）："
      echo "          bash scripts/setup-venv.sh --rebuild"
      RC=1
      ;;
    REPARSE)
      if [ -n "$VENV_TARGET" ]; then
        c_ok "是 junction（目录联接），指向：$VENV_TARGET"
      else
        c_ok "是 junction（目录联接）—— 文件在项目外，安全"
      fi
      ;;
    *)
      c_bad "无法判断 $LINK_WIN 的类型（探测结果 TYPE=$VENV_TYPE）"
      echo "      修法：bash scripts/setup-venv.sh --rebuild"
      RC=1
      ;;
  esac

  # -------------------------------------------------------------------------
  # [2] venv 里的 python.exe 能不能跑
  # -------------------------------------------------------------------------
  echo
  echo "[2] backend/.venv/Scripts/python.exe 是否可用"
  VPY="$LINK_POSIX/Scripts/python.exe"
  VPY_OK=0
  if [ -f "$VPY" ]; then
    PVER="$("$VPY" -c 'import platform; print(platform.python_version())' 2>/dev/null)"
    if [ -n "$PVER" ]; then
      c_ok "可用，Python $PVER"
      VPY_OK=1
    else
      c_bad "python.exe 在，但跑不起来（venv 可能被删过文件）"
      echo "      修法：bash scripts/setup-venv.sh --rebuild"
      RC=1
    fi
  else
    # 区分"还没建"与"建过但内容没了"：后者正是本机清理程序干的事（目录在、文件被删空），
    # 必须判**有问题**（RC=1）—— 否则这个自检对最该抓的情形反而是绿的。
    if [ "$VENV_TYPE" = "MISSING" ]; then
      c_warn "找不到 $LINK_WIN\\Scripts\\python.exe（venv 还没建）"
    else
      c_bad "venv 里没有可用的 python.exe —— 目录在、内容没了（很可能被清理程序删空过）"
      echo "      修法：bash scripts/setup-venv.sh --rebuild"
      RC=1
    fi
  fi

  # -------------------------------------------------------------------------
  # [3] 依赖分组：[dev] 与**基础依赖**（缺一个整个测试套都收集不了）
  # -------------------------------------------------------------------------
  echo
  echo "[3] 依赖分组"
  if [ "$VPY_OK" = "1" ]; then
    if "$VPY" -c 'import pytest, ruff' 2>/dev/null; then
      c_ok "[dev] 已装（pytest / ruff 可 import）"
    else
      c_bad "[dev] 缺失或有损坏（pytest / ruff 有 import 不了的）"
      echo "      装它：.venv/Scripts/python.exe -m pip install -e \".[dev]\""
      RC=1
    fi
    # ⚠️ 这三个是**基础依赖**（`backend/pyproject.toml` 的 `[project.dependencies]`），
    #    名字里带 parse 只是历史原因 —— 它们**不是**「只有 P1 才需要」：
    #    `app/api` → `app/pipeline` → `app/parse/__init__` 会**模块级**连锁 import 它们，
    #    缺任何一个都会让**整个测试套**在**收集阶段**全灭。
    #    实测（Issue #73）：P2 那次 24 个用例全报 `ModuleNotFoundError: No module named
    #    'pptx'`，而他一行 PPTX 代码都没写。所以这里判 **bad + RC=1**，不是 warn。
    MISSING_BASE_DEPS="$("$VPY" - <<'PYEOF' 2>/dev/null
import importlib.util as u
mods = [("pymupdf", "pymupdf"), ("python-docx", "docx"), ("python-pptx", "pptx")]
missing = []
for dist, mod in mods:
    try:
        if u.find_spec(mod) is None:
            missing.append(dist)
    except Exception:
        missing.append(dist)
print(",".join(missing))
PYEOF
)"
    if [ -n "$MISSING_BASE_DEPS" ]; then
      c_bad "缺基础依赖：$MISSING_BASE_DEPS —— 解析链路会 import 它们，缺了**整个测试套**都收集不了"
      echo "      装它：.venv/Scripts/python.exe -m pip install -e \".[dev]\""
      echo "      （或直接重建：bash scripts/setup-venv.sh --rebuild）"
      RC=1
    else
      c_ok "pymupdf / docx / pptx 可 import（基础依赖；缺一个测试套就收集不了）"
    fi
  else
    c_warn "跳过依赖检查（venv 里的 python 不可用）"
  fi

  # -------------------------------------------------------------------------
  # [4] 项目外的真实 venv（文件物理位置）
  # -------------------------------------------------------------------------
  echo
  echo "[4] 项目外真实 venv（文件实际存放处）"
  if [ -d "$TARGET_POSIX" ]; then
    TCOUNT="$(find "$TARGET_POSIX" -type f 2>/dev/null | wc -l | tr -d ' ')"
    c_ok "存在：$TARGET_WIN（约 $TCOUNT 个文件）"
  else
    c_warn "不存在：$TARGET_WIN（首次搭建时会自动创建）"
  fi

  # -------------------------------------------------------------------------
  # [5] 下一步建议
  # -------------------------------------------------------------------------
  echo
  echo "[5] 下一步建议"
  if [ "$RC" = "0" ]; then
    echo "  环境健康。继续开发："
    echo "      cd backend && .venv/Scripts/python.exe -m pytest -q"
  else
    echo "  照上面 ❌ 的提示处理。常用命令："
    echo "      bash scripts/setup-venv.sh            # 首次搭建"
    echo "      bash scripts/setup-venv.sh --rebuild  # 坏了重建"
    echo "      bash scripts/setup-venv.sh --check    # 再自检一次"
  fi

  echo
  echo "=================================================="
  if [ "$RC" = "0" ]; then
    echo " 自检结果：健康 ✅（退出码 0）"
  else
    echo " 自检结果：有问题 ❌（退出码 1）"
  fi
  echo "=================================================="
  exit "$RC"
fi

# ---------------------------------------------------------------------------
# 0. 找 Python ≥ 3.11
# ---------------------------------------------------------------------------
say "[0/5] 找 Python"
PY="$(find_python || true)"
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
