#!/usr/bin/env bash
# 会话归档（归属：P2）
#
# ## 为什么需要它
#
# 赛事要求提交 **LearnBuddy 历史对话记录**作为评审参考（delivery-checklist 第 5 项）。
#
# ## ⚠️ 先说清楚一个限制（我不想假装能拿到）
#
# 我**读不到对话原文**。查过的位置：
#
# | 位置 | 实际是什么 |
# |---|---|
# | `~/.learnbuddy/audit-log/*.jsonl` | **工具命令审计**（`commandPreview`），没有对话正文 |
# | `~/.learnbuddy/workbuddy.db` 的 `sessions` 表 | **会话元数据**（model / mode / project_id），没有消息 |
# | `~/.learnbuddy/sessions/*.json`（452B × 67） | 会话索引，装不下对话 |
# | `app/session/Local Storage/leveldb/*.ldb` | 渲染进程存储，**扫不到可读的对话 JSON** |
#
# → **对话原文要么在应用自己的私有存储里，要么根本不在磁盘上。**
#    所以本脚本归档的是**我能可靠拿到的东西**，不是"完整对话记录"。
#
# ## 归档哪三类
#
# 1. **工具调用审计** —— `audit-log/YYYY-MM-DD.jsonl`（谁在什么时候跑了什么命令、放行还是拦下）
# 2. **工作日志** —— `.learnbuddy/memory/YYYY-MM-DD.md`（每轮做了什么、为什么）
# 3. **当天产出** —— git 提交清单（改了什么文件）
#
# 这三样合起来**能还原"这一天做了什么"**，但**不是逐字对话**。
# 逐字对话需要从应用里导出 —— 那一步我做不了，得人来。
#
# ## 用法
#
#     bash scripts/export-session.sh            # 导出今天
#     bash scripts/export-session.sh 2026-09-19 # 导出指定日期
#     bash scripts/export-session.sh --all      # 导出有记录的全部日期

set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"

OUT="$ROOT/exports/session-log"
HOME_DIR="${HOME:-/c/Users/admin}"
LB="$HOME_DIR/.learnbuddy"

mkdir -p "$OUT"

DATE="${1:-$(date +%Y-%m-%d)}"

make_one() {
    local d="$1"
    local dst="$OUT/$d"
    mkdir -p "$dst"
    local got=0

    # ① 工具调用审计
    local al="$LB/audit-log/$d.jsonl"
    if [ -f "$al" ]; then
        cp "$al" "$dst/tool-audit.jsonl" && got=$((got + 1))
    fi

    # ② 工作日志
    local mem="$ROOT/.learnbuddy/memory/$d.md"
    if [ -f "$mem" ]; then
        cp "$mem" "$dst/worklog.md" && got=$((got + 1))
    fi

    # ③ 当天 git 提交清单
    if git rev-parse --git-dir >/dev/null 2>&1; then
        {
            echo "# $d 提交清单"
            echo
            git log --since="$d 00:00" --until="$d 23:59" \
                --pretty=format:'## %h  %s%n%n作者：%an <%ae>%n时间：%ad%n%n%b%n---' \
                --date=iso 2>/dev/null
        } > "$dst/commits.md"
        got=$((got + 1))
    fi

    # 索引
    {
        echo "# $d 会话归档"
        echo
        echo "> ⚠️ **这不是逐字对话记录。**"
        echo "> 对话原文不在可读位置（详见 \`scripts/export-session.sh\` 开头的说明）。"
        echo "> 下面是**能可靠拿到的三类**：工具调用审计 / 工作日志 / 提交清单。"
        echo
        echo "| 文件 | 内容 |"
        echo "|---|---|"
        [ -f "$dst/tool-audit.jsonl" ] && echo "| \`tool-audit.jsonl\` | 工具调用审计（谁跑了什么命令、放行/拦下） |"
        [ -f "$dst/worklog.md" ] && echo "| \`worklog.md\` | 当日工作日志（做了什么、为什么） |"
        [ -f "$dst/commits.md" ] && echo "| \`commits.md\` | 当日提交清单 |"
        echo
        echo "导出时间：$(date '+%Y-%m-%d %H:%M:%S')"
    } > "$dst/README.md"

    echo "  $d -> $got 个文件"
}

if [ "$DATE" = "--all" ]; then
    echo "==> 导出全部日期"
    for f in "$LB"/audit-log/2*.jsonl; do
        [ -f "$f" ] || continue
        make_one "$(basename "$f" .jsonl)"
    done
else
    echo "==> 导出 $DATE"
    make_one "$DATE"
fi

echo
echo "输出目录：$OUT"
du -sh "$OUT" 2>/dev/null | awk '{print "  总大小：" $1}' || true
