# D5 生产环境验证记录 · 2026-09-20（归属：P3）

> 对应 SPEC §9.5「D5 · P3 = 前端构建接入后端静态托管；**生产环境验证**」
> 对应验收项 **A4-5**（公网链接可访问，且**不依赖本地环境**）与风险 **R-20**（提交的链接在评审期打不开）
> 执行方式：**纯外网 HTTP**（`scripts/check-deploy.py` 需要 SSH 到主机，本机无 `~/.ssh/config`、`xizhi` 主机名不解析 → 那条路走不通）

---

## 0 结论

| 项 | 结果 |
|---|---|
| 检查项 | **31 PASS / 0 FAIL / 1 WARN（无害）** |
| A4-5「不依赖本地环境」 | ✅ **通过**（HTML / bundle / 资源路径三项独立证明） |
| 目标 | `http://120.77.177.171:8000` |
| 待人工完成 | 3 项（见 §4） |

---

## 1 公网可达性与稳定性

```
连续 5 次 GET /            -> [200, 200, 200, 200, 200]
连续 5 次 GET /api/health  -> [200, 200, 200, 200, 200]
/api/health -> {"status":"ok","db":"ok","llm":"not_in_use","version":"0.1.0"}
```

`llm=not_in_use` 同时证明**离线构建 + 运行期零模型依赖**这条硬约束在线上成立。

## 2 A4-5 核心：不依赖本地环境

| 检查 | 结果 |
|---|---|
| HTML 不含 `localhost` / `127.0.0.1` / `0.0.0.0` / `192.168.` / `10.0.` | ✅ 全无 |
| HTML 不含硬编码 `http(s)://…:8000` 绝对地址 | ✅ |
| HTML 用**绝对路径**引用产物 | ✅ `/assets/index-ZuPuPASf.js` |
| CSS 同样绝对路径且可取 | ✅ `/assets/index-BGO-aEep.css`（28241 B） |
| bundle 可取 | ✅ 359088 B |
| bundle 不含内网地址 / 未把 `VITE_API_BASE_URL` 烧成 IP | ✅ |
| bundle 的 API base 走**相对** `/api` | ✅ |
| bundle 不依赖外部 CDN | ⚠️ 仅命中 `reactjs.org/docs/error-decoder.html`（React 内部错误提示用的**常量字符串**，不是运行期依赖）→ **无害** |

> **为什么这三条能证明 A4-5**：只要还有一处 `localhost` 或绝对 IP，换台机器打开就会白屏。
> 三条都干净 → 换设备打开能用（**结构上**成立；实机验证见 §4）。

## 3 前端构建已接入后端静态托管（D5 P3 任务前半）

```
GET / /materials /graph /path /tutor /report  ->  全部 200 · ct=text/html · <div id="root"> 在
GET /api/definitely-not-registered            ->  404 · application/json（未被 SPA catch-all 抢走）
```

**六个路由由后端同一个端口提供，同源 → 不需要 CORS。** 这正是 `Dockerfile` 的形态设计（`/` 前端静态产物 + `/api/**` 后端）。

## 4 ⚠️ 本机做不到、必须由人完成的 3 项（A4-5 / R-20 剩余）

| # | 事项 | 为什么只能人做 |
|---|---|---|
| 1 | **换另一台设备 + 不同网络**实测（例如手机 4G 打开该地址） | A4-5 原文要求"换台电脑打开能用"；本机只有一个网络出口 |
| 2 | **主机到期时间必须晚于 2026-10-15**（R-20 ④） | 要登录云控制台看，HTTP 查不到 |
| 3 | **R-20 ③ 第二入口**：LearnBuddy 专家智能体页面链接 | 双保险，需人工提供 |

**部分证据（已有）**：本机与演示主机**不在同一内网**（`120.77.177.171` 是公网 IP），请求确实走了公网。

## 5 一个方法学说明：为什么「容器里是新代码」我用行为层证明

`scripts/check-deploy.py` 里**最关键**的一条是「本地 `backend/app/**/*.py` 清单哈希 == 容器里的清单哈希」，用来挡"部署跑完了但其实没生效"。**那条需要 SSH，本机做不到。**

替代证据（行为层，旧代码不可能产出）：

| 探针 | 线上结果 | 说明 |
|---|---|---|
| `/api/report/quality` 的 acceptance | 每条带 `sample_size`（638/638/631/631/0） | 这是 9/20 01:29 才修的行为 |
| `/api/materials/{id}/outline` | 非单章「传输层」的 mock | 这是 9/20 02:19 才修的行为 |
| `/api/learning-path` | 形状稳定（不再是 mock 对象） | 同上 |
| `/api/*` 未注册路径 | JSON 404 | 同上 |
| 前端 bundle | `index-ZuPuPASf.js`（9/19 是 `index-Bm0TWMu9.js`） | **证明前端重新构建过** |

**推论**：旧代码不可能产出这些新行为 → 新代码已生效。但这是**推论**，不是 `check-deploy.py` 那种清单哈希的直证 —— **建议有 SSH 的同学跑一次 `scripts/check-deploy.py` 补齐**。

## 6 顺带发现（已报 #66，不属本记录结论）

- **端点计数**：线上 `/openapi.json` = **28 个 path 模板 / 31 个 (path, method) 组合**。
  `scripts/verify-deploy.sh` 里写「端点总数（应为 31）」—— 数字对得上，**但要明确它数的是哪个口径**，否则下次会有人以为少了 3 个。
- **`scripts/verify-deploy.sh` 第 35–38 行用默认 `GET` 探 `review/import-edges` / `review/decide`** ——
  这两个是 **POST-only**，GET 必然 404。脚本没有断言，只打印 `HTTP 404` → **每次部署验证都会印出两个误导性的 404**。
  实测：`GET /api/review/queue` → 200（它是 GET）；另两个 → 404（**正确行为**）。
  —— 与 P2 在 #57 里总结的"v2 只比路径、不比方法"是同一条教训。

---

## 附：如何复跑

本记录的脚本在 P3 侧（`_tmp_probe/p3_d5_prod_verify.py`，纯 `requests`，无需 SSH）。
建议把可复用部分收进 `scripts/`，与 `check-deploy.py` 形成互补：

| 工具 | 覆盖 | 前置 |
|---|---|---|
| `scripts/check-deploy.py`（P2） | 代码身份（清单哈希）+ 容器健康 + 关键接口 | **需要 SSH** |
| `scripts/check-public-link.*`（P3，待收） | A4-5「不依赖本地环境」+ 稳定性 + 静态托管 | **只需公网** |
