# P1 · 本机开发环境搭建与验证记录

> 日期：2026-09-17（v2，基线更新至 `2ac2852`） · 执行人：P1（DakerDack） · 工具：LearnBuddy
> 用途：记录本机环境从零到「可开发」的过程、验证证据与本机特有的环境坑，供队友对照复现。
> 上游文档：[`dev-environment.md`](../dev-environment.md)（环境要求与已知坑）· [`backend/README.md`](../../backend/README.md)
>
> **v1 → v2 改了什么**：基线从 `ccfb2a8` 更新到 `2ac2852`（测试 61 → 217、端点 5 → 28）；
> venv 方案改为仓库新约定（`scripts/setup-venv.sh`，venv 建在项目外 + junction）；
> 新增坑 D（pip 卸载 editable 失败）与坑 E（`git rebase` 会删掉 `.git/refs`）。

---

## 1. 结论

**后端环境已就绪**：虚拟环境可用、依赖装齐、**217 项测试全绿**、静态检查通过、依赖无冲突、迁移建库成功、服务可启动且 **28 个操作**全部注册。

---

## 2. 环境事实

| 项 | 值 |
|---|---|
| 仓库位置 | `D:\multimodal-teaching-agent`（原克隆）/ 本次测量在干净副本 `C:\Users\XiaoZH\.xizhi-check\repo` |
| 测量基线 | `2ac2852`（Merge PR #8 `fix/venv-outside-project`） |
| Python | 3.13.14 |
| venv 位置 | **项目外** `C:\Users\XiaoZH\.venvs\xizhi-backend`，经 junction 映射为 `backend/.venv` |
| 配置文件 | 仓库根 `.env`（复制自 `.env.example`，全部默认值） |
| git 提交身份 | `DakerDack` / `272972788+DakerDack@users.noreply.github.com`（全局，依据 SPEC §9.1） |
| Node（备用） | v22.22.2 / npm 10.9.7 |

### 2.1 venv 方案（按仓库新约定）

```bash
bash scripts/setup-venv.sh                       # 首次搭建
bash scripts/setup-venv.sh --rebuild             # 环境坏了重建
```

脚本做五件事：找 Python ≥ 3.11 → 腾出 junction 位置 → 在项目外建 venv → 装依赖 → 建 junction 并验证。
实测通过，且验证项 `项目内实际文件数 = 0` 成立（文件确实都在项目外）。

> **不要手动 `python -m venv .venv`** —— 那样建出来的环境在项目目录里，会被 `dev-environment.md` §0 描述的清理程序删掉。

**⚠️ 本机一个默认值问题（建议修脚本）**：脚本默认把 venv 建在
`C:\Users\${USERNAME}\.venvs\xizhi-backend`，但**本机 `$USERNAME` = `isac_hw`，而用户目录实际是 `C:\Users\XiaoZH`**（两者不一致，文件属主也显示 `isac_hw`）。
于是脚本在第 2 步报 `[!!] 建不出 C:\Users\isac_hw\.venvs\xizhi-backend`。

规避（用脚本自带的覆盖变量）：

```bash
XIZHI_VENV_DIR='C:\Users\XiaoZH\.venvs\xizhi-backend' bash scripts/setup-venv.sh
```

建议改法：默认值用环境变量 `USERPROFILE`（`$USERPROFILE` 或 `%USERPROFILE%`）而不是拼 `C:\Users\$USERNAME`。

### 2.2 依赖版本（本机实际解析结果）

venv 用 `pip install -e ".[dev]" --no-build-isolation -i https://pypi.org/simple` 安装。

