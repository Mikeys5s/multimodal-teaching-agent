# 开发环境与已知坑

> 本文目的只有一个：**让已经踩过的坑不再被第二个人踩。**
> 每一条都是实际发生过的 —— 不是"理论上可能"，是"已经浪费过时间"。
>
> 相关：[`../CONTRIBUTING.md`](../CONTRIBUTING.md)（Git 协作规范）· [`../backend/README.md`](../backend/README.md)（后端上手）

---

## ⚠️ 0. 已知环境风险：有程序在批量删除本仓库下的文件

**实测发生过 4 次**：`.venv/Lib/site-packages/` 下所有包变成 **0 个文件**
（目录结构和 `.dist-info` 还在）、`.git/objects/pack/` 被清空。

**特征**：目录结构完整、只丢文件 → **不是磁盘故障，是有程序在按规则删除/隔离**。

### 试过但**无效**的办法

把 `D:\muti_tagent` 加进杀毒软件（火绒）信任区 —— **加了之后仍然被删**。
信任区界面原话是「**病毒查杀与病毒防护的扫描功能**将跳过以下信任项」，
它只管火绒自己的扫描链路，管不了别的机制。

> 所以**不能假定是杀毒软件**。火绒的「隔离区」和「日志」里如果没有对应记录，就可以排除它。

### ⛔ 结论：**不是杀毒软件**（但根因仍未完全定责）

**判定依据**（P1、P2 两台机器实测一致）：

1. 把仓库目录加进火绒**信任区**之后**仍然被删** —— 信任区只管它自己的扫描链路
2. 火绒的**「隔离区」与「日志」里没有任何对应时间的记录**
3. P1 做过对照实验：**`git rebase` 可稳定复现**（先备份 `.git` 再复现，**2/2 命中**），
   被删的是 **`.git/refs/`** —— 这不是杀毒软件的行为模式（见坑 11）

> ⚠️ **但不要过早收口**：`.venv/Lib/site-packages/` 被清空那几次**与 git 操作无关**
> （`.venv` 是 gitignored，git 不会碰它）。目前有两种可能，**尚未定论**：
> ① 触发条件比「git 操作」更宽；② **本来就是两件不同的事**。
> 正在按 Issue #20 用 `scripts/watch-files.py` 做多台机器的对照实验。

### ✅ 有效的办法：把 venv 放到项目外

**做法**：venv 建在项目外，用 **junction（目录联接）** 把 `backend/.venv` 指过去。

```
D:\muti_tagent\backend\.venv   ← junction（项目内只有一个目录项，0 个文件）
        ↓ 指向
C:\Users\<你>\.venvs\xizhi-backend   ← 真实的 4700+ 个文件在这里
```

**为什么这样有效**：文件在物理上不在项目目录里，按路径扫描的清理程序碰不到；
而 `backend/.venv/Scripts/python.exe` **路径完全没变** ——
文档、命令、脚本一个字都不用改。

**一条命令搞定**（见 §1），已经实测通过。

### 仍然需要你做的两件事

1. **查火绒的「隔离区」+「日志」**，看有没有对应时间的记录 —— 这是**定责**的证据
2. **勤提交、勤推送**。远端的东西不会丢，不要攒一大堆改动最后一起推

### 想抓现行的话

`.learnbuddy/tools/watch_files.py` 是文件哨兵：定时统计项目下各类文件数量，
一旦下降立刻告警并列出消失的路径。开着它干活，能拿到**精确时间点**。

---

## 1. 环境准备

