#!/usr/bin/env bash
# gate-selftest.sh —— **证明每一道闸都会失败**（归属：P2）
#
# ## 为什么需要它
#
# 2026-09-19 我在"检查工具"上错了 7 次：漏检却报成功、结论写死、
# 启发式误报、`${}` 漏归一化、前瞻越界、停止条件过激……
# **全是同一件事：检查本身不可靠，却输出「通过」。**
#
# 而 `gate.sh` 的四道闸，在很长一段时间里**从没被证明过会失败**。
# 一道永远不会 FAIL 的闸，和没有闸是一样的 —— 它只会给人虚假的安全感。
#
# ## 它做什么
#
# 在一份**克隆出来的副本**里注入已知故障，跑对应的闸，**期望它 FAIL**：
#
#   | 闸 | 注入什么故障 | 期望 |
#   |---|---|---|
#   | ① 工作区完整性 | 删掉一个已跟踪文件 | FAIL |
#   | ② ruff | 写一个必然的 lint 错误 | FAIL |
#   | ③ 假数据审计 | 往一个端点里塞 mock 返回 | 数出 ≥1 个假数据 |
#   | ④ 验收指标 | 塞一条成环的依赖边 | FAIL |
#
# **副本里操作，真仓库一个字节都不动。** 用真的 `git clone`（闸① 依赖 `.git`）。
#
# ## 用法
#
#     bash scripts/gate-selftest.sh
#
# 退出码 0 = 四道闸都被证明会失败；非 0 = 有闸是"哑的"。

set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOT_WIN="$(cd "$ROOT" && pwd -W 2>/dev/null || echo "$ROOT")"
PY="$ROOT/backend/.venv/Scripts/python.exe"
COPY="$ROOT/.learnbuddy/_gatecheck"

OK=0
BAD=0
declare -a LINES

say()  { printf '%s\n' "$*"; }
head1() { printf '\n== %s\n' "$*"; }

# 判定：期望 FAIL，实际 FAIL 才算"闸是活的"
judge() {
    local name="$1" expect="$2" actual="$3" note="${4:-}"
    if [ "$expect" = "$actual" ]; then
        OK=$((OK + 1))
        LINES+=("  ✅ $name")
    else
        BAD=$((BAD + 1))
        LINES+=("  ❌ $name  —— 期望 $expect，实际 $actual ${note:+（$note）}")
    fi
    [ -n "$note" ] && LINES+=("       $note")
}

# 造一份干净的克隆副本（带 .git，闸① 需要）
#
# ⚠️ 三个坑，都是今天踩过的：
#   ① **`git` 是原生 Windows 程序，要 Windows 路径** —— 给 POSIX 路径它会说
#      "repository does not exist"，而报错**不指向路径格式**。
#      （同一条坑我刚在 `scripts/deploy.sh` 的注释里写过，然后在这里又踩了一次。）
#   ② **本机删除在 D 盘不可用** → `rm -rf` 清不掉旧副本 →
#      第二次克隆会撞上已存在的目录。所以**每次克隆到新目录**。
#   ③ 副本里**不装依赖** —— 用真 venv 的 python 跑副本里的脚本
#      （脚本用 `__file__` 定位自己的 `backend/`，所以导入的是副本的源码）。
STAMP="$(date +%H%M%S)"
COPY_N=0
mkcopy() {
    COPY_N=$((COPY_N + 1))
    # ⚠️ 名字里必须带**每一次运行唯一的**时间戳。
    #
    #    本机在 D 盘**删不掉目录**（safe-delete fail-closed）——
    #    所以"先清空再克隆"这条路走不通：`rm -rf` 会静默失败，
    #    第二次运行就撞上"destination ... already exists and is not an empty directory"。
    #
    #    **同一个坑今天第三次踩了**（部署包名、临时文件、这次的副本）。
    #    规律很清楚：**在这个环境里，凡是"可重复执行"的东西，名字必须唯一。**
    COPY="$ROOT/.learnbuddy/_gatecheck_${STAMP}_$COPY_N"
    COPY_WIN="$(cd "$ROOT/.learnbuddy" && pwd -W 2>/dev/null)/_gatecheck_${STAMP}_$COPY_N"
    # ⚠️ 不要把错误吞掉 —— 第一版写了 `2>/dev/null`，于是失败时只说
    #    "克隆失败"，看不到**为什么**。诊断工具自己不该是黑盒。
    if ! git clone --quiet --no-hardlinks "$ROOT_WIN" "$COPY_WIN" 2>"$ROOT/.learnbuddy/_clone_err.txt"; then
        say "❌ 克隆失败（目标 $COPY_WIN），无法继续"
        say "   \$ROOT_WIN = $ROOT_WIN"
        say "   git 说：$(tail -3 "$ROOT/.learnbuddy/_clone_err.txt" 2>/dev/null | tr '\n' ' ')"
        exit 2
    fi
}

