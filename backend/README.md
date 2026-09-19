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

> **完整版见 [`../docs/dev-environment.md`](../docs/dev-environment.md)** —— 那份是给三个人看的。
> 这里只列与后端直接相关的。

| 现象 | 原因 | 处理 |
|---|---|---|
| 装依赖时报 `SAFE_DELETE_FAIL_CLOSED` / `No module named pip` | `pip install --upgrade pip` 要删旧 `pip.exe`，被环境的回收站机制拦下，反而把 pip 弄坏 | **不要升级 pip**；已坏则 `.venv/Scripts/python.exe -m ensurepip` 修复 |
| `alembic revision --autogenerate` 生成**空迁移** | 模型文件没被 import，`Base.metadata` 里没有表 | 新增模型后**必须在 `app/models/__init__.py` 里 import** |
| 外键约束不生效 | SQLite 默认关闭外键，且 pragma 是**连接级**的 | 已在 `app/db.py` 用 connect 事件监听统一设置；`/api/health/pragma` 可自检 |
| 后台任务访问数据库报线程错误 | SQLite 默认禁止跨线程 | 已在 engine 里设 `check_same_thread=False` |
| **迁移里少了索引 / CHECK 约束**（模型里有、库里没有，且不报错） | `autogenerate` 不比较 CHECK，也识别不了表达式索引 | **改完模型跑 `pytest`** —— `tests/test_migration_schema.py` 会对比"迁移建出的结构"与"模型定义"。缺的约束要手工补进迁移文件 |
| 时间字段写入报 `CHECK constraint failed` | 时间列强制 **UTC 单一格式** | 用 `app.models.utc_now_iso()`；不传也会自动填。格式为 `2026-09-17T12:00:00+00:00` |

---

## 迁移注意事项

**① `downgrade` 会丢数据。**

> `alembic downgrade` **仅限本地开发库使用**。禁止对共享库、演示库执行。
> 需要回退线上结构时，写一个**新的正向迁移**修正，而不是回滚。

**② SQLite 改列必须走 batch 模式。**

`alembic/env.py` 已开 `render_as_batch=True`，**不要关掉** —— 否则改列会直接失败。

**③ 复合外键（层级链一致性）。**

`sections` 与 `knowledge_points` 用复合外键把「节 / 章 / 材料必须同属一条链」钉在数据库层。
注意两点：
- 插入顺序必须是 `materials → chapters → sections → knowledge_points`
- 复合外键的**父侧必须有对应的唯一索引**（`chapters` 的 `UNIQUE(id, material_id)`、
  `sections` 的 `UNIQUE(id, chapter_id, material_id)`），否则约束形同虚设

---

## 测试

```bash
.venv/Scripts/python.exe -m pytest -v          # 全量
.venv/Scripts/python.exe -m ruff check .       # 静态检查
.venv/Scripts/python.exe -m ruff format .      # 格式化
```

三条**基础设施回归测试**值得留意，它们守的都是"将来有人重构时容易悄悄破坏"的东西：

| 测试 | 它守什么 |
|---|---|
| `test_foreign_keys_pragma_is_actually_enabled` | `db.py` 的连接事件监听被去掉 → 外键约束静默失效 |
| `test_migration_schema.py` 全部用例 | 迁移与模型不一致（autogenerate 静默漏约束） |
| `test_composite_fk_is_actually_enforced` | 复合外键"声明了但不生效"（父侧唯一索引形状不对时会发生） |
