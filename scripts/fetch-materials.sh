#!/usr/bin/env bash
# =============================================================================
# fetch-materials.sh —— 一条命令把「真实教材」素材准备好（A1-2 / A1-5 / A1-6 /
#                       A2-7 / F1.2 的复现前提）
#
# 为什么需要这个脚本
# ------------------
# 解析链路上最有分量的那批证据（真实教材的块数、逐字忠实性、字符覆盖率、
# 可复现性、扫描版判定）都跑在**真实教材**上。而那两个素材文件放在
# `.learnbuddy/materials/`（已被 `.gitignore` 忽略，**不进版本库**），
# 于是任何人 clone 下来跑测试，那 14 个用例都只是 skip —— 队友与评委
# 复现不了任何一条结论。本脚本就是为了消掉这个"复现门槛"：
#
#     bash scripts/fetch-materials.sh                    # 只下教材
#     bash scripts/fetch-materials.sh --make-scan-sample # 再顺手做一个扫描件样本
#
# 落到哪里
# --------
#   <repo>/.learnbuddy/materials/
#     ├── ComputerNetworks-SystemsApproach-6e.pdf              （教材全文，489 页）
#     └── ComputerNetworks-SystemsApproach-6e-扫描件样本.pdf   （只有图片、无文本层）
#   可用环境变量 `QA_MATERIALS_DIR` 覆盖目录（与测试读取的是同一个变量）。
#
# 素材与许可归属（CC BY 4.0）
# --------------------------
#   书名：Computer Networks: A Systems Approach, 6th edition (Release v6.1)
#   作者：Larry Peterson, Bruce Davie
#   项目：https://github.com/SystemsApproach/book
#   许可：Creative Commons Attribution 4.0 International (CC BY 4.0)
#         https://creativecommons.org/licenses/by/4.0/
#   直链：https://github.com/SystemsApproach/book/releases/download/v6.1/book.pdf
#   本脚本**只做下载**：不改动、不再分发教材内容；下载物落在版本库之外，
#   版权与署名仍归原作者，使用时请遵守 CC BY 4.0（保留署名）。
#
# 注意：**扫描件样本是本脚本用 pymupdf 从教材渲染出来的派生文件**，
#       不是原始素材，同样只落在版本库之外，仅供本地跑"扫描版判定"用例。
# =============================================================================

set -euo pipefail

# ---- 常量 -------------------------------------------------------------------
TEXTBOOK_NAME="ComputerNetworks-SystemsApproach-6e.pdf"
SCAN_SAMPLE_NAME="ComputerNetworks-SystemsApproach-6e-扫描件样本.pdf"
TEXTBOOK_URL="https://github.com/SystemsApproach/book/releases/download/v6.1/book.pdf"
#: 实测的字节数（2026-09 实测，Release v6.1 的 book.pdf）。
#: 用途：① 判断"已下载好、可跳过"；② 下载完校验完整性。
#: 上游换 Release 时这个数会变，届时同步更新即可。
TEXTBOOK_BYTES=22254526
#: 实测页数，用于下载后的可用性自检。
TEXTBOOK_PAGES=489
#: 扫描件样本的页数 —— 与 `tests/test_qa_parse_real_material.py` 的断言一致（== 3）。
SCAN_SAMPLE_PAGES=3
#: 从教材的第几页（1-based）开始取渲染源页。取正文中段，避开封面/目录/空白页。
SCAN_SAMPLE_FIRST_PAGE=21
#: 渲染 DPI。150 够"像扫描件"，又不至于把样本做得太大。
SCAN_SAMPLE_DPI=150

# ---- 路径 -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MATERIALS_DIR="${QA_MATERIALS_DIR:-$REPO_ROOT/.learnbuddy/materials}"
TEXTBOOK_PATH="$MATERIALS_DIR/$TEXTBOOK_NAME"
SCAN_SAMPLE_PATH="$MATERIALS_DIR/$SCAN_SAMPLE_NAME"

MAKE_SCAN_SAMPLE=0