# 用真 venv 跑副本里的某个 python 脚本
#
# ⚠️ **必须传 Windows 路径**：`$PY` 是原生 Windows 的 python.exe，
#    给它 POSIX 路径 `/d/muti_tagent/...` 会被当成 `D:\d\muti_tagent\...`
#    → `can't open file`。
#    （这条我在 `scripts/deploy.sh` 的注释里写过，然后在这里踩了两次。）
pyc() {
    local rel="${1#"$COPY"/}"
    shift
    "$PY" "$COPY_WIN/$rel" "$@" 2>&1
}

say "===================================================================="
say "四道闸自检 —— 证明每一道闸都会失败"
say "===================================================================="

# ---------------------------------------------------------------------------
# 闸 ① 工作区完整性预检
# ---------------------------------------------------------------------------
head1 "闸① 工作区完整性预检"
mkcopy
# ⚠️ 注入"删除"要用 **mv 挪走**，不能用 `rm` ——
#    本机在 D 盘上删除被拦（safe-delete fail-closed），`rm` 会静默失败，
#    于是"注入"根本没发生，那道闸自然也不会 FAIL（第一版就栽在这）。
#    `mv` 是可用的，而 git 一样会把文件看成 ` D`。
mv "$COPY/README.md" "$COPY/README.moved-by-selftest" 2>/dev/null || true
D=$( (cd "$COPY" && git status --porcelain) | grep -c '^ D' || true)
judge "① 挪走一个已跟踪文件后，预检应当 FAIL" FAIL \
      "$([ "${D:-0}" -gt 0 ] && echo FAIL || echo PASS)" \
      "副本里检出 $D 个缺失文件"

# ---------------------------------------------------------------------------
# 闸 ② ruff
# ---------------------------------------------------------------------------
head1 "闸② 静态检查（ruff）"
mkcopy
cat > "$COPY/backend/app/_lint_probe.py" <<'PYEOF'
"""自检注入用：这个文件**故意**有 lint 错误。"""

import os


def probe():
    unused = 1
    return 2
PYEOF
if "$PY" -m ruff check --no-cache "$COPY/backend/app/_lint_probe.py" >/dev/null 2>&1; then
    judge "② 写一个必然的 lint 错误，ruff 应当 FAIL" FAIL PASS "ruff 竟然没报 —— 它没在工作"
else
    judge "② 写一个必然的 lint 错误，ruff 应当 FAIL" FAIL FAIL
fi

# ---------------------------------------------------------------------------
# 闸 ③ 假数据审计
# ---------------------------------------------------------------------------
head1 "闸③ 假数据审计"
mkcopy
# 判据是「在空库上打每个端点，看响应体量」。
# 注入方式：把副本里 `/api/jobs` 的列表实现换成**写死的返回**。
if [ -f "$COPY/backend/app/api/jobs.py" ]; then
    "$PY" - "$COPY_WIN/backend/app/api/jobs.py" <<'PYEOF'
import pathlib
import re
import sys

