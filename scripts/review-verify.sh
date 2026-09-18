#!/usr/bin/env bash
# 独立验证脚本 —— 在**项目之外**的干净克隆里验证一个 PR / 分支（归属：P2，全队可用）
#
# ## 为什么必须在"项目之外"验
#
# 本机存在「工作区文件被成批删除」的未定责问题（Issue #20，已发生 5 次）。
# 也就是说：**主工作区本身不是一个可信的验证环境**。
# 在一个会随机丢文件的地方跑测试，结论没有意义 —— 你不知道失败是代码的问题
# 还是"文件又没了"。
#
# 所以这个脚本的**第一件事**就是：把代码拷到一个全新目录，
# 并且**先做一次文件完整性预检**（对比 `git ls-files`），
# 缺失就先 `git restore .` 并明确告警 —— 不让"环境问题"污染"代码结论"。
#
# ## 用法
#
#   bash scripts/review-verify.sh --pr 30
#   bash scripts/review-verify.sh --branch feat/frontend-scaffold
#   bash scripts/review-verify.sh --pr 30 --keep      # 保留克隆，供人工检查
#
# ## 它会输出
#
#   ① 文件完整性预检（缺失数必须是 0）
#   ② ruff check / format
#   ③ pytest 全量（含跳过项与原因）
#   ④ 与 main 的差距（落后多少、改了哪些文件）
#   ⑤ 一份可直接粘进 PR 评论的结论摘要
#
# ## 它**不做**什么
#
# 它只跑机器能判定的部分（测试、静态检查、文件完整性）。
# 「声明与实现是否一致」「指标是否自我实现」这类需要判断的，见
# `docs/review-playbook.md` —— 那部分必须由人（或 agent）来读、来想。

set -u

# ---- 参数 ----
PR=""
BRANCH=""
KEEP=0
ENV_PY="${REVIEW_BASE_PYTHON:-}"

while [ $# -gt 0 ]; do
    case "$1" in
        --pr)     PR="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --keep)   KEEP=1; shift ;;
        *) echo "未知参数：$1"; exit 2 ;;
    esac
done

if [ -z "$PR" ] && [ -z "$BRANCH" ]; then
    echo "用法：bash scripts/review-verify.sh --pr <编号> | --branch <分支名> [--keep]"
    exit 2
fi

REPO_SLUG="RyeYen/multimodal-teaching-agent"
WORK_ROOT="${REVIEW_WORK_ROOT:-$HOME/.xizhi-review}"
CLONE="$WORK_ROOT/repo"
VENV="$WORK_ROOT/venv"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '  [OK] %s\n' "$*"; }
warn() { printf '  [!!] %s\n' "$*"; }
die()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

# 把 POSIX 路径转成原生 Windows 程序能用的形式（/c/Users/x -> c:/Users/x）。
#
# ⚠️ 这不是洁癖 —— 本仓库已经在这件事上摔了 6 次（见 docs/dev-playbook.md §3.2）：
#    python / ssh-keygen / powershell / scp / git -C / python 读文件，
#    **原生 Windows 程序一律不认 `/c/...`**，而且报错都指不到真正原因。
#    凡是把路径**当参数传给原生程序**（python、git）的地方，都过一遍这个函数。
to_win() { printf '%s' "$1" | sed -e 's|^/\([a-zA-Z]\)/|\1:/|' ; }

