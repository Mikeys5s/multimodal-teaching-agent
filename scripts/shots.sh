#!/usr/bin/env bash
# 批量截四个主页面 —— 供 PPT 使用。
#
# ## 为什么用 chrome.exe 直接截，而不是 agent-browser
#
# `agent-browser` 在这台机器上**起不来**：
#
#     ✗ Auto-launch failed: CDP WebSocket connect failed:
#       IO error: 远程主机强迫关闭了一个现有的连接。 (os error 10054)
#
# 而且它的 shim 脚本本身还有个**路径 bug**（今天这个根因的第 5 次复现）：
#
#     Cannot find module 'd:\c\Users\admin\AppData\Roaming\npm\node_modules\...'
#     （`/c/Users/...` 被前面加了个 `d:`）
#
# **但 Chrome 是现成的**（`ms-playwright/chromium-1223/chrome-win64/chrome.exe`），
# 而 Chrome 自带 `--headless --screenshot` —— **一行命令就能截图，不需要任何封装**。
#
# ## 用法
#
#   bash scripts/shots.sh
set -u
cd "$(dirname "$0")/.." || exit 1

CHROME="C:/Users/admin/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe"
if [ ! -x "$CHROME" ]; then
    echo "❌ 找不到 chrome.exe：$CHROME"
    echo "   找法：find \"\$LOCALAPPDATA/ms-playwright\" -name chrome.exe"
    exit 1
fi

BASE="${1:-http://120.77.177.171:8000}"
OUT="$(pwd)/docs/screenshots"
mkdir -p "$OUT"

# 页面清单：路径 | 文件名 | 说明
PAGES=(
  "/|01-overview|概览（入口）"
  "/materials|02-materials|素材工作台"
  "/graph|03-graph|知识图谱（含复核抽屉入口）"
  "/path|04-path|学习路径"
  "/tutor|05-tutor|答疑辅导"
  "/report|06-report|质量报告"
)

echo "=== 截图（目标 $BASE）==="
OK=0
for row in "${PAGES[@]}"; do
    IFS='|' read -r path name desc <<< "$row"
    url="${BASE}${path}"
    png="${OUT}/${name}.png"
    rm -f "$png" 2>/dev/null

    # --virtual-time-budget：等 JS 跑完再截（SPA 必须等数据回来）
    # --window-size：手册要求桌面端 1440×900
    "$CHROME" --headless --disable-gpu --no-sandbox --hide-scrollbars \
        --window-size=1440,900 --virtual-time-budget=9000 \
        --screenshot="$(printf '%s' "$png" | sed -E 's|^/([a-zA-Z])/|\1:/|')" \
        "$url" > /dev/null 2>&1

    if [ -f "$png" ]; then
        sz="$(wc -c < "$png" | tr -d ' ')"
        printf "  ✅ %-14s %-22s %8s 字节  %s\n" "$name" "$path" "$sz" "$desc"
        OK=$((OK + 1))
    else
        printf "  ❌ %-14s %-22s 失败\n" "$name" "$path"
    fi
done

echo
echo "  成功 $OK / ${#PAGES[@]}"
echo "  输出目录：$OUT"

rm -f "$OUT/_probe.png" 2>/dev/null