| 包 | 版本 | pyproject 约束 |
|---|---|---|
| fastapi | 0.141.1 | `>=0.115` |
| uvicorn | 0.53.0 | `>=0.32` |
| sqlalchemy | 2.0.54 | `>=2.0.36` |
| alembic | 1.20.0 | `>=1.14` |
| pydantic | 2.13.5 | （随 fastapi） |
| pytest | 9.1.1 | `>=8.3` |
| ruff | 0.16.8 | `>=0.8` |
| httpx | 0.28.1 | `>=0.28` |
| xizhi-backend | 0.1.0 | 本项目（editable） |

解析出的版本普遍比约束下限新不少（fastapi 0.141.1 带的是 starlette 1.6.0）。测试有 2 条来自 starlette 的
`DeprecationWarning`（`httpx` 与 `anyio.abc.BlockingPortal` 别名），**当前不影响结果**，上游后续版本可能移除。

> 该 venv 只装了 `[dev]`。**P1 另需 `[parse]`**，见 §7。

### 2.3 解析链路依赖（P1 专用）

在 v1 的 venv 上已装齐并逐个 import 验证通过：

| 包 | 版本 | pyproject 约束 | 备注 |
|---|---|---|---|
| pymupdf | 1.28.2 | `>=1.25` | `import fitz` 已被上游标记 deprecated，新代码建议 `import pymupdf` |
| python-docx | 1.2.0 | `>=1.1` | |
| python-pptx | 1.0.2 | `>=1.0` | |
| **paddleocr** | **3.7.0** | `>=2.9` | ⚠️ 解析到 **3.x 大版本**，API 与 2.x 不兼容 |
| paddlepaddle | 3.3.1 | `>=2.6` | cp313 wheel |
| paddlex / modelscope | 3.7.2 / 1.40.1 | （随 paddleocr） | |
| numpy / opencv-contrib / shapely / pyclipper | 2.3.5 / 4.10.0.84 / 2.1.2 / 1.4.0 | （随依赖） | |

**两个待团队决策的风险**

1. **paddleocr 装成 3.x**：`pyproject.toml` 写的是 `>=2.9`，语义上允许 3.x，但两代 API 差别很大（`predict()` vs `ocr()`）。
   按 2.x 文档写解析代码会直接跑不通。→ 待定：**收窄约束锁 2.x，还是直接用 3.x 并重写调用示例**。
2. **PaddleOCR 3.x 首次调用会联网下载模型权重**（走 modelscope/huggingface），与「离线构建、沙箱内无外网」冲突。
   → 待验证：**离线环境下能否完成首次 OCR**，需要提前把模型缓存到本地。

---

## 3. 验证证据

全部命令在 `backend/` 下执行，Python 为 project 外 venv 的 `backend/.venv/Scripts/python.exe`。

### 3.1 测试

```bash
.venv/Scripts/python.exe -m pytest -q
```

**217 passed（0 失败，31.6 秒）**。测试函数 141 个（`def test_` 静态统计），含参数化后展开为 217 项：

| 文件 | 测试函数数 |
|---|---|
| `test_api_smoke.py` | 49 |
| `test_models_constraints.py` | 28 |
| `test_models_extra.py` | 22 |
| `test_ids.py` | 11 |
| `test_schemas.py` | 11 |
| `test_migration_schema.py` | 7 |
| `test_skeleton.py` | 7 |
| `test_api_contract.py` | 6 |

### 3.2 静态检查 / 依赖冲突

```bash
.venv/Scripts/python.exe -m ruff check .     # All checks passed!
.venv/Scripts/python.exe -m pip check        # No broken requirements found.
```

### 3.3 迁移

```bash
.venv/Scripts/python.exe -m alembic upgrade head
#  -> 74bc5654395d  core tables
#  -> 335b7e83d38f  harden integrity: composite FK chain + utc time guard
#  -> 1383d287b94e  add remaining 8 tables
```

结果：**15 张表**，`alembic_version = 1383d287b94e`。

### 3.4 服务端点

