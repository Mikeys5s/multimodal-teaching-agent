#!/usr/bin/env bash
# 会话归档核对（归属：P2）
#
# ## 用途
#
# `scripts/export-session.sh --all` 跑完后，用它**核一遍归档是不是真的齐全**。
#
# `export-session.sh` 自己报的"3 个文件"**不可信**（见该脚本「已知缺陷」第 2 条），
# 本脚本绕开它，**直接从产物反查**：
#
# | 检查项 | 判据 | 为什么 |
# |---|---|---|
# | 每日文件齐全 | 4 个（三类 + README） | 脚本报数漏 README |
# | 提交数对账 | `commits.md` 条目数 == `git log main` 当日条数 | 抓"少计"（缺陷第 4 条） |
# | 提交总数对账 | 8 天之和 == `git rev-list --count HEAD` | 抓漏天 / 重复 |
# | 审计条数 | 每日 `tool-audit.jsonl` 行数 + 合计 | 零条 = 当天没记录 |
#
# ## ⚠️ 两个坑（都踩过）
#
# 1. **数提交不能用 `grep -c '^## '`** —— 提交正文里的 `## 小标题` 会被算成条目。
#    （9/23 实测：错误口径 41 条 vs 真实 12 条。）必须匹配 `^## [0-9a-f]{7,}  `。
# 2. **本机没有 `du` / `stat`** —— 用 `find -printf '%s\n'` + `awk` 算大小。
#    `export-session.sh` 里的 `du -sh` 因此永远打不出"总大小"。
#
# ## 用法
#
#     bash scripts/check-archive.sh
#
# 退出码：0 = 全部对账一致；1 = 有不一致（看 `不一致!` 标记）。

set -u
cd "$(dirname "$0")/.." || exit 1
OUT="exports/session-log"

[ -d "$OUT" ] || { echo "找不到 $OUT —— 先跑 scripts/export-session.sh --all"; exit 1; }

DAYS=$(for f in "$HOME"/.learnbuddy/audit-log/2*.jsonl; do
    [ -f "$f" ] && basename "$f" .jsonl
done | sort)

if [ -z "$DAYS" ]; then echo "audit-log 里没有任何日期文件"; exit 1; fi

head_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
echo "== 会话归档核对 =="
echo "当前分支：$head_branch"
if [ "$head_branch" != "main" ]; then
    echo "⚠️  不在 main 上 —— commits.md 用的是隐式 HEAD，可能少计队友提交。"
    echo "   建议先：git switch main && git pull --ff-only origin main"
fi
echo

printf "%-12s %8s %8s %8s %8s %8s\n" "日期" "文件" "审计" "日志行" "归档提交" "git提交"
printf '%.0s-' {1..62}; echo

bad=0
sum_a=0; sum_w=0; sum_c=0; sum_g=0; sum_files=0

for d in $DAYS; do
    dir="$OUT/$d"
    if [ ! -d "$dir" ]; then
        printf "%-12s %s\n" "$d" "目录缺失 —— 未导出!"
        bad=1; continue
    fi

    nf=$(find "$dir" -type f | wc -l)
    a=0; w=0; c=0
    [ -f "$dir/tool-audit.jsonl" ] && a=$(wc -l < "$dir/tool-audit.jsonl")
    [ -f "$dir/worklog.md" ]       && w=$(wc -l < "$dir/worklog.md")
    [ -f "$dir/commits.md" ]       && c=$(grep -cE '^## [0-9a-f]{7,}  ' "$dir/commits.md" || true)
    g=$(git log main --since="$d 00:00" --until="$d 23:59" --oneline 2>/dev/null | wc -l)

    flag=""
    [ "$nf" != "4" ]    && { flag="$flag 文件数≠4"; bad=1; }
    [ "$a" = "0" ]      && { flag="$flag 审计为空"; bad=1; }
    [ "$c" != "$g" ]    && { flag="$flag 提交不一致!"; bad=1; }

    printf "%-12s %8s %8s %8s %8s %8s%s\n" "$d" "$nf" "$a" "$w" "$c" "$g" "$flag"

    sum_files=$((sum_files + nf)); sum_a=$((sum_a + a)); sum_w=$((sum_w + w))
    sum_c=$((sum_c + c)); sum_g=$((sum_g + g))
done

echo
echo "合计：$sum_files 个文件（不含顶层索引）/ 审计 $sum_a 条 / 工作日志 $sum_w 行"
echo "提交：归档 $sum_c 条，git 按日累加 $sum_g 条"

head_count=$(git rev-list --count HEAD 2>/dev/null || echo "?")
echo "      git 全库 HEAD 共 $head_count 条"

if [ "$sum_c" != "$head_count" ]; then
    echo "❌ 归档提交合计($sum_c) 与 HEAD 总数($head_count) 不一致 —— 有漏计或重复"
    bad=1
else
    echo "✅ 归档提交合计与 HEAD 总数一致，无遗漏/重复"
fi

bytes=$(find "$OUT" -type f -printf '%s\n' | awk '{s+=$1} END {print s+0}')
awk -v b="$bytes" 'BEGIN {printf "总大小：%d 字节 = %.2f MB\n", b, b/1048576}'

echo
[ "$bad" = "0" ] && echo "== 核对通过 ==" || echo "== 核对不通过，见上方标记 =="
exit "$bad"