# 找一个**确认可用**的基础解释器（建 venv 要用）。
# 逐个候选试 `import venv` —— 本机有多个 python，其中一些是坏的（装不出 Scripts/python.exe），
# 所以**必须实测**而不是取第一个 `command -v python`。
find_base_python() {
    for cand in "${REVIEW_BASE_PYTHON:-}" \
                "$HOME/.workbuddy/binaries/python/versions/3.13.12/python.exe" \
                "$(command -v python3 2>/dev/null)" \
                "$(command -v python 2>/dev/null)"; do
        [ -n "$cand" ] || continue
        [ -x "$cand" ] || continue
        if "$cand" -c "import venv, sys" >/dev/null 2>&1; then
            printf '%s' "$cand"
            return 0
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# 0. 找 Python（优先用已有的独立 venv，没有就用仓库自带的）
# ---------------------------------------------------------------------------
if [ -z "$ENV_PY" ]; then
    if [ -x "$VENV/Scripts/python.exe" ]; then
        ENV_PY="$VENV/Scripts/python.exe"
    elif [ -x "$VENV/bin/python" ]; then
        ENV_PY="$VENV/bin/python"
    fi
fi

# ---------------------------------------------------------------------------
# 1. 准备独立克隆
# ---------------------------------------------------------------------------
say "1/5 准备独立克隆（项目之外：$WORK_ROOT）"
mkdir -p "$WORK_ROOT"

if [ -d "$CLONE/.git" ]; then
    echo "  已有克隆，直接 fetch（比重新 clone 快）"
    # ⚠️ 不要用 `git -C <路径>` —— git 是**原生 Windows 程序**，不认 /c/... 这种 POSIX 路径
    #    （报 `fatal: cannot change to '...': No such file or directory`）。
    #    bash 内建的 `cd` 才认。这是本仓库反复踩到的同一个坑。
    (cd "$CLONE" && git fetch --quiet origin 2>&1 | tail -3)
else
    echo "  首次克隆 ..."
    git clone --quiet "https://github.com/$REPO_SLUG.git" "$CLONE" 2>&1 | tail -3
    [ -d "$CLONE/.git" ] || die "克隆失败"
fi
ok "克隆就绪：$CLONE"

# ---------------------------------------------------------------------------
# 2. 切到目标分支（**用 fetch + switch，绝不用 rebase**）
# ---------------------------------------------------------------------------
say "2/5 切到目标分支"
cd "$CLONE" || die "进不去克隆目录"

if [ -n "$PR" ]; then
    # ⚠️ 不要 fetch 到"当前已检出的分支"上 —— git 会拒绝：
    #    `fatal: refusing to fetch into branch 'refs/heads/review/pr30' checked out at ...`
    #    所以先 fetch 到 FETCH_HEAD，再用**分离头指针**切过去。
    #    （也不需要为 PR 建分支名 —— 我们只是要验它。）
    git fetch --quiet origin "pull/$PR/head" || die "fetch PR #$PR 失败（编号对吗？）"
    git switch --quiet --detach FETCH_HEAD || die "切到 FETCH_HEAD 失败"
    TARGET="PR #$PR"
else
    git fetch --quiet origin "$BRANCH" || die "fetch 分支 $BRANCH 失败"
    git switch --quiet --detach FETCH_HEAD || die "切到 FETCH_HEAD 失败"
    TARGET="分支 $BRANCH"
fi
ok "已切到 $TARGET"
echo "     HEAD=$(git rev-parse --short HEAD)  $(git log --oneline -1)"

# ---------------------------------------------------------------------------
# 3. ★ 文件完整性预检 —— 不让"环境问题"污染"代码结论"
# ---------------------------------------------------------------------------
say "3/5 文件完整性预检（本机有丢文件的历史，这一步不能省）"
MISSING=$(git ls-files | while read -r f; do [ -f "$f" ] || echo "$f"; done)
MISS_COUNT=$(printf '%s' "$MISSING" | grep -c . || true)

if [ "${MISS_COUNT:-0}" -gt 0 ]; then
    warn "工作区缺 $MISS_COUNT 个已跟踪文件 —— 这是本机的已知问题（Issue #20），不是 PR 的问题"
    printf '%s\n' "$MISSING" | head -8 | sed 's/^/      - /'
    echo "    正在 git restore 恢复 ..."
    git restore . 2>&1 | tail -2
    MISSING2=$(git ls-files | while read -r f; do [ -f "$f" ] || echo "$f"; done)
    MISS_COUNT2=$(printf '%s' "$MISSING2" | grep -c . || true)
    if [ "${MISS_COUNT2:-0}" -gt 0 ]; then
        die "restore 之后仍缺 $MISS_COUNT2 个文件 —— 环境不可信，本次验证结论作废"
    fi
    ok "已恢复，继续验证"
else
    ok "文件完整（0 缺失）"
fi

# ---------------------------------------------------------------------------
# 4. 独立 venv + 依赖
# ---------------------------------------------------------------------------
say "4/5 独立 venv 与依赖"

# 找现有 venv：先找固定名，再找最近建过的 venv-<时间戳>（脚本自己建的）
if [ -z "$ENV_PY" ]; then
    for cand in "$VENV/Scripts/python.exe" "$VENV/bin/python"; do
        [ -x "$cand" ] && ENV_PY="$cand" && break
    done
fi
if [ -z "$ENV_PY" ]; then
    # 取最近一次自动建的（ls -dt 按时间倒序）
    cand=$(ls -dt "$WORK_ROOT"/venv-*/Scripts/python.exe 2>/dev/null | head -1)
    [ -n "$cand" ] && [ -x "$cand" ] && ENV_PY="$cand"
fi
if [ -z "$ENV_PY" ]; then
    cand=$(ls -dt "$WORK_ROOT"/venv-*/bin/python 2>/dev/null | head -1)
    [ -n "$cand" ] && [ -x "$cand" ] && ENV_PY="$cand"
fi

# 没有就自己建 —— 脚本要能独立跑，不能要求使用者先手工准备环境
if [ -z "$ENV_PY" ]; then
    echo "  没有现成 venv，自动建一个 ..."
    BASE_PY="$(find_base_python)" || die "找不到可用的基础 Python（可设 REVIEW_BASE_PYTHON 指定）"
    echo "  基础解释器：$BASE_PY"
    VENV="$WORK_ROOT/venv-$(date +%s)"
    mkdir -p "$WORK_ROOT"
    VENV_LOG="$WORK_ROOT/venv-create.log"
    # ⚠️ 必须传 **Windows 路径**给 python —— 它是原生程序，不认 /c/... ，
    #    而且失败时**不报错**，只是 Scripts/python.exe 不存在。
    #    （本项目在同一个坑上摔了 7 次，见 docs/dev-playbook.md §3.2）
    "$BASE_PY" -m venv "$(to_win "$VENV")" > "$VENV_LOG" 2>&1
    ENV_PY="$VENV/Scripts/python.exe"
    [ -x "$ENV_PY" ] || ENV_PY="$VENV/bin/python"
    if [ ! -x "$ENV_PY" ]; then
        warn "建 venv 失败，末尾输出："
        tail -6 "$VENV_LOG" | sed 's/^/      /'
        die "无法建立干净环境 —— 本次验证结论作废"
    fi
    ok "已建好：$VENV"
fi

# 依赖装好没有 —— **不能只看 pip 的退出码**。
#
# ⚠️ 本机实测：沙箱的「安全删除」机制会拦住 pip 替换旧文件，报
#      [safe-delete][SAFE_DELETE_FAIL_CLOSED] ... windows-sandbox-recycle-bin-unavailable
#    结果是 **pip 没装成，但错误信息埋在几十行输出里**，而后面测试会报
#      `ModuleNotFoundError: No module named 'alembic.config'`
#    —— **看起来像代码问题，其实是环境问题**。这正是本脚本存在的意义，
#    所以它自己首先不能犯这个错：**装完必须验证关键依赖真的能 import**。
PIP_LOG="$WORK_ROOT/pip.log"
PIP_INDEX="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"

# ⚠️ 刻意**不**执行 `pip install --upgrade pip setuptools wheel`。
#    本机的 safe-delete 机制会拦住对**已存在文件**的替换，
#    升级 pip 恰好就是"替换 pip 自己的文件" → 必然触发 → 整个安装失败。
#    venv 自带的 pip/setuptools 装这个项目完全够用。
install_deps() {
    {
        # ⚠️ setuptools / wheel 必须先装：Python 3.12+ 的 venv **默认不带 setuptools**，
        #    而下面用了 `--no-build-isolation`，缺它会报
        #      BackendUnavailable: Cannot import 'setuptools.build_meta'
        #    注意是**新装**（venv 里没有）→ 不需要替换文件 → 不会触发 safe-delete ✅
        #
        #    但**不要** `--upgrade pip` —— 那会替换 pip 自己的文件 → 被 safe-delete 拦死。
        #    venv 自带的 pip 完全够用。
        echo "--- setuptools / wheel ---"
        "$ENV_PY" -m pip install -q setuptools wheel -i "$PIP_INDEX"
        echo "--- 项目（含 dev）---"
        "$ENV_PY" -m pip install -q -e "backend[dev]" --no-build-isolation -i "$PIP_INDEX"
        echo "--- 解析测试所需（不在 [dev] 里，属 [parse]）---"
        "$ENV_PY" -m pip install -q "pymupdf>=1.25" "python-docx>=1.1" -i "$PIP_INDEX"
    } >> "$PIP_LOG" 2>&1
    # 真正的判据：关键依赖能不能导入（pip 退出码 0 不代表文件写成功了）
    "$ENV_PY" -c "import alembic.config, fastapi, pytest, httpx, sqlalchemy, ruff" 2>/dev/null
}

: > "$PIP_LOG"

# ★ 复用前先**只做导入检查** —— 通过了就完全不动它。
#
# ⚠️ 这里不能"无脑重装一遍"。本机实测：
#    往一个**已装好这些包**的 venv 里再 `pip install` → pip 要替换既有文件
#    → 被 safe-delete 拦住 → 安装失败 → 于是脚本会去建新 venv → **每次都要重来**
#    （有一轮跑了 18 分钟还没结束，就是这么循环出来的。）
#    所以：**导入通过就用，不通过才重建。**
if "$ENV_PY" -c "import alembic.config, fastapi, pytest, httpx, sqlalchemy, ruff" 2>/dev/null; then
    ok "依赖已就绪（直接复用，未做任何写入）：$ENV_PY"
else
    echo "  现有 venv 依赖不全，需要安装 ..."

    if install_deps; then
        ok "依赖已装好：$ENV_PY"
    else
        warn "依赖装完但**导入失败** —— 沙箱的 safe-delete 拦住了 pip 写文件"
        if grep -q "SAFE_DELETE_FAIL_CLOSED" "$PIP_LOG" 2>/dev/null; then
            echo "    pip 日志里确实有（这行就是关键证据）："
            grep -m1 "SAFE_DELETE_FAIL_CLOSED" "$PIP_LOG" | cut -c1-140 | sed 's/^/      /'
        fi
        echo
        echo "    原因：这个 venv 里已经有那些包，pip 要**替换**它们 → 被拦。"
        echo "    对策：换一个**全新 venv**（都是新文件，不需要替换）。"

        BASE_PY="$(find_base_python)" || die "找不到可用的基础 Python（可设 REVIEW_BASE_PYTHON）"
        echo "    基础解释器：$BASE_PY"

        # 不复用旧 venv、也不删它（本机的删除机制本身就不稳）—— 直接建一个新的带时间戳的
        VENV="$WORK_ROOT/venv-$(date +%s)"
        ENV_PY="$VENV/Scripts/python.exe"
        mkdir -p "$WORK_ROOT"

        VENV_LOG="$WORK_ROOT/venv-create.log"
        # ⚠️ 必须传 **Windows 路径**给 python —— 它是原生程序，不认 /c/... ，
        #    而且失败时**不报错**，只是 Scripts/python.exe 不存在。
        #    （本项目在同一个坑上摔了 7 次，见 docs/dev-playbook.md §3.2）
        "$BASE_PY" -m venv "$(to_win "$VENV")" > "$VENV_LOG" 2>&1
        [ -x "$ENV_PY" ] || ENV_PY="$VENV/bin/python"
        if [ ! -x "$ENV_PY" ]; then
            warn "建 venv 失败，末尾输出："
            tail -6 "$VENV_LOG" | sed 's/^/      /'
            die "无法建立干净环境 —— 本次验证结论作废"
        fi
        ok "新 venv：$VENV"

        : > "$PIP_LOG"
        if install_deps; then
            ok "依赖就绪（全新环境）：$ENV_PY"
        else
            warn "全新 venv 里依赖仍装不上，末尾日志："
            tail -8 "$PIP_LOG" | sed 's/^/      /'
            die "环境不可信，本次验证结论作废"
        fi
    fi
fi

# 关键：确认跑的是**克隆里**的代码，不是主仓库的
#
# ⚠️ 这里只比较「标记目录名」，不做完整路径比较 ——
#    因为 Python 返回的是 **Windows 路径**（`C:\Users\...`）而 `$WORK_ROOT` 是
#    **POSIX 路径**（`/c/Users/...`），直接比**永远不匹配**，
#    会把"验对了"误报成"验错了"。（这个 bug 第一次跑就撞上了。）
APPPATH=$("$ENV_PY" -c "import app,pathlib;print(pathlib.Path(app.__file__).parent)" 2>/dev/null)
MARKER=$(basename "$WORK_ROOT")   # 默认 .xizhi-review
case "$APPPATH" in
    "")             die "import app 失败 —— 依赖没装好？" ;;
    *"$MARKER"*)    ok "app 解析到克隆内部：$APPPATH" ;;
    *)              die "app 解析到了克隆之外（$APPPATH）—— 验证对象错了，结论无效" ;;
