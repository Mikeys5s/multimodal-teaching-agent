# 上线操作说明（改版分支 → 生产 120.77.177.171:8000）

> 状态：**尚未上线**。本文是拿到服务器访问方式后的一次性操作清单。
> 相关：[`../../docs/deployment.md`](../deployment.md) · [`../../scripts/deploy.sh`](../../scripts/deploy.sh) · [`../../docs/deploy-verify-2026-09-20.md`](../deploy-verify-2026-09-20.md)

## 0 当前事实（2026-10-09 实测）

| 项 | 值 |
|---|---|
| 线上前端产物 | `/assets/index-C9x5krX1.js` + `index-CKBlMSo_.css`（**旧版**） |
| 本地新产物 | `/assets/index-CydAC2Tw.js` + `index-Bl2YuFO8.css`（改版后） |
| 线上后端 | `GET /api/health` → `{"status":"ok","db":"ok","llm":"not_in_use","version":"0.1.0"}` |
| 本机 SSH | **无 `~/.ssh`（无密钥、无 config）** → `scripts/deploy.sh` 当前跑不通 |
| 代码位置 | Gitee `origin/feat/frontend-visual-redesign` = `97a8cf5`（本机 HEAD 同 sha） |

**判定上线是否成功的唯一硬指标**：`curl -s http://120.77.177.171:8000/ | grep -o 'assets/index-[^"]*\.js'`
返回的 hash **变成 `index-CydAC2Tw.js`**（同一次构建的产物 hash 固定，不受部署时间影响）。

## 1 前置：把 SSH 打通（二选一）

### 方案 A：用私钥（推荐，可重复部署）

```bash
# 1) 把私钥放到本机（示例路径，按你的实际文件改）
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cp /path/to/你的私钥 ~/.ssh/xizhi_ed25519 && chmod 600 ~/.ssh/xizhi_ed25519

# 2) 写 ~/.ssh/config，别名必须是 xizhi（deploy.sh 默认 HOST=xizhi）
cat >> ~/.ssh/config <<'EOF'
Host xizhi
    HostName 120.77.177.171
    User root
    IdentityFile ~/.ssh/xizhi_ed25519
    ServerAliveInterval 10
EOF
chmod 600 ~/.ssh/config

# 3) 验证（必须无密码直接登录成功）
ssh -o BatchMode=yes xizhi 'echo OK && hostname'
```

### 方案 B：没有私钥、只有密码

本机没装 sshpass，`deploy.sh` 的 `BatchMode=yes` 也不接受交互输入。两条路：
1. `ssh-keygen -t ed25519` 生成密钥 → 把公钥内容贴到服务器 `/root/.ssh/authorized_keys`（最省事，之后全部免密）；
2. 或者不动本机，直接在服务器上执行本文 §2 的「服务器侧等价操作」。

## 2 上线（一条命令）

```bash
cd <仓库根>
bash scripts/deploy.sh
```

脚本会依次做（**幂等**，可重复跑）：

1. 从**工作区**打包（排除 `.git` / `node_modules` / `dist` / `.venv` / `*.db` / `.learnbuddy`），
   并断言包里含 `package-lock.json`（缺它 `npm ci` 必失败）；
2. 服务器上加 **2G swap**（2G 内存跑 `npm ci && vite build` 的保险）；
3. `scp` 上传 → 服务器上把旧 `/root/xizhi` **改名备份**（`/root/xizhi.bak.MMDD-HHMMSS`，可一条命令回滚）→ 解包新代码；
4. `docker compose up -d --build`（**这一步最慢**：2 核机器首次拉 node/python 基础镜像 + 前端构建，5–15 分钟）；
5. 跑 `scripts/check-deploy.py` 自检，**不通过就让整个部署失败**（非零退出）。

数据在具名卷 `xizhi_xizhi-data` 里，与代码目录无关，`up --build` 不会动它。

### 服务器侧等价操作（方案 B 或想手工控制时）

```bash
# 服务器上
cd /root
# ① 拿新代码（两种方式，任选）
#    a) git 方式
sudo apt-get install -y git   # 若没有
git clone -b feat/frontend-visual-redesign https://gitee.com/mikey_code/multimodal-teaching-agent.git xizhi-new
#    b) 或让本机 scp 一个 tar.gz 上来再解包（与 deploy.sh 的 ③ 相同）
# ② 切目录（旧目录改名保留，便于回滚）
mv xizhi xizhi.bak.$(date +%m%d-%H%M%S) 2>/dev/null; mv xizhi-new xizhi
# ③ 重建（改完代码必须重建镜像，只 restart 用的是旧镜像）
cd xizhi && docker compose up -d --build
```

## 3 上线后验证（三档，逐级加严）

**① 外网硬指标（本机即可，无需 SSH）**

```bash
curl -s http://120.77.177.171:8000/ | grep -o 'assets/index-[^"]*\.js'   # 期望 index-CydAC2Tw.js
curl -s -o /dev/null -w '%{http_code}\n' http://120.77.177.171:8000/            # 200
curl -s http://120.77.177.171:8000/api/health                                     # ok / db ok
```

**② 界面走查（改版专项）**

| 检查 | 期望 |
|---|---|
| 窄窗口拖到 390px | **无整页横向滚动**（改版前 `#root min-width:1024px` 会横滚） |
| 手机视口顶栏 | 出现汉堡菜单；点开左抽屉 6 项导航；Escape 关闭后焦点回到菜单按钮 |
| `/graph` | 节点是白底「地标卡」+ 左侧难度色轨；硬前置实线实心箭头、软前置点线空心箭头（图例在左下） |
| `/path` | 选一个知识点后是里程碑时间线，最后一步带蓝色「目标」徽标 |
| `/report` | 顶部四条核心红线；未达标项红框 + 文字（不靠颜色单独传达） |
| 控制台 | 无 error（F12） |

**③ 完整自检（需 SSH，最严格）**

```bash
python scripts/check-deploy.py     # 逐项哈希核对线上产物 = 本地构建产物
bash scripts/verify-deploy.sh      # 容器/健康/接口组合检查
```

## 4 回滚（一条命令）

```bash
ssh xizhi 'cd /root && ls -d xizhi.bak.* | tail -1'     # 找到最近一次备份
ssh xizhi 'cd /root && mv xizhi xizhi.failed && mv xizhi.bak.<时间戳> xizhi && cd xizhi && docker compose up -d --build'
```

## 5 已知注意点

- **必须 `.env.local` 不要进包**：本机开发用的 `frontend/.env.local` 已被 `.gitignore` 忽略（`frontend/.gitignore:31`），打包脚本也排除 `.env*`；生产是**同源相对 `/api`**，不依赖任何环境变量。
- **2G 内存**：构建期最容易 OOM 的一步是 `npm ci && vite build`，故脚本先加 swap；如果构建仍被 OOM kill，重跑一次通常能过（层缓存已部分建立）。
- **不要只 `docker compose restart`**：改的是镜像内容，必须 `up -d --build`。
- **前端产物 hash 会变**：因为本次改了 `tailwind.config.js` 与大量 CSS 类，产物 hash 与上版不同属正常；判定"是否上线成功"看 hash 是否等于**本地刚构建出的那一个**。