```bash
# 后端环境（一条命令，含"venv 放项目外 + junction"的处理）
bash scripts/setup-venv.sh

# 环境坏了要重建
bash scripts/setup-venv.sh --rebuild

# 起服务
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

**脚本会做五件事**：找 Python ≥ 3.11 → 腾出 junction 位置 →
在 `%USERPROFILE%\.venvs\xizhi-backend` 建 venv → 装依赖 → 建 junction 并验证。

> **不要手动 `python -m venv .venv`** —— 那样建出来的环境在项目目录里，
> 会被上面 §0 说的问题删掉。用脚本。

**依赖分组是刻意的，不要图省事全装**：

| 组 | 谁需要 | 内容 |
|---|---|---|
| 默认 | 所有人 | fastapi / uvicorn / sqlalchemy / alembic / pydantic-settings |
| `[dev]` | P2、P3 | pytest / pytest-cov / httpx / ruff |
| `[parse]` | **只有 P1** | pymupdf / python-docx / python-pptx / paddleocr / paddlepaddle |

`[parse]` 里的 paddleocr + paddlepaddle 有**几个 GB**，跟后端日常开发无关。
装了会拖慢每一次 `pip install`，还容易和 ABI 版本打架。

---

## 2. 禁忌清单（不要做，以及为什么）

| ❌ 不要 | 为什么 | 后果 |
|---|---|---|
| `pip install --upgrade pip` | 升级要删旧的 `pip.exe`，本机安全删除机制走回收站，沙箱里回收站不可用 → 删除失败但旧包已卸载 | **venv 的 pip 直接坏掉**（`No module named pip`）。修法：`python -m ensurepip` |
| 没 `git fetch` 就直接 `git switch <分支>` | 本地分支指针可能停留在旧提交，目标分支里可能**没有** `backend/` 这类目录，git 会尝试删掉整个目录 | 工作区被清空、留下卡死的 git 进程与 `index.lock`，**`.venv/Scripts/` 也可能被删** |
| 直接 `Stop-Process` 杀卡死的 git 进程 | 宿主应用的 git 集成可能仍持有 `.git/index` 句柄 | 之后每次 `git add` / `git commit` 都报权限错误，只能重启应用 |
| `git push --force` | 团队规范明令禁止 | 覆盖他人提交。个人分支请用 `--force-with-lease` |
| 提交前不看 `git status` + `git diff --staged` | 容易把 `.env`、数据库文件、几个 GB 的模型一起推上去 | 泄露密钥 / 仓库臃肿，且公开仓库不可撤回 |
| 用 `rm` 删项目里的文件 | 本机删除机制走回收站，沙箱内走不通 | 报 `SAFE_DELETE_FAIL_CLOSED`。**改用重命名移走**（见坑 4） |
| 手工给 `created_at` 传任意时间字符串 | 时间列是 TEXT，排序靠字典序 | 混进带本地偏移的时间会让排序**静默出错**。现在有 CHECK 兜底，会直接报错 |
| **直接用 `git branch -f main origin/main` 更新本地 main** | `origin/main` 是**本地缓存**，`git fetch` 失败过一次它就可能停在旧位置 | 本地 main 被设到旧提交 → 下一个 `git switch main` 会**删掉新文件**（见坑 6） |
| **在本仓库 `git rebase`** | 实测**稳定触发** `.git/refs/` 被删（2/2），git 随即报 `not a git repository` | **仓库整体不可用**。替代：`git switch -c <分支> origin/main`（新克隆更稳）；需要同步 main 时**用 `merge`，不要 rebase**（见坑 11） |
| **给 bash 脚本的输出接管道**（`bash x.sh \| tail -30`） | 本机的命令过滤器会把管道场景一起打挂 | **输出全空 + 退出码 1**，看起来像脚本没跑。直接 `bash x.sh` 就正常（见坑 8） |

---

## 3. 已知坑与恢复流程

### 坑 1 · `pip` 被升级操作弄坏

**现象**：`No module named pip`，或 `pip is a package and cannot be directly executed`

**恢复**：
```bash
.venv/Scripts/python.exe -m ensurepip
```

---

### 坑 1b · pip 镜像不可达导致装不上依赖

**现象**：
```
ERROR: Could not find a version that satisfies the requirement setuptools>=68
       (from versions: none)
ERROR: Failed to build '<项目目录>' when installing build dependencies
```
`from versions: none` 说明**索引本身不可达**，不是版本约束问题。
注意：**`curl` 测镜像返回 200 不代表 pip 能拿到版本列表** —— 实测清华源在 curl 正常时 pip 仍然失败。

**根因**：`pip install -e .` 默认走**构建隔离**，会去下载 `setuptools`；而 venv 里恰好没有它，
下载又失败，整个安装就挂。

**恢复**：
```bash
# ① 先补 setuptools（换官方源）
.venv/Scripts/python.exe -m pip install setuptools -i https://pypi.org/simple

# ② 再装项目，跳过构建隔离
.venv/Scripts/python.exe -m pip install -e ".[dev]" --no-build-isolation -i https://pypi.org/simple
```

**降级方案**（连可编辑安装都做不了时）：直接装依赖列表即可 ——
从 `backend/` 目录下跑代码时 `import app` 本来就能工作：
```bash
.venv/Scripts/python.exe -m pip install -q fastapi "uvicorn[standard]" "sqlalchemy>=2" \
  alembic pydantic-settings python-multipart pytest pytest-cov httpx ruff -i https://pypi.org/simple