esac

# ---------------------------------------------------------------------------
# 5. 静态检查 + 测试
# ---------------------------------------------------------------------------
say "5/5 静态检查与测试"
cd "$CLONE/backend" || die "进不去 backend"

echo "  --- ruff check ---"
# 注意是 $(...) 不是 $((...)) —— 后者是**算术展开**，会把命令当算式算（踩过）
RUFF=$("$ENV_PY" -m ruff check --no-cache . 2>&1 | tail -3 || true)
printf '%s\n' "$RUFF" | sed 's/^/    /'

echo "  --- pytest ---"
# ⚠️ DB_PATH 会被 **Python（原生程序）** 读取，所以要转成 Windows 路径
export DB_PATH="$(to_win "$WORK_ROOT/test.db")"
RESULT_FILE="$WORK_ROOT/pytest-result.txt"
"$ENV_PY" -m pytest -p no:cacheprovider --tb=short -q -p no:warnings \
    -rs > "$RESULT_FILE" 2>&1
PYTEST_RC=$?

# ★ 判"通过还是失败"**只看退出码**，不数进度条上的字符。
#   理由：本机的环境会往输出里插 `[safe-delete]...` 之类的噪声行，
#   里面有字母 F/E/s —— 数字符会把"全绿"误报成"有失败"。
#   （这个假警报第一版就出现了。**在一个专门用来抓假象的工具里出现假象，
#     比没有这个工具更糟** —— 所以这里以退出码为唯一判据。）
if [ "$PYTEST_RC" -eq 0 ]; then
    echo "  ✅ pytest 全部通过（退出码 0）"
