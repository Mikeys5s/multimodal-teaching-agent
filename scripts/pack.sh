#!/usr/bin/env bash
# 打一个交付用的源码包（`.tar.gz`）。
#
# ## 为什么要它（`docs/delivery-checklist.md` 的 A5）
#
# > **代码已附 `.zip` 或 `.tar.gz`，且打包后复查过一次无密钥、无大文件**
#
# 仓库**当前是私有的** —— 转 public 在别人手上，
# **打包是"即使转不了 public 也能交"的兜底**（`deliverable-plan.md` §一 第 4 项）。
#
# ## 这个脚本与"随手 tar 一下"的区别
#
# **它自己会复查三件事**：无密钥 / 无大文件 / 无环境缓存，**不通过就非零退出**。
#
# ---
#
# ## ⚠️⚠️ 第一版是**假的** —— 记在这里，因为它是个典型错误
#
# 第一版这样写：
#
#     SECRETS="$(tar -tzf "$OUT" | grep -E '\.env|\.key' || true)"
#     if [ -n "$SECRETS" ]; then ... else echo "✅ 无密钥"; fi
#
# 而那次 `tar` **本身就失败了**（Windows 的 `tar.exe` 不支持 `--transform`，
# 包压根没生成）：
#
#     tar.exe: Option --transform is not supported
#     tar.exe: Error opening archive: Failed to open ...
#     ✅ 无疑似密钥文件        ← ⚠️ 假通过
#     ✅ 无 > 5MB 的文件       ← ⚠️ 假通过
#     ✅ 复查通过：无密钥、无大文件、无环境缓存   ← 而且 exit 0
#
# **命令失败 → 输出为空 → grep 没匹配到 → 判"通过"。**
#
# **这和同一天遇到的 `mergeable is None`（GitHub 还在算）
# 与 `r.passed is None`（样本为 0）是同一类：
# 把「没有输出」当成了「没有问题」。**
#
# ## 本脚本的两条纪律
#
# 1. **每个判据都先确认「命令成功」，再判内容。**
# 2. **Windows 上的两个坑**：不能用 `--transform`；不能用 `mktemp -d`
#    （它给 `/tmp/...`，而 Windows 的 `tar.exe` 不认）。
#    **临时目录一律建在项目内。**
set -u

cd "$(dirname "$0")/.." || exit 1
NAME="xizhi-source-$(date +%Y%m%d-%H%M)"
OUT="$(pwd)/${NAME}.tar.gz"
FILELIST="$(pwd)/.pack-files.txt"
WORK="$(pwd)/.pack-work"
FAIL=0

fail() { echo "  ❌ $*"; FAIL=1; }
ok()   { echo "  ✅ $*"; }

# ⚠️⚠️ **必须把 MSYS 路径转成 Windows 路径**（2026-09-21，踩了三次）
#
# Git Bash 里 `$(pwd)` 得到的是 `/d/muti_tagent` —— **那是 MSYS 的虚拟路径**。
# 而 **`tar.exe` 是原生 Windows 程序，它只认 `D:/muti_tagent`**：
#
#     tar.exe: could not chdir to '/d/muti_tagent/.pack-work'
#
# **这和同一天遇到的「删除工具拿到 `/d/...` 被判 relative path rejected」
# 是同一个根因** —— 在 Windows 上，**原生程序与 MSYS 程序的路径约定不同**。
#
# 用法：只用 MSYS 侧命令（`cp` / `find` / `grep`）时保持 `/d/...`；
#       **要交给 `tar.exe` / `docker.exe` 这类原生程序的，一律过 `winpath`。**
if command -v cygpath > /dev/null 2>&1; then
    winpath() { cygpath -w "$1"; }
else
    winpath() { printf '%s' "$1" | sed -E 's|^/([a-zA-Z])/|\1:/|'; }
fi

cleanup() { rm -rf "$WORK" "$FILELIST" 2>/dev/null; }
trap cleanup EXIT

echo "=== ① 用 git 列文件（只打已跟踪的 —— 天然排除 .env / .venv / 缓存）==="
if ! git ls-files > "$FILELIST" 2>/dev/null; then
    fail "git ls-files 失败"
    exit 1
fi
N="$(grep -c . "$FILELIST")"
echo "  已跟踪文件：$N 个"
[ "$N" -gt 50 ] || { fail "只列到 $N 个文件，不像一个完整仓库"; exit 1; }