# ---- 小工具 -----------------------------------------------------------------
say() { printf '%s\n' "$*"; }
ok() { printf '  [OK] %s\n' "$*"; }
skip() { printf '  [跳过] %s\n' "$*"; }
warn() { printf '  [注意] %s\n' "$*" >&2; }
die() {
  printf '\n[错误] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<EOF
用法：bash scripts/fetch-materials.sh [选项]

  （无选项）            只下载教材全文到 $MATERIALS_DIR
  --make-scan-sample    额外生成「扫描件样本」（只有图片、没有文本层的 3 页 PDF）
  -h, --help            显示本帮助

环境变量：
  QA_MATERIALS_DIR      覆盖素材目录（测试读的是同一个变量）

幂等：文件已存在且大小正确就跳过；可用 --make-scan-sample 反复执行。
EOF
}

file_bytes() {
  # 输出文件的字节数（跨 GNU / BSD / Git Bash 都可用）。
  wc -c <"$1" | tr -d '[:space:]'
}

find_python_with_pymupdf() {
  # 依次试：仓库 venv（首选）→ python3 → python。第一个能 import pymupdf 的胜出。
  local cand
  for cand in \
    "$REPO_ROOT/backend/.venv/Scripts/python.exe" \
    "$REPO_ROOT/backend/.venv/bin/python" \
    "$(command -v python3 2>/dev/null || true)" \
    "$(command -v python 2>/dev/null || true)"; do
    [ -n "$cand" ] && [ -x "$cand" ] || continue
    if "$cand" -c "import pymupdf" >/dev/null 2>&1; then
      printf '%s' "$cand"
      return 0
    fi
  done
  return 1
}

download() {
  # download <url> <dest>；失败返回非 0（调用方负责收尾）。
  local url="$1" dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --retry-delay 3 --connect-timeout 30 -o "$dest" "$url"
    return $?
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -O "$dest" "$url"
    return $?
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$url" "$dest" <<'PYEOF'
import sys, urllib.request
url, dest = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as out:
    while True:
        chunk = resp.read(1 << 20)
        if not chunk:
            break
        out.write(chunk)
PYEOF
    return $?
  fi
  die "找不到 curl / wget / python3 中的任何一个，无法下载。请先装其中一个再运行。"
}

# ---- 解析参数 ---------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
  --make-scan-sample) MAKE_SCAN_SAMPLE=1 ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    warn "未知参数：$1"
    usage
    exit 2
    ;;
  esac
  shift
done

say "=============================================="
say " 析知 XiZhi · 真实教材素材准备"
say "=============================================="
say "素材目录：$MATERIALS_DIR"
say ""

mkdir -p "$MATERIALS_DIR"

# =============================================================================
# 1. 教材全文
# =============================================================================
say "[1/2] 教材全文：$TEXTBOOK_NAME"

if [ -f "$TEXTBOOK_PATH" ]; then
  actual="$(file_bytes "$TEXTBOOK_PATH")"
  if [ "$actual" = "$TEXTBOOK_BYTES" ]; then
    skip "已存在且大小正确（$actual 字节），无需重新下载。"
  else
    warn "已存在但大小不符（实际 $actual，期望 $TEXTBOOK_BYTES）—— 视为不完整的旧文件，重新下载。"
  fi
fi

if [ ! -f "$TEXTBOOK_PATH" ] || [ "$(file_bytes "$TEXTBOOK_PATH")" != "$TEXTBOOK_BYTES" ]; then
  part="$TEXTBOOK_PATH.part"
  part_name="$(basename "$part")"
  # 最终文件名**永远不会出现半成品**：先下到 .part，校验通过再改名。
  say "  正在下载（约 22 MB，慢的话耐心等一下）："
  say "  $TEXTBOOK_URL"
  # ⚠️ 必须 `cd` 进素材目录、只传**相对文件名**：本机 shell 与下载器都是
  # Windows 程序（Git Bash 的 curl 是 system32\curl.exe），给它 `/d/foo` 这种
  # POSIX 路径会报 "Failed to open the file ... No such file or directory"。
  if ! (cd "$MATERIALS_DIR" && download "$TEXTBOOK_URL" "$part_name"); then
    die "下载失败。已下载的部分保留在 $part（不会被当成可用素材），下次运行会覆盖它。"
  fi

  part_bytes="$(file_bytes "$part")"
  if [ "$part_bytes" != "$TEXTBOOK_BYTES" ]; then
    # 不删文件（本机删除受限），保留 .part 供排查；最终文件名仍是空的。
    die "下载内容大小不符：实际 $part_bytes 字节，期望 $TEXTBOOK_BYTES。半成品保留在 $part，正式文件名未被占用，可重跑本脚本。"
  fi

  mv "$part" "$TEXTBOOK_PATH"
  ok "下载完成并已校验：$TEXTBOOK_BYTES 字节。"
