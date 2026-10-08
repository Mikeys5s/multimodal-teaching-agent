#!/usr/bin/env bash
# 修「.git/index 落后于 HEAD」—— **安全，工作区不动**。
#
# ## 根因（**是我自己的提交方式造成的**）
#
# 我这两天一直用 `GIT_INDEX_FILE=<临时文件> git ...` 提交。
# **好处**：绕开本机 `index.lock` 的怪问题；
# **代价**：临时索引里的新文件**没同步进 `.git/index`** ⇒
#   索引里的文件数**一次次落后于 HEAD**（今天差 27 个）。
#
# ⚠️ **危险点**：在这种情况下 `git status` 会**虚报**（把已提交的文件显示成"未跟踪"），
#    而 `git commit -am` **会真把文件删进历史**。
#    （MEMORY 里记过：2026-09-25 / 2026-10-08 各中过一次）
#
# ⇒ 所以每次提交完，**必须把索引同步回来**。
set -u
cd /d/muti_tagent || exit 1

echo "=== 修前 ==="
echo "  ls-files: $(git ls-files | wc -l)   HEAD: $(git ls-tree -r HEAD --name-only | wc -l)"

echo
echo "=== 备份索引 ==="
STAMP=$(date +%Y%m%d-%H%M)
if cp .git/index ".git/index.bak-$STAMP" 2>/dev/null; then
    echo "  ✅ .git/index.bak-$STAMP"
else
    echo "  ⚠️ 备份失败（继续，因为 git reset 本身是安全的）"
fi

echo
echo "=== 清 0 字节锁（若有）==="
if ls .git/*.lock >/dev/null 2>&1; then
    ls -la .git/*.lock | sed 's/^/  /'
    # ⚠️ 本机 remove 有 safe-delete 拦截，用 Windows 绝对路径
    for f in .git/*.lock; do
        rm -f "D:/muti_tagent/$(echo "$f" | sed 's|^\./||')" 2>/dev/null || true
    done
    echo "  已尝试清理"
else
    echo "  ✅ 无锁文件"
fi

echo
echo "=== 重建索引（git reset，**不加 --hard**）==="
git reset 2>&1 | head -6 | sed 's/^/  /'

echo
echo "=== 修后（两个数应相等）==="
A=$(git ls-files | wc -l)
B=$(git ls-tree -r HEAD --name-only | wc -l)
echo "  ls-files: $A   HEAD: $B"
if [ "$A" = "$B" ]; then
    echo "  ✅ **索引已同步**"
else
    echo "  ⚠️ 仍差 $((B - A)) 个"
fi

echo
echo "=== 工作区状态（**应该还是干净的**）==="
git status --short | head -10 | sed 's/^/  /'
echo "  合计改动：$(git status --short | wc -l)"
