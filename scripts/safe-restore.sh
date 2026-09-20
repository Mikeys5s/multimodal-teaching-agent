#!/usr/bin/env bash
# 安全恢复（归属：P2）—— **先保住未提交的改动，再 restore**
#
# ## 为什么需要它（这是今天第三次踩同一个坑之后的产物）
#
# 本机有「工作区文件被成批移走」的已知问题，遇到时标准修法是 `git restore .`。
#
# **但 `git restore .` 会把"被移走的文件"和"你刚改了一半的文件"一起处理**：
# 前者恢复（好），后者**回滚**（灾难）。
#
# 今天真实发生过三次：
#   1. `docs/review-playbook.md` 刚写好的规则被一起回滚
#   2. `backend/app/api/extract.py` 的改动被回滚，白做一轮
#   3. `backend/app/api/__init__.py` 的路由注册被回滚 → 端点全 405
#
# **三次都不是"不知道风险"，是"知道风险但没把它变成动作"。**
# 这个脚本就是那个动作。
#
# ## 它做什么
#
#   ① 先把未提交的改动 `git stash` 起来（**带名字，便于找回**）
#   ② 再 `git restore .` 恢复被移走的文件
#   ③ 告诉你 stash 的名字，以及怎么取回
#
# ## 用法
#
#   bash scripts/safe-restore.sh
#   bash scripts/safe-restore.sh --no-stash     # 确认没有未提交改动时，跳过 stash
#
# 取回改动：
#   git stash list                      # 看有哪些
#   git stash apply stash^{/名字}        # 应用但不删除
#   git stash pop stash^{/名字}          # 应用并删除

set -u
cd "$(dirname "$0")/.." || exit 1

NO_STASH=0
[ "${1:-}" = "--no-stash" ] && NO_STASH=1

DELETED=$(git status --porcelain | grep -c '^ D' || true)
DIRTY=$(git status --porcelain | grep -vc '^ D' || true)

echo "工作区状态：$DELETED 个已跟踪文件被移走，$DIRTY 项其它改动"
echo

if [ "${DIRTY:-0}" -gt 0 ] && [ "$NO_STASH" -eq 0 ]; then
    TAG="saferestore-$(date +%Y%m%d-%H%M%S)"
    echo "⚠️ 有 $DIRTY 项未提交改动 —— **先 stash 保住它们**（否则 restore 会把它们一起回滚）"
    git status --porcelain | grep -v '^ D' | head -8 | sed 's/^/      /'
    if git stash push -u -m "$TAG" >/dev/null 2>&1; then
        echo "   ✅ 已 stash：$TAG"
        echo "      取回：git stash pop \"stash^{/$TAG}\""
    else
        echo "   ❌ stash 失败 —— **中止**，请手工处理后再跑"
        exit 1
    fi
elif [ "${DIRTY:-0}" -gt 0 ]; then
    echo "⚠️ 有 $DIRTY 项未提交改动，但你指定了 --no-stash —— **这些改动会被 restore 回滚**"
    echo "   3 秒后继续（Ctrl-C 可中止）"
    # 用 bash 内建的 `read -t` 等待 —— 本环境的 `sleep` 命令缺失（见 dev-playbook §3.6）
    read -t 3 -r _ 2>/dev/null || true
fi

echo
echo "正在 git restore . ..."
git restore . || { echo "❌ restore 失败（可能有陈旧锁：把 .git/*.lock 改名即可）"; exit 1; }

LEFT=$(git status --porcelain | grep -c '^ D' || true)
if [ "${LEFT:-0}" -gt 0 ]; then
    echo "⚠️ 仍缺 $LEFT 个 —— 环境不可信，请人工检查"
    exit 1
fi

echo "✅ 已恢复。当前工作区改动 $(git status --porcelain | wc -l) 项"