| 端点 | 结果 |
|---|---|
| `GET /api/health` | 200 `{"status":"ok","db":"ok","llm":"not_in_use","version":"0.1.0"}` |
| `GET /api/health/pragma` | 200 `foreign_keys=1`、`journal_mode=wal`、`busy_timeout=5000` |
| `GET /openapi.json` | 200 —— **25 条路径 / 28 个操作**（与「28/28 端点齐备」一致） |

### 3.5 ⚠️ 一个需要注意的执行顺序问题（干净环境）

在**全新的干净副本**上按 `pytest → alembic upgrade head` 的顺序执行时，`alembic` 会失败：

```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) table materials already exists
[SQL: CREATE TABLE materials (...)]
```

**原因**：先跑测试会在 `backend/app.db`（真实库，非 tmp）留下 15 张表和 `alembic_version`，
但迁移版本记录与实际结构不匹配，于是 `upgrade` 又从第一个迁移开始建表 → 撞表。

**规避（实测有效）**：把残留库移走后重跑，3 个迁移正常应用、15 张表齐全。

```python
import os; os.rename(r'backend\app.db', r'backend\app.db.parked')   # 删除被拦，用重命名
```

**建议**：干净环境按 `alembic upgrade head → pytest` 的顺序初始化；或者由 P2 确认
「哪个测试写了真实 `app.db`」并隔离掉（`tests/` 归属 P2）。

---

## 4. 本机环境坑（5 条，均为实际发生）

> 与 `dev-environment.md` 的关系已在每条里注明，**不重复它已收录的内容**。

### 坑 A · Bash 命令过滤器会误报引号错误，命令根本没执行 🆕

**现象**：`unexpected EOF while looking for matching '`，退出码 2，但命令里**没有未闭合的引号**，且命令**未被执行**。

已确认的触发形态（可复现）：

| 触发形态 | 例子 |
|---|---|
| 含 Windows 盘符路径 | `python -m venv D:/repo/backend/.venv` |
| 引号包裹的含空格 / 中文路径 | `rm "D:/新建文件夹 (2)/.../check.txt"` |
| 特定 URL 字符串 | `git clone https://github.com/.../multimodal-teaching-agent.git` |
| 用 `;` 串联多条命令 | `node --version; npm --version` |
| **随机的普通命令** | 同一命令重试 1–2 次往往就能成功 |

**规避**：把操作写成 **Python 脚本**（`subprocess` 调目标程序、`shell=False`、`encoding="utf-8", errors="replace"`），
用相对路径执行，结果写日志文件再读；启动失败就原样重试。

> 这条**会浪费队友时间**：报错信息完全指错方向（像语法错误，实际是过滤器拦截），且与 `dev-environment.md` 其它坑都不同源。

### 坑 B · PowerShell 工具的输出不可见 🆕

**现象**：命令退出码正常，但 stdout / stderr **全空** —— 连 `Write-Output "hello"` 都没有输出。

**规避**：把结果写入文件，再用读取工具读文件。

### 坑 C · `rm` 要求绝对路径，而绝对路径又触发坑 A

`dev-environment.md` 坑 4 已收录「删除被拦 → 改用重命名」。补充两点新发现：

- 用**相对路径** `rm` 会被直接拒绝（`relative path rejected (must be absolute)`）
- 而**绝对路径**若含空格 / 中文，会触发坑 A —— 于是两条路都不通
- 结论：**删仓库内的文件用 Python `os.rename` 移走**，不要试图 `rm` 或 `os.remove`（仓库路径下 `os.remove` 同样被 `SAFE_DELETE_FAIL_CLOSED` 拦下）

### 坑 D · venv 已有 editable 安装时，`pip install -e .` 必定失败 🆕

**现象**：pip 下载安装一切正常，走到最后重装 editable 包时：

```
Attempting uninstall: xizhi-backend
[safe-delete][SAFE_DELETE_FAIL_CLOSED] {"target": "...\\__editable__.xizhi_backend-0.1.0.pth", "reason": "windows-sandbox-recycle-bin-unavailable"}
ERROR: Could not install packages due to an OSError: [safe-delete][SAFE_DELETE_FAIL_CLOSED]
```