fi

# ---- 可用性自检（有 pymupdf 才做，缺了不算失败）----
if PY="$(find_python_with_pymupdf)"; then
  # 内联脚本一律 exit 0 并把结论打在 stdout 上：这样"页数不对"与
  # "pymupdf 自己报错"是两种可区分的输出，不会把后者误报成"上游换了 Release"。
  #
  # 为什么要 `cd` 进素材目录再只传文件名：Git Bash 的 `/d/foo/bar` 形式
  # Windows 版 python 不认（FileNotFoundError），而本机没有 cygpath 可转换；
  # 传相对文件名对 Windows / POSIX 两种 python 都成立。
  check_out="$(
    cd "$MATERIALS_DIR"
    "$PY" - "$TEXTBOOK_NAME" "$TEXTBOOK_PAGES" <<'PYEOF'
import sys
import pymupdf

name, expected = sys.argv[1], int(sys.argv[2])
try:
    doc = pymupdf.open(name)
except Exception as exc:  # noqa: BLE001 - 只是要把原因原样报给用户
    print(f"OPEN_FAILED {type(exc).__name__}: {exc}")
    raise SystemExit(0)
try:
    n = doc.page_count
finally:
    doc.close()
print("OK" if n == expected else f"MISMATCH {n}")
PYEOF
  )" || true
  case "$check_out" in
  OK)
    ok "可用性自检通过：$TEXTBOOK_PAGES 页，pymupdf 能正常打开。"
    ;;
  MISMATCH*)
    die "教材页数不符（实际 ${check_out#MISMATCH }，期望 $TEXTBOOK_PAGES）—— 上游可能换了 Release，请复核脚本顶部的 TEXTBOOK_BYTES / TEXTBOOK_PAGES。"
    ;;
  *)
    warn "页数自检没跑成，pymupdf 的报错：$check_out"
    warn "文件大小是对的，素材大概率仍可用；如需确认请手动打开这个 PDF 看一眼。"
    ;;
  esac
else
  warn "没找到带 pymupdf 的 Python，跳过页数自检（不影响素材可用）。"
fi

