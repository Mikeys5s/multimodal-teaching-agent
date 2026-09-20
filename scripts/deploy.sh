#!/usr/bin/env bash
# 部署到生产服务器（归属：P2）
#
# 用法：bash scripts/deploy.sh [--build-only]
#
# ## 这台服务器的已知情况（2026-09-19 实测）
#
# - 阿里云轻量 2核2G 深圳，公网 120.77.177.171:8000
# - `/root/xizhi` **不是 git 仓库** —— 代码是 scp 上去的快照，所以部署方式是
#   **本地打包 → 上传 → 解包 → 重新构建**，不是 `git pull`
# - 数据在 **docker volume `xizhi_xizhi-data`** 里，**与代码目录无关** ——
#   所以换代码目录不会丢数据（这是当初把数据放 volume 的直接收益）
# - **2G 内存且原本没有 swap** —— Vite 构建很容易 OOM，所以本脚本会先加 2G swap
#
# ## 三个刻意的动作
#
# ① **构建前加 swap** —— 2G 上跑 `npm ci && vite build` 是这台机器最容易挂的一步
# ② **旧代码改名而不是删除** —— 出问题能一条命令回滚（目录名带时间戳）
# ③ **数据用 volume** —— 部署脚本从不碰数据

set -u
cd "$(dirname "$0")/.." || exit 1
ROOT_DIR="$(pwd)"   # 打包时要 cd 进临时目录，所以先把仓库根记下来

# ⚠️ **原生 Windows 程序（tar.exe）要 Windows 路径**。
#    Git Bash 的 `/d/muti_tagent/...` 传给它只会得到 `tar: Failed to open`，
#    而且报错**不指向路径格式**，很容易以为是文件被占用。
#    `pwd -W` 给出 `D:/muti_tagent` 这种形式。
#    （这条在 docs/dev-playbook.md 里记过 —— 我还是先踩了才想起来去翻。）
ROOT_WIN="$(pwd -W 2>/dev/null || echo "$ROOT_DIR")"

#: 用本机 venv 的 python 跑自检脚本（它要算哈希、发 HTTP 请求）
PY="$ROOT_DIR/backend/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python"
if [ "${ROOT_WIN#/}" = "$ROOT_WIN" ]; then
    : # 已经是 Windows 形式
else
    # pwd -W 不可用时手工转：/d/foo -> D:/foo
    ROOT_WIN="$(echo "$ROOT_DIR" | sed -E 's|^/([a-zA-Z])/|\1:/|')"
fi

HOST="${XIZHI_HOST:-xizhi}"
REMOTE_DIR="/root/xizhi"
TARBALL=".learnbuddy/_gh/artifact/xizhi-main.tar.gz"
BUILD_ONLY=0
[ "${1:-}" = "--build-only" ] && BUILD_ONLY=1

SSHOPTS="-o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=10"

if [ "$BUILD_ONLY" -eq 0 ]; then
    # ---- ① 本地打包（从 git 出，干净无杂物）------------------------------
    #
    # ⚠️ `git archive` **只打已跟踪文件**。而 `frontend/package-lock.json`
    #    曾在 2026-09-19 之前一直没被提交过 —— 于是部署包里没有它，
    #    而 Dockerfile 里的 `npm ci` **必须有 lock 才能跑**，构建直接失败。
    #
    #    **所以这里显式地把它从工作区补进去**：即使它一时没提交上，
    #    部署也不会因此失败。（同时它当然应该被提交 —— 那是另一件事。）
    echo "==> ① 本地打包（**工作区**，不是 git）"
    mkdir -p "$(dirname "$TARBALL")"
    STAMP="$(date +%m%d-%H%M%S)"
    TARBALL="$(dirname "$TARBALL")/xizhi-main-${STAMP}.tar.gz"

    # ⚠️ **为什么从工作区打包，而不是 `git archive HEAD`**
    #
    #    2026-09-19 起本机的 git **写操作全部不可用**：
    #    环境的删除/改名拦截（`safe-delete` fail-closed + WinError 5）
    #    让 git 写 index 的「临时文件 + 改名」这步必然失败 ——
    #    `fatal: unable to write new index file`。
    #
    #    **提交不了，HEAD 就是冻结的**，而改动都在工作区里。
    #    既能部署，就必须以工作区为准 —— 否则服务器上永远是旧代码。
    #
    #    ⚠️ 这同时也意味着：**部署的内容不再等于任何一次提交**。
    #    等 git 恢复后要补一次「把工作区状态提交上去」。
    tar -czf "$ROOT_WIN/$TARBALL" -C "$ROOT_WIN" \
        --exclude='./.git' \
        --exclude='./.learnbuddy' \
        --exclude='./backend/.venv' \
        --exclude='./backend/uploads' \
        --exclude='./backend/.pytest_cache' \
        --exclude='./frontend/node_modules' \
        --exclude='./frontend/dist' \
        --exclude='*/node_modules' \
        --exclude='*/__pycache__' \
        --exclude='*.pyc' \
        --exclude='*.db' \
        --exclude='*.db-wal' \
        --exclude='*.db-shm' \
        . || exit 1

    SIZE=$(ls -lh "$ROOT_DIR/$TARBALL" 2>/dev/null | awk '{print $5}')
    HAS_LOCK=$(tar -tzf "$ROOT_WIN/$TARBALL" | grep -c 'package-lock.json' || true)
    HAS_FE=$(tar -tzf "$ROOT_WIN/$TARBALL" | grep -c 'frontend/src/' || true)
    echo "    包 $TARBALL（$SIZE）  前端源码 $HAS_FE 项  lock $HAS_LOCK 个"
    if [ "$HAS_LOCK" -eq 0 ]; then
        echo "    ⚠️ 包里没有 lock —— npm ci 会失败"
    fi

    # ---- ② 服务器加 swap ------------------------------------------------
    echo "==> ② 确保有 swap（2G 机跑 Vite 构建的保险）"
    # shellcheck disable=SC2086
    ssh $SSHOPTS "$HOST" 'bash -s' <<'REMOTE_SWAP'