else
    echo "  ❌ pytest 失败（退出码 $PYTEST_RC）"
fi

# 进度条上的点/s 只用来给个**数量参考**，不参与判定
"$ENV_PY" - "$(to_win "$RESULT_FILE")" <<'PYEOF'
import pathlib
import re
import sys

txt = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
# 只取"进度条行"：形如 `....s....   [ 51%]`，且必须含百分号标记
bar_lines = [ln for ln in txt.splitlines() if re.search(r"\[\s*\d+%\]", ln)]
head = "".join(re.sub(r"\[\s*\d+%\]", "", ln) for ln in bar_lines)
passed, skipped = head.count("."), head.count("s")
print(f"    （参考数量：通过 {passed} / 跳过 {skipped}）")
print("    ※ 判通过与否只看退出码，不看上面的数量 —— 它是数进度条得到的，仅供参考")

skips = [ln for ln in txt.splitlines() if ln.startswith("SKIPPED")]
if skips:
    reasons = {}
    for s in skips:
        msg = s.split(":", 2)[-1].strip()[:70]
        reasons[msg] = reasons.get(msg, 0) + 1
    print(f"    跳过原因（{len(skips)} 项）：")
    for msg, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:5]:
        print(f"      [{n}x] {msg}")
PYEOF

if [ "$PYTEST_RC" -ne 0 ]; then
    echo
    echo "    ⚠️ 失败详情（日志尾部）："
    tail -25 "$RESULT_FILE" | sed 's/^/      /'