# =============================================================================
# 2. 扫描件样本（可选）
# =============================================================================
if [ "$MAKE_SCAN_SAMPLE" -eq 1 ]; then
  say ""
  say "[2/2] 扫描件样本：$SCAN_SAMPLE_NAME"

  if [ ! -f "$TEXTBOOK_PATH" ]; then
    die "教材还没准备好，先生成扫描件样本会失败。请先不带 --make-scan-sample 跑一次。"
  fi

  if [ -f "$SCAN_SAMPLE_PATH" ] && [ "$(file_bytes "$SCAN_SAMPLE_PATH")" -gt 0 ]; then
    skip "已存在（$(file_bytes "$SCAN_SAMPLE_PATH") 字节），无需重新生成。"
    say "        说明：渲染产物字节数随 pymupdf 版本/DPI 变化，无法按固定字节数校验；"
    say "        重新生成请先移走旧文件。"
  else
    if ! PY="$(find_python_with_pymupdf)"; then
      die "生成扫描件样本需要 pymupdf。请先装：backend/.venv/Scripts/python.exe -m pip install -e \".[parse]\""
    fi

    part="$SCAN_SAMPLE_PATH.part"
    part_name="$(basename "$part")"
    say "  用 pymupdf 把教材第 $SCAN_SAMPLE_FIRST_PAGE–$((SCAN_SAMPLE_FIRST_PAGE + SCAN_SAMPLE_PAGES - 1)) 页渲染成 $SCAN_SAMPLE_DPI DPI 图片，"
    say "  再拼成 $SCAN_SAMPLE_PAGES 页「只有图片、没有文本层」的 PDF。"

    # 与上面的页数自检同理：cd 进素材目录、只传相对文件名。
    (
      cd "$MATERIALS_DIR"
      "$PY" - "$TEXTBOOK_NAME" "$part_name" "$SCAN_SAMPLE_FIRST_PAGE" "$SCAN_SAMPLE_PAGES" "$SCAN_SAMPLE_DPI" <<'PYEOF'
import sys
import pymupdf

src_name, dest_name, first, pages, dpi = (
    sys.argv[1],
    sys.argv[2],
    int(sys.argv[3]),
    int(sys.argv[4]),
    int(sys.argv[5]),
)

source = pymupdf.open(src_name)
out = pymupdf.open()
try:
    start = first - 1  # 1-based → 0-based
    if start + pages > source.page_count:
        raise SystemExit(f"源教材只有 {source.page_count} 页，取不到第 {first} 页起的 {pages} 页")
    for offset in range(pages):
        src_page = source[start + offset]
        pix = src_page.get_pixmap(dpi=dpi)
        new_page = out.new_page(width=src_page.rect.width, height=src_page.rect.height)
        new_page.insert_image(new_page.rect, stream=pix.tobytes("png"))
    out.save(dest_name, garbage=4, deflate=True)
finally:
    out.close()
    source.close()

# 自检：必须是"无文本层 + 有整页图"，否则这条样本会骗过扫描版判定用例。
check = pymupdf.open(dest_name)
try:
    assert check.page_count == pages, f"样本页数 {check.page_count} != {pages}"
    for i in range(check.page_count):
        text = "".join(check[i].get_text("text").split())
        if text:
            raise SystemExit(f"样本第 {i + 1} 页仍有文本层（{len(text)} 字符），不是纯图像页")
        if not check[i].get_images():
            raise SystemExit(f"样本第 {i + 1} 页没有图像，扫描版判定会漏")
finally:
    check.close()
PYEOF
    )

    if [ ! -f "$part" ]; then
      die "渲染没有产出文件，请检查上面的报错。"
    fi
    mv "$part" "$SCAN_SAMPLE_PATH"
    ok "已生成并自检：$SCAN_SAMPLE_PAGES 页、无文本层、含整页图。"
  fi
fi

# =============================================================================
# 3. 接下来什么会变
# =============================================================================
say ""
say "=============================================="
say " 素材就绪 —— 接下来这些用例会从「跳过」变成「真正执行」"
say "=============================================="
if [ -f "$TEXTBOOK_PATH" ] && [ -f "$SCAN_SAMPLE_PATH" ]; then
  say "backend/tests/test_qa_parse_real_material.py 的 **全部 14 个用例**都会真跑，例如："
  say "  · A1-2 文本层抽取质量：字符覆盖率 [98%, 105%] + 逐字忠实性（块必须是原页连续子串）"
  say "  · A1-5 性能：30 页真实排版 < 90 秒"
  say "  · A1-6 锚点：块锚点数量/唯一/有序，页锚点集合 == 有块的页集合"
  say "  · A2-7 可复现：同材料解析两次，块序列与 Markdown 逐字节相同"
  say "  · F1.2 扫描版判定：样本判 pdf_scan + 中文存疑说明"
  say "  · 超页数保护：489 页原文必须报中文错并提示分批，不得静默截断"
else
  say "还差素材，目前只会执行一部分："
  [ -f "$TEXTBOOK_PATH" ] || say "  · 缺教材全文 → 相关用例仍会 skip"
  [ -f "$SCAN_SAMPLE_PATH" ] || say "  · 缺扫描件样本（加 --make-scan-sample）→ 扫描版判定用例仍会 skip"
fi
say ""
say "跑起来："
say "  cd backend"
say "  .venv/Scripts/python.exe -m pytest tests/test_qa_parse_real_material.py -q -s"
say "     （加 -s 才能看到覆盖率、性能、版式观察等实测数字；这批用例较慢）"
say ""
say "许可提醒：教材 *Computer Networks: A Systems Approach* 6th ed. 采用"
say "CC BY 4.0，作者 Larry Peterson & Bruce Davie，出处"
say "https://github.com/SystemsApproach/book —— 使用时请保留署名。"
