#!/usr/bin/env bash
# git 索引健康检查 —— **会毁掉交付的那类风险，先查它**。
#
# ## 判据（来自 skill `windows-restricted-dev-env` 坑 11b）
#
#   · `git ls-files | wc -l`  **必须等于**  `git ls-tree -r HEAD --name-only | wc -l`
#   · `.git/*.lock` 里**不该有 0 字节文件**（有 ⇒ 某次写失败过）
#   · `.git/index` 的 mtime **不该早于**最近一次提交
#
# ## 为什么这条杀伤力大（2026-09-25、2026-10-08 各中一次）
#
# 索引 mtime 一旦冻结，此后新提交**从未写进索引** ⇒
# `git status` 会把 HEAD 已跟踪的文件报成「暂存删除 + 未跟踪」，
# **看着像有人取消了跟踪** —— 而 `git commit -am` 会**真把这些文件删进历史**。
set -u
cd /d/muti_tagent || exit 1

echo "=== ① 两个数（判据：必须相等）==="
A=$(git ls-files | wc -l)
B=$(git ls-tree -r HEAD --name-only | wc -l)
echo "  git ls-files         : $A"
echo "  git ls-tree -r HEAD  : $B"
if [ "$A" = "$B" ]; then
    echo "  ✅ 一致（索引健康）"
else
    echo "  ❌ **不一致 —— 差 $((B - A)) 个**"
fi

echo
echo "=== ② 索引 mtime vs 最近提交 ==="
ls -la --time-style=long-iso .git/index 2>/dev/null | awk '{print "  index mtime : " $6 " " $7}'
git log -1 --format="  最近提交    : %ad  %h  %s" --date=iso

echo
echo "=== ③ HEAD 有、索引没有的文件（前 25）==="
git ls-tree -r HEAD --name-only | sort > /tmp/x_head.txt
git ls-files | sort > /tmp/x_idx.txt
comm -23 /tmp/x_head.txt /tmp/x_idx.txt | head -25 | sed 's/^/  /'
echo "  合计：$(comm -23 /tmp/x_head.txt /tmp/x_idx.txt | wc -l)"

echo
echo "=== ④ 0 字节锁文件 ==="
if ls .git/*.lock >/dev/null 2>&1; then
    ls -la .git/*.lock | sed 's/^/  /'
else
    echo "  ✅ 无"
fi

echo
echo "=== ⑤ 结论 ==="
if [ "$A" = "$B" ]; then
    echo "  ✅ 索引健康 —— 可以正常提交"
else
    echo "  ❌ **索引不健康**。修法（**工作区不动**）："
    echo "     ① 备份：cp .git/index .git/index.bak-\$(date +%Y%m%d-%H%M)"
    echo "     ② 清 0 字节锁：rm -f .git/*.lock"
    echo "     ③ 重建索引：git reset       ← **不要加 --hard**"
    echo "     ⚠️ **绝不能用 `git commit -am`**（那会把文件真删进历史）"
fi