echo
echo "=== ② 打包 ==="
rm -rf "$WORK"; mkdir -p "$WORK/$NAME"
while IFS= read -r f; do
    mkdir -p "$WORK/$NAME/$(dirname "$f")"
    cp "$f" "$WORK/$NAME/$f" 2>/dev/null
done < "$FILELIST"

rm -f "$OUT"
# ★ `tar.exe` 是原生程序 → **路径必须过 `winpath`**
if ! tar -czf "$(winpath "$OUT")" -C "$(winpath "$WORK")" "$NAME" 2>/dev/null; then
    echo "  （tar 的原始报错，别猜：）"
    tar -czf "$(winpath "$OUT")" -C "$(winpath "$WORK")" "$NAME" 2>&1 | head -3 | sed 's/^/    /'
fi

# ★ **第一步不是"查内容"，是"确认包真的生成了"** —— 这是第一版漏掉的
if [ ! -f "$OUT" ]; then
    fail "打包失败：$OUT 不存在"
    exit 1
fi
SZ_BYTES="$(wc -c < "$OUT" | tr -d ' ')"
if [ "$SZ_BYTES" -lt 100000 ]; then
    fail "包只有 ${SZ_BYTES} 字节，不像一个完整仓库"
    exit 1
fi
ok "$OUT  （$(awk "BEGIN{printf \"%.1f\", $SZ_BYTES/1048576}") MB）"

echo
echo "=== ③ 复查（先确认 tar 读得了，再判内容）==="
LIST="$WORK.list"
if ! tar -tzf "$(winpath "$OUT")" > "$LIST" 2>/dev/null; then
    fail "**tar 读不了这个包** —— 无法复查，**不能当通过**"
    exit 1
fi
LINES="$(grep -c . "$LIST")"
echo "  包内条目：$LINES"
[ "$LINES" -gt 50 ] || { fail "包内只有 $LINES 个条目，明显不对"; exit 1; }

echo "  --- 密钥 ---"
# ⚠️ **`.env.example` 是允许的**（`.gitignore` 里明确有 `!.env.example`）——
#    它是**变量名模板**，不含真值。第一版判据把它当密钥报了失败。
#    判据要排除它，但**不能顺手把 `.env` 也放过**：
#      · 排除 `.env.example`（含 `.env.local.example` 这种变体）
#      · 仍要抓 `.env` / `.env.local` / `.env.production` …
SECRETS="$(grep -E '(^|/)\.env($|\.)|\.(key|pem|p12|pfx)$' "$LIST" \
           | grep -vE '\.env[a-z.]*\.example$' || true)"
if [ -n "$SECRETS" ]; then
    echo "$SECRETS" | sed 's/^/         /'
    fail "包里有疑似密钥文件（见上）"
else
    ok "无疑似密钥文件（已排除 .env.example）"
fi

echo "  --- 环境与缓存 ---"
JUNK="$(grep -E '/(\.venv|node_modules|__pycache__|\.pytest_cache|dist|\.next)/' "$LIST" || true)"
if [ -n "$JUNK" ]; then
    echo "$JUNK" | head -6 | sed 's/^/         /'
    fail "包里混进了环境/缓存（见上）"
else
    ok "无 .venv / node_modules / __pycache__ / dist"
fi

echo "  --- 大文件（> 5MB）---"
EXTRACT="$WORK/x"
mkdir -p "$EXTRACT"
if ! tar -xzf "$(winpath "$OUT")" -C "$(winpath "$EXTRACT")" 2>/dev/null; then
    fail "解包失败 —— 无法查大文件"
else
    BIG="$(find "$EXTRACT" -type f -size +5M -printf '%s\t%p\n' 2>/dev/null | sort -rn | head -8 || true)"
    if [ -n "$BIG" ]; then
        echo "$BIG" | awk -F'\t' -v p="$EXTRACT/$NAME/" '{gsub(p,"",$2); printf "         %.1f MB  %s\n", $1/1048576, $2}'
        fail "有大文件（确认是否必要，见上）"
    else
        ok "无 > 5MB 的文件"
    fi
fi

echo
if [ "$FAIL" -ne 0 ]; then
    echo "❌ 复查未通过 —— **别直接交**。上面列出的项要处理掉。"
    exit 1
fi
echo "✅ 复查通过：无密钥、无大文件、无环境缓存"
echo
echo "包就绪：$OUT"
echo "（解压后顶层目录是 ${NAME}/，不会散在用户当前目录里）"
