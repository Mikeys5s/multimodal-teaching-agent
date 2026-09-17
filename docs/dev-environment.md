# 开发环境与已知坑

> 本文目的只有一个：**让已经踩过的坑不再被第二个人踩。**
> 每一条都是实际发生过的 —— 不是"理论上可能"，是"已经浪费过时间"。
>
> 相关：[`../CONTRIBUTING.md`](../CONTRIBUTING.md)（Git 协作规范）· [`../backend/README.md`](../backend/README.md)（后端上手）

---

## ⚠️ 0. 先做这一件事：把仓库目录加入杀毒软件白名单

**实测发生过两次**：`.git/objects/pack/` 被清空、`.venv/Lib/site-packages/` 下所有包变成
**0 个文件**（目录结构和 `.dist-info` 还在）。

**判断依据**：目录结构完整、只丢文件 → **不是磁盘故障，是有程序在按规则删除/隔离**。
进程里能看到杀毒软件（本机是火绒 `HipsDaemon` / `HipsTray`）。

**请把 `D:\muti_tagent` 加入杀毒软件的排除目录。** 否则会反复发生 ——
表现为测试突然报 `No module named fastapi`、git 报 `not a valid object`。

**在这个问题解决之前**：**勤提交、勤推送**。本机随时可能再被清，
而远端的东西不会丢。不要攒一大堆改动最后一起推。

---

## 1. 环境准备

```bash
# 后端（Python 3.13 —— 已核实 paddlepaddle / pymupdf / sqlalchemy 都有 cp313 wheel）
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m ensurepip          # 见坑 1
.venv/Scripts/python.exe -m pip install -e ".[dev]"

# 起服务
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

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

**任何一条不过，就不要提交。**