**危害比报错本身大**：pip 事务中断，**排在 editable 包之后的所有依赖都不会被安装**（本次静默丢掉了
`modelscope-hub` / `modelscope` / `paddlex` / `paddleocr` 四个），而报错正文只在 stderr 里，容易被 stdout 淹没。

**根因**：与「不要升级 pip」同源 —— 删除要走回收站、沙箱内回收站不可用；pip 卸载 editable 包必然要删 `.pth`。

**规避**：

```bash
# ① 装 extras 时不带 -e .，直接点名缺的包
.venv/Scripts/python.exe -m pip install paddleocr

# ② 或新环境一次装完，不要分两次（首次安装不会触发卸载）
.venv/Scripts/python.exe -m pip install -e ".[dev,parse]" --no-build-isolation
```

**自检**：装完拿 `pip freeze` 与 extras 清单逐项对照，别只看退出码。

### 坑 E · `git rebase` 会删掉 `.git/refs/`，导致仓库不可用 ⚠️🆕

**这条本次复现了两次，第二次以「先备份 → 再复现」的方式确认，可以排除偶发。**

**现象**：执行 `git rebase origin/main` 时驱动进程中断，随后所有 git 命令报：

```
fatal: not a git repository (or any of the parent directories): .git
```

**检查发现**：`.git/refs/` **整个目录消失**（本地分支引用全丢）；第二次连 `objects` 也少了一部分
（`fatal: bad object HEAD`、`missing blob ...`、`fetch` 报 `did not send all necessary objects`）。

**判定**：`objects/pack`、`index`、`HEAD`、`config`、`packed-refs` 与工作区文件**通常完好**，
坏的只是 `refs/`（git 要求它存在才认仓库）。这与 `dev-environment.md` §0 的「按路径批量删文件」现象一致，
但**触发条件更具体：`rebase` 这种高频改写 `.git` 的操作**。`git switch -c <分支> origin/main`（无工作区变更）实测无害。

**恢复 runbook（本次两次都靠它无损恢复，约 10 分钟内）**

```python
import os
GIT = r'<repo>\.git'
# 1) 重建 refs 目录结构（缺它 git 直接不认仓库）
for sub in ('refs', 'refs/heads', 'refs/tags', 'refs/remotes/origin'):
    os.makedirs(os.path.join(GIT, sub), exist_ok=True)

# 2) 用远端 sha 写回本地分支引用（最可靠）
#    sha = git rev-parse origin/<branch>
with open(os.path.join(GIT, 'refs/heads/docs/p1-env-readiness'), 'w', encoding='ascii') as f:
    f.write('<sha>\n')

# 3) 若 objects 也缺，用提前备份的 .git 覆盖回灌（copytree 只覆盖、不删除）
#    shutil.copytree(backup_git, GIT, dirs_exist_ok=True)
```

```bash
git read-tree HEAD          # 索引与 HEAD 对齐，工作区文件不动
git reset --mixed HEAD
git fetch origin
git fsck --connectivity-only   # 期望 exit 0
```

**预防**：

1. **动 `.git` 之前先备份**：`shutil.copytree('.git', '<项目外>/git_backup')`（本仓库 `.git` 仅约 456 KB，成本极低）
2. 需要同步 `main` 时，**优先用「新克隆 + 基于 `origin/main` 建分支」**，而不是在本仓库 rebase
3. 无论如何：**勤提交、勤推送**（本次两个提交早已推送，才做到零丢失）

> 建议把这条并入 `dev-environment.md`（属共享文档，需先在 Issue 知会，本 PR 不动它）。

---

## 5. 网络与加速

