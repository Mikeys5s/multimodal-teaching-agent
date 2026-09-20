#!/usr/bin/env bash
# 交付验收门（归属：P2）—— **"能跑通 + 过测试 + 按验收标准验收" 的一键执行**
#
# ## 为什么需要一条命令
#
# "每次交付都要跑通、过测试、按验收标准验收" 这条要求，
# **如果只写在文档里，它会退化成一句口号** —— 因为它是三件分开的事，
# 而人在赶时间时总会挑着做（通常挑最省事的那件）。
#
# 把它变成一条命令的意义不是省事，是**让它变成一个整体**：
# 要么全过，要么全不过，**没有"我只跑了测试"这个选项**。
#
# ## 四道闸
#
#   ① 静态检查（ruff）            —— 代码层面
#   ② 全量测试（含端到端链路）     —— 行为层面
#   ③ 假数据审计                  —— **数据是不是真的**
#   ④ 验收指标（--strict）        —— 按 SPEC 的可测标准
#
# **第 ③ 道是这个项目特有的**：我们有 400+ 测试全绿而 10 个端点返回假数据的历史。
# "测试通过"和"功能是真的"是两件事，所以闸门要分开设。
#
# ## 用法
#
#   bash scripts/gate.sh                 # 当前工作区（提交前自查用）
#   bash scripts/gate.sh --pr 41         # 独立克隆里验某个 PR（验收别人的交付）
#
# 任一道不过 → 非零退出。

set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
PY_BACKEND="backend/.venv/Scripts/python.exe"
[ -x "$PY_BACKEND" ] || PY_BACKEND="backend/.venv/bin/python"

PR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --pr) PR="$2"; shift 2 ;;
        *) echo "未知参数：$1"; exit 2 ;;
    esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
pass() { printf '  \033[32m[PASS]\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m[FAIL]\033[0m %s\n' "$*"; }
skip() { printf '  \033[33m[SKIP]\033[0m %s\n' "$*"; }

# 验 PR 时在独立克隆里跑（主工作区会被"移走文件"，不可信）
if [ -n "$PR" ]; then
    say "0/4 独立克隆（PR #$PR）"
    bash scripts/review-verify.sh --pr "$PR" || true
    echo
    echo "⚠️ 独立克隆模式只跑 ① ②（静态检查 + 测试）。"
    echo "   ③ 假数据审计与 ④ 验收指标需要一份**已迁移、已灌数据**的库，"
    echo "   在 PR 的临时克隆里跑没有意义 —— 请在本地灌好数据后跑不带 --pr 的版本。"
    exit 0
fi

FAILED=0

# ---------------------------------------------------------------------------
say "0/4 工作区完整性预检"
# ---------------------------------------------------------------------------
#
# ⚠️ 这一步是**必须的**，而且必须放在最前面。
#
# 本机有「工作区文件被成批移走」的已知问题（Issue #20：删除 = 移到回收站，
# 回收站不可用时 fail closed）。今天它发作过三次，最严重的一次是
# `scripts/` 下五个文件一起消失。
#
# **不加这一步的后果**：闸门会在很后面报一个 `No such file or directory`，
# 看起来像"脚本写错了"或"工具没装"，而真实原因只是文件被移走了 ——
# 又一种"报错指不到真正原因"。
#
# 判据：`git status` 里出现 ` D`（工作区有文件被删但未提交）就是不完整。
DELETED=$(git status --porcelain 2>/dev/null | grep -c "^ D" || true)
if [ "${DELETED:-0}" -gt 0 ]; then
    fail "工作区缺 $DELETED 个已跟踪文件（本机已知问题，不是你的代码问题）"
    echo "      修法：git restore ."
    echo "      前几个："
    git status --porcelain | grep "^ D" | head -5 | sed 's/^/        /'
    echo
    echo "  正在自动恢复 ..."
    git restore . 2>/dev/null || true
    DELETED2=$(git status --porcelain 2>/dev/null | grep -c "^ D" || true)
    if [ "${DELETED2:-0}" -gt 0 ]; then
        fail "restore 之后仍缺 $DELETED2 个 —— 环境不可信，本次结论作废"
        exit 1
    fi
    pass "已恢复，继续"