```

---

### 坑 2 · `git switch` 把工作区删空 + venv 损坏

**现象**：`git status` 里大量文件显示为 `D`；git 卡住不动；`.venv/Scripts/` 消失

**恢复（文件都在索引里，不会真丢）**：
1. 结束卡死的 git 进程
   ```bash
   powershell -NoProfile -Command "Get-Process | Where-Object { \$_.ProcessName -match '^git$' } | Select-Object Id"
   powershell -NoProfile -Command "Stop-Process -Id <PID> -Force"
   ```
2. 把锁文件**重命名**移走（删除会被拦，重命名不会）
   ```python
   import os; os.rename(r'<repo>\.git\index.lock', r'<别处>\index.lock.old')
   ```
3. `git restore .` —— 从索引恢复全部文件
4. 检查 `.venv/Scripts/` 是否还在；不在就把 `.venv` 整个重命名移走再重建

**预防**：
```bash
git fetch origin
git switch -c feat/xxx origin/main     # 直接从远端引用建分支，不经过旧提交
```

---

### 坑 3 · `.git/index` 被宿主应用独占

**现象**：`fatal: unable to write new index file`；`git commit` 报
`could not open '.git/COMMIT_EDITMSG': Permission denied`

**判断**：
```python
import os
os.open(r'<repo>\.git\index', os.O_RDWR)   # PermissionError 即被独占
```

**恢复**：**重启编辑器 / IDE / 带 git 集成的客户端**，释放句柄。

**无效的做法**：把 `GIT_INDEX_FILE` 指向别处（实测绕不过去）。

**附带症状**：`.pytest_cache` / `.ruff_cache` 写入报"拒绝访问"，同一原因，无害。

---

### 坑 4 · `rm` 被安全删除机制拦截

**现象**：`[safe-delete][SAFE_DELETE_FAIL_CLOSED]` 或 `relative path rejected`

**恢复**：**改用重命名移走** —— 删除需要走回收站所以被拦，重命名不需要。

```bash
python -c "import os; os.rename(r'<源>', r'<目标>')"
```

临时脚本建议统一放 `.learnbuddy/`（已在 `.gitignore` 中）或加 `.tmp_*` 前缀。

---

### 坑 5 · 沙箱内没有外网

**现象**：`curl https://github.com` 返回 `000`

**处理**：需要网络的命令（`pip install`、`git push/fetch`、`curl`）要用**沙箱外**执行；
纯本地命令（建目录、写文件、跑测试）留在沙箱内即可。

---

### 坑 6 · 用远端跟踪引用更新本地分支 —— 会删文件

**这是第二危险的坑**（仅次于"批量删文件"），实测栽过一次，代价是工作区被清空。

**危险写法**：
```bash
git branch -f main origin/main    # ← origin/main 是本地缓存，可能已过期
git switch main                    # ← 于是切到旧提交，把新文件全删掉
```

**为什么 `origin/main` 会过期**：它**只是本地记录**，只在 `git fetch` 成功时才更新。
一旦某次 fetch 失败或异常，它就会停在旧位置 —— 而 `git branch -f` 完全不会校验。

**征兆（看到就必须停下，不要继续往下跑）**：
```
error: cannot lock ref 'refs/remotes/origin/main': is at fca4e1f... but expected ccfb2a8
 ! ccfb2a8..6e783de  main -> origin/main  (unable to update local ref)
```
> **`cannot lock ref` = 本地记录不可信。** 看到它就该先修引用，而不是继续操作。

**正确做法**：
```bash
# ① 取权威值，不依赖本地缓存
git ls-remote origin refs/heads/main

# ② 用权威 sha 直接更新
git update-ref refs/remotes/origin/main <权威sha>
git branch -f main <权威sha>
git switch main
```

**已经中招了怎么办**（顺序不能乱）：
```
1. git update-ref refs/remotes/origin/main <权威sha>   # 先修引用
2. 杀掉卡死的 git 进程                                  # 见坑 7
3. 移走 .git/index.lock                                # 进程死了才移得动
4. git restore .                                       # 文件从索引恢复，不会丢
```

---

