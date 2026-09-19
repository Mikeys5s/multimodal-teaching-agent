#!/usr/bin/env bash
# 部署后验证（归属：P2）
#
# ⚠️ 单独写成脚本文件，是因为**多行 SSH 命令塞进 Bash 工具的命令字符串会因引号嵌套报错**。
#    这个坑今天踩了不止一次：凡是"多行 + 引号"的命令，一律落成脚本再跑。

set -u
HOST="${XIZHI_HOST:-xizhi}"
PUBLIC="${XIZHI_PUBLIC:-http://120.77.177.171:8000}"

ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" 'bash -s' <<'REMOTE'
set -u
echo "=== 容器 ==="
docker ps --filter name=xizhi --format "{{.Status}}"
echo
echo "=== 首页 ==="
curl -s -o /tmp/idx -w "HTTP %{http_code}   大小 %{size_download} 字节\n" http://127.0.0.1:8000/
if grep -q "<title>" /tmp/idx 2>/dev/null; then
    grep -o "<title>[^<]*</title>" /tmp/idx | head -1 | sed 's/^/  /'
else
    echo "  （响应里没有 <title> —— 可能还是旧的兜底页）"
fi
echo
echo "=== 前端产物 ==="
docker exec xizhi sh -c 'ls /app/frontend/dist 2>/dev/null | head -6' || echo "  （容器里没有 dist）"
echo
echo "=== 健康接口 ==="
curl -s http://127.0.0.1:8000/api/health
echo
echo
echo "=== 端点总数（应为 31）==="
curl -s http://127.0.0.1:8000/openapi.json | grep -o '"/api/[^"]*"' | sort -u | wc -l
echo
echo "=== 今天新搭的 hard 边通道（review 三个端点）==="
for p in review/queue review/import-edges review/decide; do
    echo -n "  /api/$p  -> "
    curl -s -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:8000/api/$p"
done
echo
echo "=== 解析链能不能起来（今天缺 python-docx 的地方）==="
docker exec xizhi python -c "import app.parse, app.pipeline, pymupdf, docx, pptx; print('  解析链依赖齐全')" 2>&1 | tail -3
REMOTE

echo
echo "=== 外网可达性（从本机）==="
curl -s -o /dev/null -w "  $PUBLIC  ->  HTTP %{http_code}\n" --max-time 20 "$PUBLIC" || echo "  连不上"