p = pathlib.Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
# 在 list_jobs 里直接 return 写死的数据（放在函数体第一行之后）
s = s.replace(
    "    # 不分页（见端点说明），但**按创建时间倒序** —— 最近的任务在最前面，",
    "    # ---- selftest 注入：写死返回**一条真实记录**，空库上也有数据 ----\n"
    "    # ⚠️ 必须返回**非空列表**：审计器数的是列表长度，\n"
    "    #    第一版只给了 total=3 而 items=[]，被判成「真实」。\n"
    "    from app.core.response import ok as _ok\n"
    "    from app.schemas.job import JobListOut as _J, JobOut as _JO\n"
    "    _fake = _JO(id='job_selftest', job_type='parse', target_id='mat_x',\n"
    "                status='running', progress=1, stage_detail='注入',\n"
    "                result_json=None, error_message=None, started_at=None,\n"
    "                finished_at=None, created_at='2026-01-01T00:00:00+00:00')\n"
    "    return _ok(_J(items=[_fake], total=1))\n"
    "    # ---- selftest 注入结束 ----\n"
    "    # 不分页（见端点说明），但**按创建时间倒序** —— 最近的任务在最前面，",
    1,
)
p.write_text(s, encoding="utf-8")
print("  已注入")
PYEOF
fi
OUT=$("$PY" "$COPY_WIN/scripts/audit-mock-endpoints.py" 2>&1 | tail -12 || true)
N=$(printf '%s' "$OUT" | grep -oE '假数据 [0-9]+ 个' | grep -oE '[0-9]+' | head -1 || true)
judge "③ 把 /api/jobs 换成写死返回，审计应当数出来" FAIL \
      "$([ "${N:-0}" -gt 0 ] && echo FAIL || echo PASS)" \
      "审计尾部：$(printf '%s' "$OUT" | tail -3 | tr '\n' ' ')"

# ---------------------------------------------------------------------------
# 闸 ④ 验收指标（依赖图必须无环）
# ---------------------------------------------------------------------------
head1 "闸④ 验收指标（图不变量）"
mkcopy
FIX="$COPY/samples/graph-infer-tests"
CYCLIC=$(ls "$FIX" 2>/dev/null | grep -i "cycle" | head -1 || true)
if [ -n "$CYCLIC" ]; then
    OUT=$(pyc "$COPY/skills/xizhi-graph-infer/scripts/graph_infer.py" verify --input "$(cd "$FIX" && pwd -W)/$CYCLIC" || true)
    # 取环数。
    # ⚠️ 正则必须能吃下 `cycle_count` —— 第一版写 `cycles?["\s:=]+[0-9]+`，
    #    **`_` 不在那个字符类里**，于是匹配不上 `"cycle_count": 1`，
    #    结果"取不到值"被当成"闸没报"。
    #    **是取值写错了，不是闸哑了 —— 差一点又把自己的错记到闸头上。**
    N=$(printf '%s' "$OUT" | grep -oE '"cycle_count"[[:space:]]*:[[:space:]]*[0-9]+' | grep -oE '[0-9]+' | head -1 || true)
    judge "④ 用带环的夹具跑图校验，应当报出环" FAIL \
          "$([ "${N:-0}" -gt 0 ] && echo FAIL || echo PASS)" \
          "夹具 $CYCLIC -> cycles=${N:-?}｜原始输出：$(printf '%s' "$OUT" | head -2 | tr '\n' ' ')"
else
    judge "④ 用带环的夹具跑图校验，应当报出环" FAIL PASS "夹具目录里没找到带 cycle 的 json"
fi

# ---------------------------------------------------------------------------
say ""
say "===================================================================="
say "结果"
say "===================================================================="
for l in "${LINES[@]}"; do say "$l"; done
say ""
if [ "$BAD" -eq 0 ]; then
    say "✅ 四道闸**都被证明会失败** —— 它们的「通过」才有意义"
else
    say "❌ 有 $BAD 道闸是**哑的**：注入故障它也不报"
    say "   一道永远不会 FAIL 的闸，和没有闸一样 —— 它只给人虚假的安全感"
fi
say "===================================================================="
rm -rf "$COPY" 2>/dev/null || true
exit $([ "$BAD" -eq 0 ] && echo 0 || echo 1)
