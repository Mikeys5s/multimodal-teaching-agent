# 部署手册（M3）

> 目标：**一条命令起服务，一个 URL 交付**（SPEC §4.7 / §5.6）。
> 相关：[`../Dockerfile`](../Dockerfile) · [`../docker-compose.yml`](../docker-compose.yml) · [`dev-environment.md`](dev-environment.md)

---

## 1. 交付形态

**单容器、同源、一个端口。**

```
http://<公网IP>:8000/           → 前端界面（SPA）
http://<公网IP>:8000/api/**     → 接口
http://<公网IP>:8000/docs       → OpenAPI 文档（演示与调试用）
```

**没有 nginx、没有 CORS、没有域名。**

| 决策 | 为什么 |
|---|---|
| **不用域名** | 国内节点绑域名要 **ICP 备案，3~20 天**，时间上来不及。赛事只要求"浏览器可直接访问的在线链接"，IP 即可 |
| **用 8000 不用 80** | 未备案时 **80/443 被封**。这是国内云主机的硬规则，不是选择 |
| **不做 CORS** | 前后端同源，浏览器根本不会发预检请求。`DEBUG=false` 时 CORS 中间件不挂载（见 `app/main.py`） |
| **不需要 nginx** | FastAPI 直接托管静态产物。少一个组件就少一处故障点，2G 内存也省一点 |

---

## 2. 首次部署

### 2.1 服务器准备（一次性）

| 项 | 值 |
|---|---|
| 实例 | 阿里云轻量应用服务器 **2核2G**，华南1（深圳），40G ESSD |
| 镜像 | **Ubuntu 24.04 LTS**（不要选宝塔/1Panel 之类面板镜像） |
| 防火墙 | 放行 **22（SSH）** 与 **8000（HTTP）** |
| 数据盘 | 不需要额外数据盘 |

### 2.2 装 Docker

```bash
# 官方脚本，装完 docker + compose plugin
curl -fsSL https://get.docker.com | sh

# 验证
docker --version && docker compose version
```

> 国内机器拉 Docker Hub 可能很慢或超时。如果 `docker pull` 卡住，配一个镜像加速：
> ```bash
> sudo mkdir -p /etc/docker
> sudo tee /etc/docker/daemon.json <<'EOF'
> { "registry-mirrors": ["https://docker.m.daocloud.io", "https://dockerproxy.com"] }
> EOF
> sudo systemctl restart docker
> ```

### 2.3 拉代码、起服务

```bash
cd ~
git clone https://github.com/RyeYen/multimodal-teaching-agent.git xizhi
cd xizhi

docker compose up -d --build
```

首次构建要拉 `node:22-alpine` 和 `python:3.13-slim`，**慢的话 5~15 分钟**（2 核机器）。

### 2.4 验证

```bash
docker compose ps          # 期望 STATUS 里出现 (healthy)
docker compose logs --tail=50
curl -s http://127.0.0.1:8000/api/health | head -c 300
```

然后**从外网**访问一次：

```
http://<公网IP>:8000/api/health
http://<公网IP>:8000/
```

> **外网那一步必须真的从别的网络试一次。** 云主机的防火墙有两层
> （控制台的安全组/防火墙 + 系统内的 ufw），只放开一层是最常见的"本机能通、外面不通"。

---

## 3. 更新部署

```bash
cd ~/xizhi
git pull --ff-only
docker compose up -d --build
```

**迁移由容器入口自动跑**（见 `backend/docker-entrypoint.sh`），不需要手动执行。
数据在具名卷里，`up --build` 不会动它。

---

## 4. 前端还没进仓库时会怎样

`Dockerfile` 的前端阶段是**可选**的：`frontend/package.json` 不存在就跳过构建，
镜照样能出。

这时：

- `http://<IP>:8000/` 返回一个说明页（**不是 404**），上面有 `/docs` 等入口
- `/api/**` 全部照常工作

**这是刻意设计的** —— M3 是硬里程碑，不该被"前端还没合进 main"卡住。
前端合并后重新 `docker compose up -d --build` 即可自动带上。

---

## 5. 排障

| 现象 | 先看什么 |
|---|---|
| `docker compose ps` 一直 `starting` | `docker compose logs` —— 多半是迁移失败或端口被占 |
| 本机能通、外网不通 | **两层防火墙**：云控制台的防火墙规则 + 系统内 `sudo ufw status` |
| 构建卡在 `npm ci` / `pip install` | 网络。配 Docker 镜像加速，或给 pip 换源（见 `Dockerfile`） |
| `(unhealthy)` | 健康检查打的是 `/api/health`。`curl` 一下看返回什么 |
| 改完代码没生效 | 镜像要重建：`up -d --build`。只 `restart` 用的是旧镜像 |
| 想彻底重置数据 | `docker compose down -v`（**会删库**） |

**看容器里的数据状态**：

```bash
docker compose exec xizhi python -c "
import sqlite3; from app.config import settings
con = sqlite3.connect(settings.db_file)
print('表数', len([r for r in con.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]))
print('迁移', con.execute('SELECT version_num FROM alembic_version').fetchone())
"
```

---

## 6. 待办与已知缺口

- [ ] **`/api/report/quality` 仍是 mock** —— `scripts/evaluate.py` 已经能算出真实指标，
      但接口还没复用同一套计算。**这是当前最大的结构性隐患**，见任务清单 T5
- [ ] **前端未合并** —— `frontend/` 还在 P3 的分支上，M3 的完整界面需要它先合入
- [ ] **HTTPS 未配置** —— 目前是裸 HTTP + IP。赛事要求不涉及，评审也只看能否访问；
      若后续要加，最省事的是前面挂一层 Caddy 自动签证书（但需要域名，仍受备案限制）
- [ ] 部署脚本尚未在**真实服务器**上跑过 —— 本地无 Docker daemon，未验证过镜像构建