### 坑 7 · 卡死的 git 进程 + `index.lock` 移不走

**现象**：`fatal: Unable to create '.git/index.lock': File exists`，
但按提示"手动删掉锁文件"**删不掉**，报 `WinError 32 另一个程序正在使用此文件`。

**原因**：有一个 git 进程真的还活着并持有它 —— 典型是 `git switch` 卡在删除大量文件上
（也就是坑 6 发生时会连带产生）。

**正确顺序**（不要反复重试删锁，只会浪费时间）：
```bash
# 1) 查进程
powershell -NoProfile -Command "Get-Process | Where-Object { \$_.ProcessName -match '^git$' }"
# 2) 杀掉
powershell -NoProfile -Command "Stop-Process -Id <PID> -Force"
# 3) 移锁（用重命名，不用删除）
python -c "import os; os.rename(r'<repo>\.git\index.lock', r'<别处>\index.lock.old')"
# 4) 再执行 git 操作
```

---

### 坑 8 · Bash 命令过滤器会**误报引号错误**（命令其实没执行）

**现象**：报错像语法错误，但**命令里根本没有未闭合的引号**，而且**命令没有被执行**：

```
/usr/bin/bash: -c: line 1: unexpected EOF while looking for matching `''
```

**已知触发形态**（都是实测遇到的，非穷举）：

| 触发形态 | 例子 |
|---|---|
| 含 Windows 盘符路径 | `python -m venv D:/repo/backend/.venv` |
| 引号包裹的含空格 / 中文路径 | `rm "D:/新建文件夹 (2)/.../check.txt"` |
| 特定 URL 字符串 | `git clone https://github.com/owner/repo.git` |
| 用 `;` 串联多条命令 | `node --version; npm --version` |
| **给 bash 脚本的输出接管道**（P2 补充） | `bash x.sh \| tail -30` → 输出全空 + 退出码 1，**不报引号错但同样没跑成** |
| **随机的普通命令** | 同一条命令重试 1–2 次往往就能成功 |

**规避**：
1. **把操作写成 Python 脚本**（`subprocess` + `shell=False`）执行，结果写文件再读
2. 用**相对路径**而不是盘符路径
3. **别给 bash 脚本接管道**，直接 `bash x.sh`
4. 启动失败就**原样重试 1–2 次**

> **为什么值得单独记一条**：报错信息把人往"语法错误"上引，实际是过滤器拦截 —— 很容易浪费十几分钟去找不存在的引号问题。

---

### 坑 9 · PowerShell 工具的输出不可见

**现象**：命令退出码正常，但 **stdout / stderr 全是空的** —— 连 `Write-Output "hello"` 都没有输出。

**规避**：把结果**写入文件**，再用读文件的工具读回来。

---

### 坑 10 · git 的网络命令失败：**schannel TLS 后端**（不是网络问题）

**现象**：任何走网络的 git 命令（`push` / `fetch` / `ls-remote` / `clone`）**每次都卡约 91 秒**才失败：

```
fatal: unable to access 'https://github.com/<owner>/<repo>.git/':
schannel: server closed abruptly (missing close_notify)
```

**关键判断 —— 这不是网络问题**（别去折腾代理 / DNS / hosts / hosts 文件）：

| 探测 | 结果 |
|---|---|
| Python `urllib` 直连 `github.com` / `api.github.com` / `codeload.github.com` | 全部 **HTTP 200** |
| `gh api rate_limit` | **成功**（gh 走 Go 自己的 TLS 栈） |
| `git ls-remote`（默认 schannel） | **失败**，91 秒超时 |
| `git -c http.sslBackend=openssl ls-remote` | ✅ **4–6 秒成功** |

**根因**：Windows 上 git 默认用 **schannel**（系统 TLS）。本机 schannel 握手被中断（安全软件 / 中间盒做 TLS 检查时常见）；而 git 自带的 **openssl** 后端 + PortableGit 的 CA 包是好的。

**解法**（写一次永久有效；仓内配置，不进版本库）：

```bash
git config http.sslBackend openssl          # 推荐
git -c http.sslBackend=openssl push         # 或每条命令临时带上
```

**排查顺序**：git 网络操作失败 → **先用 openssl 后端试一次（6 秒出结果）**，再怀疑网络。

---

### 坑 11 · `.git/refs` 可能损坏（**`rebase` 能稳定触发，但不止 rebase**）