fi

echo "  退出码：$PYTEST_RC（0 = 全部通过）"

# ---------------------------------------------------------------------------
# 结论摘要
# ---------------------------------------------------------------------------
say "与 main 的差距"
git fetch --quiet origin main 2>&1 | tail -2
echo "  落后 main：$(git rev-list --count HEAD..origin/main 2>/dev/null) 个提交"
echo "  领先 main：$(git rev-list --count origin/main..HEAD 2>/dev/null) 个提交"
echo "  改动文件："
git diff --stat origin/main...HEAD 2>/dev/null | tail -20 | sed 's/^/    /'

if [ "$KEEP" -eq 0 ]; then
    :
else
    echo
    ok "克隆保留在 $CLONE（--keep）"
fi

printf '\n\033[1m=== 机器能判定的部分到此为止 ===\033[0m\n'
cat <<'NEXT'
  以下这些**脚本判不了**，必须由人读代码来定（清单见 docs/review-playbook.md）：
    · 作者的"声明"与"实现"是否一致（他报的数字要自己核对来源）
    · 指标是否自我实现（分母与分子是否同源 → 永远 100%）
    · 只在特定数据/版式下成立的阈值
    · 边界与守恒（区间开闭、差一个块的语义歧义、空输入）
    · "真空满足"（空库全绿没有意义）
    · 静默错误（不报错但结果错）—— 这一类最贵
NEXT
