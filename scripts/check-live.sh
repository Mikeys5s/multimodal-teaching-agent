#!/usr/bin/env bash
# 从本机确认线上状态（归属：P2）
# ⚠️ 单独成脚本：多行 + 引号的命令塞进 Bash 工具会因引号嵌套报错（今天踩过多次）

set -u
BASE="${1:-http://120.77.177.171:8000}"

echo "=== $BASE ==="
echo

echo "--- 首页 ---"
curl -s --max-time 25 -o /tmp/xz.html -w "  HTTP %{http_code}   %{size_download} 字节\n" "$BASE/"
if grep -q "<title>" /tmp/xz.html; then
    grep -o "<title>[^<]*</title>" /tmp/xz.html | head -1 | sed 's/^/  /'
fi

echo
echo "--- 前端静态资源 ---"
grep -o 'src="[^"]*"' /tmp/xz.html | head -3 | sed 's/^/  /'
JS=$(grep -o 'src="[^"]*\.js"' /tmp/xz.html | head -1 | tr -d '"' | sed 's/^src=//')
if [ -n "$JS" ]; then
    curl -s --max-time 25 -o /dev/null -w "  JS $JS -> HTTP %{http_code}  %{size_download} 字节\n" "$BASE$JS"
fi
CSS=$(grep -o 'href="[^"]*\.css"' /tmp/xz.html | head -1 | tr -d '"' | sed 's/^href=//')
if [ -n "$CSS" ]; then
    curl -s --max-time 25 -o /dev/null -w "  CSS $CSS -> HTTP %{http_code}  %{size_download} 字节\n" "$BASE$CSS"
fi

echo
echo "--- 接口 ---"
for p in api/health api/review/queue api/knowledge-graph api/jobs api/knowledge-points; do
    printf "  %-30s" "$p"
    curl -s --max-time 20 -o /dev/null -w "HTTP %{http_code}\n" "$BASE/$p"
done

echo
echo "--- SPA 路由（前端应该回落 index.html）---"
for p in graph knowledge path qa; do
    printf "  /%-12s" "$p"
    curl -s --max-time 20 -o /dev/null -w "HTTP %{http_code}\n" "$BASE/$p"
done