**现象**：所有 git 命令报 `fatal: not a git repository`；或 `cannot lock ref` / `unable to resolve reference`；
更隐蔽的情况是 `git diff` 给出**假结果**（例如显示远端"少了几千行"）。

**已知事实**：

- P1 实测：**`git rebase` 稳定触发** —— `.git/refs/` 整个目录消失（**2/2 命中**，用「先备份 `.git` → 再复现」的对照实验确认）；
  严重时 `.git/objects` 也会少文件（`bad object HEAD`、`missing blob`）
- P2 实测：**没跑过 rebase 也遇到过** refs 损坏 —— 所以**触发条件比 rebase 更宽**，按「**本地 refs 可能损坏**」这个现象来记，不要只归因于 rebase

**两种修法**

**① 轻量（引用记录坏了，但对象库完好）**：

```bash
git update-ref -d refs/remotes/origin/main     # 删掉坏引用
git remote prune origin                        # 清理失效的远端跟踪引用
git fetch origin                               # 重新取
```

**② 重量（`.git/refs/` 目录整个没了 → git 直接不认仓库）**：

1. 重建目录结构（缺它 git 就报 `not a git repository`）：
   `refs`、`refs/heads`、`refs/tags`、`refs/remotes/origin`
2. 用**远端 sha** 写回本地分支引用（最可靠）：
   `git rev-parse origin/<branch>` 取 sha → 写进 `.git/refs/heads/<branch>`
3. 对齐索引与工作区：`git read-tree HEAD` → `git reset --mixed HEAD`
4. `git fetch origin` → `git fsck --connectivity-only`（期望 exit 0）
5. 若 `objects` 也缺 → 用**提前备份的 `.git`** 覆盖式回灌（`shutil.copytree(backup, git_dir, dirs_exist_ok=True)`，只覆盖不删除）

**预防（成本极低，`.git` 只有几百 KB）**：**动 `.git` 之前先备份**（见 §5）。

---

## 4. Alembic 的两个必知事项

### 4.1 `autogenerate` 会静默漏东西 —— 必须逐个核对

实测漏过两类，而且**都是静默的**（不报错、不警告）：

| 漏什么 | 例子 | 为什么 |
|---|---|---|
| **表达式索引** | `Index("idx_x", text("col DESC"))` | Alembic 无法可靠反射表达式索引 |
| **CHECK 约束的增删** | 新增的 `CHECK` 只在新建表时跟随，改已有表时**不生成** | autogenerate 不比较 CHECK |

**对策**：
- 索引一律用普通列索引。SQLite 可以双向遍历索引，`DESC` 不带来收益
- 新加的 CHECK 要**手工补进迁移文件**（`batch_op.create_check_constraint(...)`，
  名字用 `op.f()` / `batch_op.f()` 包住，否则命名约定会二次拼接）
- **仓库里有 `tests/test_migration_schema.py` 做永久性比对** —— 它会对比"迁移建出的结构"
  与"模型定义"，把这类偏差变成一次明确的测试失败。**改动模型后一定要跑它。**

### 4.2 `downgrade` 会丢数据

SQLite 的 `DROP TABLE` 不可逆，且有数据时可能因约束冲突失败。

> **`alembic downgrade` 仅限本地开发库使用。禁止对共享库、演示库执行。**
> 需要回退线上结构时，写一个**新的正向迁移**去修正，而不是回滚。

另外：SQLite 改列必须走 batch 模式重建表 —— `alembic/env.py` 已开
`render_as_batch=True`，不要关掉。

---

## 5. 提交前自检（30 秒）

```bash
git status                    # 有没有意外的新增文件
git diff --staged             # 改动内容对不对
git diff --staged --name-only | grep -E "\.env|\.key|\.pem|\.db$"   # 应无输出
python -m pytest -q           # 测试是不是绿的
python -m ruff check .        # 静态检查
```

**每天开工第一件事（成本近零）**：

```bash
git restore .                 # 万一昨晚有文件被删，先恢复再看
```

> 文件都在 git 里，恢复是秒级的。**真正的风险是"在没恢复的状态下改了代码，然后 commit"** —— 那会把删除**固化**进历史。

**动 `.git` 之前先备份**（成本极低 —— `.git` 只有几百 KB）：

```python
import shutil
shutil.copytree(r'<repo>\.git', r'<项目外>\git_backup')
```

**任何一条不过，就不要提交。**
