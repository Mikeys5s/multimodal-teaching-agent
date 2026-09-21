#!/usr/bin/env bash
# 跑后端测试 —— **一行命令，不依赖任何环境记忆**。
#
# ## 为什么需要这个文件
#
# 2026-09-21 发现两个问题：
#
#   ① **本机 `.venv` 缺 `python-pptx`**（被清理工具删过），于是
#      `import app.main` 失败 → **整套测试跑不起来**。
#   ② **生产容器里没有 pytest、也没有 `tests/`**（不在 Dockerfile 的 COPY 里），
#      所以"在容器里跑测试"这条路过不去。
#
#   结果就是我前几轮一直在"两边都不行"的夹缝里凑合验证 ——
#   而且**我报过一次「24 个测试全过」，那是在一个我临时补过依赖的容器里跑的，
#   别人照我的步骤复现不出来。**
#
# **这个脚本的目的是：让"怎么跑测试"这件事不再是某个人脑子里的知识。**
#
# ## 用法
#
#   bash scripts/test.sh              # 跑全部
#   bash scripts/test.sh tutor        # 只跑文件名含 tutor 的
#   bash scripts/test.sh --cov        # 带覆盖率
set -u

cd "$(dirname "$0")/.." || exit 1
PY="backend/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="backend/.venv/bin/python"
if [ ! -x "$PY" ]; then
    echo "❌ 找不到虚拟环境：backend/.venv"
    echo "   先跑：bash scripts/setup-venv.sh"
    exit 1
fi

# ---- 依赖自检：缺什么就直接说，不要让 pytest 报一个难懂的 ImportError ----
echo "=== 依赖自检 ==="
MISSING=""
for m in pytest fastapi sqlalchemy alembic httpx pptx; do
    if "$PY" -c "import $m" 2>/dev/null; then
        printf "  ✅ %s\n" "$m"
    else
        printf "  ❌ %s\n" "$m"
        MISSING="$MISSING $m"
    fi
done

if [ -n "$MISSING" ]; then
    echo
    echo "⚠️ 缺少依赖：$MISSING"
    echo "   装法（**用官方源** —— 清华源上曾经找不到 python-pptx）："
    echo "     $PY -m pip install --index-url https://pypi.org/simple \\"
    for m in $MISSING; do
        [ "$m" = "pptx" ] && echo "         python-pptx \\" || echo "         $m \\"
    done
    echo "         # （去掉末行反斜杠）"
    exit 1
fi

# ---- 跑测试 ----
FILTER="${1:-}"
EXTRA=""
ARGS=""
case "$FILTER" in
    --cov) EXTRA="--cov=app --cov-report=term-missing" ;;
    "")    ;;
    *)     ARGS="-k $FILTER" ;;
esac

echo
echo "=== 跑测试 ==="
cd backend || exit 1
exec "../$PY" -m pytest -q -p no:cacheprovider $EXTRA $ARGS tests/
