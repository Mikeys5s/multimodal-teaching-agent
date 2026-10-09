#!/usr/bin/env bash
# 一次推到**全部三个 remote**，**并核对结果**。
#
# ## 为什么需要它（2026-10-09 的教训）
#
# 我这两天写的每个 `commit_*.sh` 里都写死了：
#
#     for r in origin backup; do git push $r main; done
#
# **两个都是 GitHub**（origin=RyeYen/… · backup=Mikeys5s/…）
# ⇒ **`gitee` 一次都没推过** ⇒ **Gitee 落后两周**（停在 9/25）。
#
# ⚠️ 而 **Gitee 才是交付要求用的那个仓库** ——
# **评委点开看到的是两周前的代码**（没有依赖图、没有答疑修复）。
#
# ## 修法（两层）
#
#   ① **不再在脚本里写死 remote 列表** —— 一律调这个脚本
#   ② **推完必须核对**（不能只看 `git push` 没报错就以为成了）
#
# ## 用法
#
#     bash scripts/push-all.sh                 # 推 main
#     bash scripts/push-all.sh feat/xxx        # 推别的分支
set -u
cd /d/muti_tagent || exit 1

BRANCH="${1:-main}"
REMOTES="origin backup gitee"

echo "==> 推 $BRANCH 到：$REMOTES"
FAIL=0
for r in $REMOTES; do
    out=$(git push "$r" "$BRANCH" 2>&1 | tail -2)
    if echo "$out" | grep -qE "\.\.[0-9a-f]{7}|up-to-date|new branch"; then
        echo "  ✅ $r: $(echo "$out" | tail -1 | tr -d '\r')"
    else
        echo "  ⚠️ $r: $(echo "$out" | tail -1 | tr -d '\r')"
        FAIL=1
    fi
done

echo
echo "==> 核对（**三个 remote 的 $BRANCH 都该指向同一个 commit**）"
LOCAL=$(git rev-parse "$BRANCH")
printf "  %-10s %s\n" "local" "${LOCAL:0:7}"
for r in $REMOTES; do
    # ⚠️ ls-remote 会给两行（HEAD + refs/heads/<branch>）⇒ **必须限定 ref 并取第一行**
    R=$(git ls-remote "$r" "refs/heads/$BRANCH" 2>/dev/null | head -1 | cut -f1)
    if [ "$R" = "$LOCAL" ]; then
        echo "  ✅ $r  ${R:0:7}（一致）"
    else
        echo "  ❌ $r  ${R:0:7}（**与本地不一致**）"
        FAIL=1
    fi
done

echo
if [ "$FAIL" = "0" ]; then
    echo "✅ 三个 remote 全部同步到 ${LOCAL:0:7}"
else
    echo "❌ **有 remote 没同步上** —— 看上面哪一行"
    echo "   ⚠️ gitee 若报凭据错误：需要用带 token 的 URL 推（见 docs 里的记录）"
fi
exit "$FAIL"