if ! swapon --show 2>/dev/null | grep -q swapfile; then
    if fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none; then
        chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile && echo "    swap 已加 2G"
    else
        echo "    ⚠️ swap 添加失败，继续（构建可能 OOM）"
    fi
else
    echo "    swap 已存在"
fi
free -m | sed -n '2,3p' | sed 's/^/    /'
REMOTE_SWAP

    # ---- ③ 上传 + 解包（旧目录改名，不删）------------------------------
    echo "==> ③ 上传并解包"
    # shellcheck disable=SC2086
    scp -q $SSHOPTS "$TARBALL" "$HOST:/root/xizhi-main.tar.gz" || exit 1
    # shellcheck disable=SC2086
    ssh $SSHOPTS "$HOST" 'bash -s' <<REMOTE_UNPACK
set -e
cd /root
if [ -d "$REMOTE_DIR" ]; then
    BAK="$REMOTE_DIR.bak.\$(date +%m%d-%H%M%S)"
    mv "$REMOTE_DIR" "\$BAK"
    echo "    旧代码已备份为 \$BAK"
fi
mkdir -p "$REMOTE_DIR"
tar -xzf /root/xizhi-main.tar.gz -C "$REMOTE_DIR"
echo "    新代码 \$(find $REMOTE_DIR -type f | wc -l) 个文件"
echo "    前端 \$(ls $REMOTE_DIR/frontend 2>/dev/null | wc -l) 项"
REMOTE_UNPACK
fi

# ---- ④ 构建并启动 -------------------------------------------------------
echo "==> ④ 构建并启动（这一步最慢，前端要 npm ci + vite build）"
# shellcheck disable=SC2086
ssh $SSHOPTS "$HOST" "cd $REMOTE_DIR && docker compose up -d --build" 2>&1 | tail -25

# ---- ⑤ 验证 -------------------------------------------------------------
#
# ⚠️ **这一段原先不断言任何东西。**
#
# 原版只做三件事：打印容器状态、`curl /` 看状态码、`curl /api/health` 看内容。
# 三个都不判定 → 脚本**永远**打印「✅ 部署流程结束」。
#
# 后果（2026-09-20 真事）：
#   · 第一次：`nohup` 在这台机器上不存在，**部署根本没启动**，脚本照样说"结束"
#   · 第二次：跑了 15 分钟，但 **docker 镜像的构建时间还是上一次的** ——
#     没有任何东西产出新镜像，**脚本还是说"结束"**
#
# 所以"部署完成"当时是一句**口号**，不是事实。现在把它变成**被检查过的结论**：
#   跑自检 → 失败就让整个部署失败（非零退出）。
echo "==> ⑤ 部署后自检"
if ! "$PY" scripts/check-deploy.py; then
    echo
    echo "❌ **部署后自检未通过 —— 这次部署算失败。**"
    echo "   外网地址虽然还在响应，但跑的可能不是最新代码。"
    echo "   排查清单见上面自检输出的末尾三行。"
    exit 1
fi

echo
echo "✅ 部署流程结束，且**自检通过**（容器里跑的就是当前代码）。"
echo "   外网地址：http://120.77.177.171:8000"