| 项 | 实测 |
|---|---|
| GitHub 直连 | 首次 clone 约 10 分钟；后续一次 clone **8 秒**（网络波动大） |
| pip（清华镜像） | `pip install -e ".[dev]"` 106 秒 |
| pip（官方源） | `scripts/setup-venv.sh` 用官方源，整轮（建 venv + 装依赖 + 建 junction）约 3 分 20 秒 |

⚠️ **镜像不是稳的**：`dev-environment.md` 坑 1b 记录过清华源不可达（`from versions: none`）的情况，
且 `curl` 返回 200 并不代表 pip 能取到版本列表。**建议以官方源为默认，镜像仅作临时加速**；
本机所有镜像用法都只注入环境变量（`PIP_INDEX_URL`），**未写入 `pyproject.toml` / `pip.ini` 等任何仓库内配置**。

---

## 6. 分支与协作

```bash
git fetch origin
git switch -c <类型>/<任务名> origin/main     # 直接从远端引用建分支（无 rebase，规避坑 E）
```

本次文档的分支 `docs/p1-env-readiness` 即按此方式**基于最新 `origin/main`（`2ac2852`）重建**，
不再使用 rebase。远端分支引用已用 `git ls-remote origin refs/heads/main` 取权威 sha 校验（参见 `dev-environment.md` 坑 6）。

> 若团队坚持 rebase 流程，请先确认 `.git` 备份已就绪，并知晓坑 E 的恢复步骤。

---

## 7. 尚未完成 / 待办

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | `[dev]` 依赖 | ✅ | 测量用 venv 已装齐 |
| 2 | `[parse]` 解析链路依赖（P1 专用） | ✅ 在旧 venv 上装齐 / ⚠️ 新方案 venv 未装 | 新 venv 只有 dev；P1 需补 `pip install paddleocr pymupdf python-docx python-pptx`（不带 `-e .`，见坑 D） |
| 3 | 旧克隆 `D:\multimodal-teaching-agent` 的 venv 迁移 | 待办 | venv 仍在项目内，建议 `bash scripts/setup-venv.sh --rebuild` 迁到项目外 |
| 4 | paddleocr 版本口径 + 离线模型缓存 | **待团队决策** | 见 §2.3 |
| 5 | 干净环境 `pytest`/`alembic` 顺序问题 | 待 P2 确认 | 见 §3.5 |
| 6 | 云服务器（学生认证 → 领券 → 下单） | **待人工** | D1 任务，需本人账号操作 |
| 7 | 部署环境搭建 | 待办 | 依赖服务器到位 |
| 8 | Ollama + `qwen2.5:3b-instruct` 兜底通道 | 未安装 | 约 2GB，`extraction-channel.md` §4 |
| 9 | 教材 PDF/EPUB 材料、自造 M-C 扫描件 / M-D 板书照片 | 待办 | D1 任务 |
| 10 | 中文材料跑通抽取通道 | 待办 | `extraction-channel.md` §7 |

---

## 8. 队友复现步骤（照抄即可）

```bash
git clone https://github.com/RyeYen/multimodal-teaching-agent.git
cd multimodal-teaching-agent

# ① 建环境（venv 会在项目外，junction 指回 backend/.venv）
#    若本机 $USERNAME 与用户目录不一致（见 §2.1），加一句覆盖：
XIZHI_VENV_DIR='C:\Users\<你>\.venvs\xizhi-backend' bash scripts/setup-venv.sh

# ② 建库（注意顺序：先迁移，后测试 —— 见 §3.5）
cd backend
.venv/Scripts/python.exe -m alembic upgrade head

# ③ 自检
.venv/Scripts/python.exe -m pytest -q         # 期望 217 passed
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m pip check

# ④ 起服务
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

打开 `http://127.0.0.1:8000/docs`，应看到 25 条路径 / 28 个操作。

**动 `.git` 之前先备份**（坑 E）：

```python
import shutil; shutil.copytree(r'<repo>\.git', r'<项目外>\git_backup')
```
