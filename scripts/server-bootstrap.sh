#!/usr/bin/env bash
# 服务器初始化（在**服务器上**跑，一次性）。
#
# ## 为什么要有这个脚本
#
# `docs/deployment.md` 里是给人看的步骤；这是给机器执行的版本。
# 区别在于：**顺序和幂等性被写死了**，不会因为漏了一步或顺序颠倒而失败。
#
# ## 目标环境
#
# 阿里云轻量 2核2G · **Ubuntu 24.04 LTS** · 华南1(深圳)
#
# ## 它做四件事
#
#   1. 校验系统确实是 Ubuntu（防止在 Alibaba Cloud Linux 上误跑，那边是 dnf）
#   2. 装 Docker + compose 插件
#   3. **配 Docker 镜像源** —— 国内直连 Docker Hub 是超时的，不配根本拉不下来
#   4. 体检：内核、内存、磁盘、端口、防火墙
#
# ## 用法
#
#   sudo bash scripts/server-bootstrap.sh
#
# 可重复执行（幂等）。

set -euo pipefail

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()  { printf '  [OK] %s\n' "$*"; }
warn() { printf '  [!!] %s\n' "$*"; }

# ---------------------------------------------------------------------------
# 1. 校验系统
# ---------------------------------------------------------------------------
say "1/4 校验系统"
if [ ! -f /etc/os-release ]; then
    warn "找不到 /etc/os-release，无法判断系统。中止。"
    exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
echo "  系统: ${PRETTY_NAME:-未知}"

if ! command -v apt-get >/dev/null 2>&1; then
    warn "这不是 Debian/Ubuntu 系（没有 apt-get）。"
    warn "本脚本为 Ubuntu 24.04 写的。若是 Alibaba Cloud Linux，请改用 dnf 手动安装。"
    exit 1
fi
ok "apt 可用"

# ---------------------------------------------------------------------------
# 2. 装 Docker
# ---------------------------------------------------------------------------
say "2/4 装 Docker"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "已安装：$(docker --version) / $(docker compose version --short 2>/dev/null || echo '?')"
else
    # ⚠️ 必须准备两条路：**国内网络下 get.docker.com 会被 Connection reset**
    #    实测 `curl: (35) Recv failure: Connection reset by peer`。
    #    这不是"失败就算了"—— 装不上 Docker，整条部署链路都走不下去。
    installed=0

    echo "  路径 A：官方脚本（国内可能被重置，最多等 60 秒）..."
    # --mirror Aliyun 让脚本改用阿里云 apt 源，比默认快得多
    if curl -fsSL --connect-timeout 20 --max-time 60 https://get.docker.com -o /tmp/get-docker.sh 2>/dev/null; then
        if sh /tmp/get-docker.sh --mirror Aliyun >/tmp/docker-install.log 2>&1; then
            ok "官方脚本装上了：$(docker --version)"
            installed=1
        else
            warn "官方脚本执行失败，末尾日志："
            tail -5 /tmp/docker-install.log | sed 's/^/      /'
        fi
    else
        warn "下载 get.docker.com 失败（国内常见）。转路径 B。"
    fi

    if [ "$installed" -eq 0 ]; then
        echo "  路径 B：直接用 Ubuntu 仓库装（走本地 apt 镜像，通常更快更稳）..."
        apt-get update -qq || true
        # docker-compose-v2 是 Ubuntu 24.04 里的 compose 插件包名
        if apt-get install -y -qq docker.io docker-compose-v2 >/tmp/apt-docker.log 2>&1; then
            ok "apt 装上了：$(docker --version)"
            installed=1
        else
            warn "apt 装 Docker 也失败了，末尾日志："
            tail -8 /tmp/apt-docker.log | sed 's/^/      /'
        fi
    fi

    if [ "$installed" -eq 0 ]; then
        warn "两条路都没装成 Docker。请手工处理后再跑一次本脚本。"
        exit 1
    fi
fi

systemctl enable --now docker >/dev/null 2>&1 || true
systemctl is-active --quiet docker && ok "docker 服务在跑" || warn "docker 服务没起来"

# compose 是 `docker compose up` 的前提，单独确认一遍 —— 它单独缺了也部署不了
if docker compose version >/dev/null 2>&1; then
    ok "compose 可用：$(docker compose version --short 2>/dev/null)"
else
    warn "⚠️ docker compose 不可用！部署会失败。"
    warn "   Ubuntu 上可试：apt-get install -y docker-compose-v2"
fi

# ---------------------------------------------------------------------------
# 3. 配镜像源（★ 关键，不配拉不动）
# ---------------------------------------------------------------------------
say "3/4 配 Docker 镜像源"
# 实测（2026-09-18，本地 Windows + Docker Desktop）：registry-1.docker.io 直连 12 秒超时；
# 配好镜像源后速度从 40 KB/s 提到 13~30 MB/s。**服务器同样在国内，同样的问题。**
# 这两个源是当时实测可用的：daocloud 返回 401（可达）、1panel 返回 200。
# 注意 hub.rat.dev 返回 302 重定向 —— 排在首位会拖慢甚至卡住构建，所以不用它。
if [ -f /etc/docker/daemon.json ]; then
    cp /etc/docker/daemon.json "/etc/docker/daemon.json.bak.$(date +%s)"
    ok "已备份原有 daemon.json"
fi

mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1panel.live"
  ],
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
ok "已写入 /etc/docker/daemon.json"

systemctl restart docker
sleep 3 2>/dev/null || true
echo "  生效的镜像源: $(docker info --format '{{.RegistryConfig.Mirrors}}' 2>/dev/null || echo '读不到')"

echo "  验一下源是否真的可用（200/401 都算可用）..."
for m in https://docker.m.daocloud.io https://docker.1panel.live; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$m/v2/" || echo 000)
    case "$code" in
        200|401) ok "$m -> $code" ;;
        000)     warn "$m -> 连不上（可能被封，换一个源）" ;;
        *)       warn "$m -> $code" ;;
    esac
done

# ---------------------------------------------------------------------------
# 4. 体检
# ---------------------------------------------------------------------------
say "4/4 体检"
echo "  CPU      : $(nproc) 核"
echo "  内存     : $(free -m | awk '/Mem:/{print $2" MB 总 / "$7" MB 可用"}')"
echo "  磁盘     : $(df -h / | awk 'NR==2{print $2" 总 / "$4" 可用"}')"
echo "  Docker   : $(docker --version)"

echo
echo "  --- 监听端口 ---"
(ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null) | grep -v "^State" | head -10 || true

echo
if command -v ufw >/dev/null 2>&1; then
    echo "  ufw 状态 : $(ufw status 2>/dev/null | head -1)"
else
    echo "  ufw      : 未安装"
fi

cat <<'NEXT'

  ┌─ 还需要手工做一件事（脚本做不了）───────────────────────────────
  │
  │  ⚠️ 阿里云控制台的「防火墙」里放行 **8000** 端口。
  │
  │  云主机有**两层**防火墙：
  │    ① 控制台的安全组/防火墙   ← 脚本碰不到，必须手工
  │    ② 系统内的 ufw/iptables   ← 上面已体检
  │  只放开一层，症状是"本机能通、外网不通" —— 这是最常见的坑。
  └──────────────────────────────────────────────────────────────
NEXT

say "完成"
echo "  下一步（在仓库目录）："
echo "      docker compose up -d --build"