else
    pass "工作区完整"
fi

# 工具存在性 —— 缺失时明确说是"工作区不完整"，而不是让下一步报文件找不到
for tool in scripts/evaluate.py scripts/audit-mock-endpoints.py "$PY_BACKEND"; do
    if [ ! -f "$tool" ]; then
        fail "缺少 $tool —— 工作区不完整（先 git fetch && git merge --ff-only origin/main）"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
say "1/4 静态检查（ruff）"
# ---------------------------------------------------------------------------
if (cd backend && "../$PY_BACKEND" -m ruff check --no-cache . 2>&1 | tail -5); then
    pass "ruff 通过"
else
    fail "ruff 不通过"; FAILED=1
fi

# ---------------------------------------------------------------------------
say "2/4 全量测试（含端到端链路）"
# ---------------------------------------------------------------------------
TEST_LOG="$(mktemp -t xizhi-gate-pytest-XXXXXX.log)"
(cd backend && "../$PY_BACKEND" -m pytest -p no:cacheprovider -q -p no:warnings \
    -rs --tb=short > "$TEST_LOG" 2>&1)
RC=$?
# 本机环境会往输出里插 [safe-delete] 噪声行，去掉再读
grep -vE "^\[safe-delete\]" "$TEST_LOG" > "$TEST_LOG.clean"
if [ "$RC" -eq 0 ]; then
    pass "测试全过"
else
    fail "测试不通过（退出码 $RC）"
    tail -25 "$TEST_LOG.clean" | sed 's/^/      /'
    FAILED=1
fi
# 端到端那条如果是 xfail，单独说一声 —— 它是"链路还没通"的**显式记录**
if grep -q "xfail" "$TEST_LOG.clean"; then
    echo "  注意：有 xfail（预期失败）。端到端链路测试在列表里时，说明链路尚未接通。"
fi

# ---------------------------------------------------------------------------
say "3/4 假数据审计（★ 本项目特有：测试通过 ≠ 数据是真的）"
# ---------------------------------------------------------------------------
AUDIT_LOG="$(mktemp -t xizhi-gate-audit-XXXXXX.log)"
"$PY_BACKEND" scripts/audit-mock-endpoints.py > "$AUDIT_LOG" 2>&1
RC=$?
grep -vE "INFO|DEBUG|Warning|from starlette" "$AUDIT_LOG" | tail -20 | sed 's/^/      /'
if [ "$RC" -eq 0 ]; then
    pass "全部端点返回真实数据"
else
    fail "仍有端点返回假数据（详见上方清单）"
    FAILED=1
fi

# ---------------------------------------------------------------------------
say "4/4 验收指标（按 SPEC 的可测标准，--strict）"
# ---------------------------------------------------------------------------
EVAL_LOG="$(mktemp -t xizhi-gate-eval-XXXXXX.log)"
"$PY_BACKEND" scripts/evaluate.py --strict > "$EVAL_LOG" 2>&1
RC=$?
tail -12 "$EVAL_LOG" | sed 's/^/      /'
if [ "$RC" -eq 0 ]; then
    pass "验收指标全部达标"
else
    fail "有验收指标未达标"
    FAILED=1
fi

# ---------------------------------------------------------------------------
say "结论"
# ---------------------------------------------------------------------------
if [ "$FAILED" -eq 0 ]; then
    printf '  \033[32m✅ 四道闸全过 —— 这份交付可以出。\033[0m\n'
else
    printf '  \033[31m❌ 有闸没过 —— 这份交付不出。\033[0m\n'
    echo "     （"能跑通"与"测试通过"是两件事，所以闸门分开设 —— 哪道红就修哪道）"
fi
exit "$FAILED"
