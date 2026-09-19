#!/usr/bin/env bash
# 安全提交（归属：P2）—— **禁止在"工作区被掏空"的状态下提交**
#
# ## 为什么必须有这个脚本
#
# 本机有「工作区文件被成批移走」的已知问题（Issue #20：删除 = 移到回收站，
# 回收站不可用时 fail closed）。今天它发作过 **5 次**。
#
# 而它真正的杀伤力不在"文件没了"—— 那个 `git restore .` 就能救。
# **杀伤力在"没注意就 `git add -A && git commit`"**：
# 那会把"删除"当成一次正常改动**提交进历史**，
# 于是 `git restore` 也救不回来了（它恢复的是"已提交的删除"）。
#
# 这个坑今天真实发生过：`backend/app/pipeline/parse_material.py`
# 在一次"补单测"的提交里被静默删掉，直到下次跑测试报
# `ModuleNotFoundError: No module named 'app.pipeline.parse_material'` 才发现。
#
# ## 用法（代替 `git add -A && git commit`）
#
#   bash scripts/safe-commit.sh "feat: 干了什么"
#
# 它会：① 检查有没有 ` D`（被移走但未提交）→ 有就先 `git restore .` 并**告诉你**；
#       ② 再暂存与提交；③ 打印本次提交的文件清单，**让你亲眼确认没有多删东西**。

set -u
cd "$(dirname "$0")/.." || exit 1

MSG="${1:-}"
if [ -z "$MSG" ]; then
    echo "用法：bash scripts/safe-commit.sh \"类型: 说明\""
    exit 2
fi

# ---- ① 关键一步：先看有没有被移走的文件 -------------------------------
DELETED=$(git status --porcelain | grep -c '^ D' || true)
if [ "${DELETED:-0}" -gt 0 ]; then
    echo "⚠️ 检测到 $DELETED 个已跟踪文件在工作区里被删（本机已知问题，不是你的改动）"
    git status --porcelain | grep '^ D' | head -8 | sed 's/^/      /'
    echo "   → 正在 git restore . 恢复它们（**否则这次提交会把删除一起提交进去**）"
    git restore . || { echo "❌ restore 失败，中止提交"; exit 1; }
    echo "   ✅ 已恢复"
    echo
fi

# ---- ② 暂存 + 提交 -----------------------------------------------------
git add -A || exit 1

echo "本次将提交这些文件："
git diff --cached --name-status | sed 's/^/      /'
echo

git commit -q -m "$MSG" || { echo "❌ 提交失败"; exit 1; }
echo "✅ 已提交 $(git rev-parse --short HEAD)  $MSG"
