# 后端 · 析知 XiZhi

FastAPI + SQLAlchemy 2.0 + SQLite。归属见 [`../SPEC.md`](../SPEC.md) §9.1。

---

## 快速开始

```bash
cd backend

# 1. 建虚拟环境（用 Python 3.13，已验证所有依赖有 cp313 wheel）
python -m venv .venv
.venv/Scripts/python.exe -m ensurepip          # 见下方「已知坑」

# 2. 装依赖
.venv/Scripts/python.exe -m pip install -e ".[dev]"     # P2 / P3 日常开发
# P1 需要解析链路时另外装：
# .venv/Scripts/python.exe -m pip install -e ".[parse]"

# 3. 起服务
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

打开 `http://127.0.0.1:8000/docs` 看接口文档。

**配置**：仓库根的 `.env`（从 `.env.example` 复制）。**不配也能跑** —— 所有配置项都有可用默认值。
相对路径一律相对 `backend/` 解析，不依赖当前工作目录。

---

## 目录归属

| 目录 / 文件 | 归属 | 说明 |
|---|---|---|
| `app/core/` | **共用** | 响应包封、错误码、request_id。新增共享件请先说明用途 |
| `app/models/` `app/schemas/` `app/extract/` `app/retrieve/` | **P2** | 数据模型、契约、抽取、检索 |
| `app/api/materials.py` `knowledge.py` `meta.py` | **P2** | |
| `app/api/qa.py` | **P3** | 已建好空文件，直接往里加路由 |
| `app/parse/` `app/llm/` | **P1** | 解析链路；`llm/` 保留不启用（SPEC §4.8） |
| `app/tutor/` | **P3** | 答疑状态机与模板库 |
| `frontend/` | **P3** | 不在本目录 |

**改别人的目录前先在 Issue 里说一声**（SPEC §9.1 归属纪律）。

---

## 三条必须遵守的约定

### 1. 响应必须走统一包封

```python
from app.core.response import Envelope, ok


@router.get("/xxx", response_model=Envelope[XxxOut])
def xxx() -> Envelope[XxxOut]:
    return ok(payload)
```

**不要用中间件包封** —— 那样 OpenAPI 里的 `response_model` 和实际返回结构会对不上，
P3 在 `/docs` 里看到的就不是真实形态。详见 `app/core/response.py` 的模块注释。

### 2. 错误消息必须是中文人话

```python
from app.core.errors import ApiError, ErrorCode

raise ApiError(ErrorCode.UNSUPPORTED_FORMAT, "暂不支持 .pages 格式，请转为 PDF 或 DOCX")
```

`message` 会**直接展示给用户**，不允许出现英文堆栈或裸错误码（`docs/api-spec.md` §1.1）。
框架自动抛的 404/405 已在全局处理器里翻成中文，不用你管。

### 3. 主键用确定性 ID，不用随机 ID

**这是验收项 A2-7「同输入可复现」的前提。**

| 实体 | 格式 | 例 |
|---|---|---|
| 素材 | `mat_<文件内容 sha1[:8]>` | `mat_a1b2c3d4` |
| 章 | `ch_<材料hash>_<章号>` | `ch_a1b2c3d4_3` |
| 节 | `sec_<材料hash>_<章号>_<节号>` | `sec_a1b2c3d4_3_4` |
| 知识点 | `kp_<材料hash>_<章号>_<节号>_<序号>` | `kp_a1b2c3d4_3_4_007` |

**为什么**：我们的抽取是离线、可反复重跑的。"这次重跑跟上次有什么变化"必须能回答，
随机 ID 会让逐条 diff 退化成整库重灌。而且这种 ID 一眼能看出归属，调试时省事。

---

## 已知坑（都踩过）

| 现象 | 原因 | 处理 |
|---|---|---|
| 装依赖时报 `SAFE_DELETE_FAIL_CLOSED` / `No module named pip` | `pip install --upgrade pip` 要删旧 `pip.exe`，被环境的回收站机制拦下，反而把 pip 弄坏 | **不要升级 pip**；已坏则 `.venv/Scripts/python.exe -m ensurepip` 修复 |
| `alembic revision --autogenerate` 生成**空迁移** | 模型文件没被 import，`Base.metadata` 里没有表 | 新增模型后**必须在 `app/models/__init__.py` 里 import** |
| 外键约束不生效 | SQLite 默认关闭外键，且 pragma 是**连接级**的 | 已在 `app/db.py` 用 connect 事件监听统一设置；`/api/health/pragma` 可自检 |
| 后台任务访问数据库报线程错误 | SQLite 默认禁止跨线程 | 已在 engine 里设 `check_same_thread=False` |

---

## 测试

```bash
.venv/Scripts/python.exe -m pytest -v          # 全量
.venv/Scripts/python.exe -m ruff check .       # 静态检查
.venv/Scripts/python.exe -m ruff format .      # 格式化
```

`tests/test_skeleton.py` 里有几条**基础设施回归测试**，其中
`test_foreign_keys_pragma_is_actually_enabled` 值得留意 ——
将来有人重构 `db.py` 时如果不小心去掉事件监听，它会立刻失败，
而不是等到数据脏了才发现。
