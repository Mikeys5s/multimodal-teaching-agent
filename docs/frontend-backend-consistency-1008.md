# 前后端一致性排查报告

- **日期**：2026-10-08
- **范围**：前端（`frontend/src/`）与后端（`backend/app/`）的字段/类型/部署一致性
- **性质**：**只排查、不改代码**。本文件是本次唯一新增文件，未改动任何 `.py` / `.ts` / `.tsx`
- **背景**：后端 2026-10-07 加了 3 个重复组字段（`is_duplicate` / `duplicate_of` / `duplicate_group_size`）、改了检索打分、新增 `backend/app/kp_dedup.json` 与 `kp-titles.json`；线上跑的是 Docker 镜像里的代码

---

## ① 前端有没有用上后端的新字段

### 发现（事实）

在 `frontend/src/` 全目录搜索（含大小写不敏感变体）：

```
$ grep -rn "is_duplicate|duplicate_of|duplicate_group_size|display_title" frontend/src
No matches found

$ grep -rin "duplicate|display_title|is_dup" frontend/src
No matches found
```

**4 个字段（3 个新字段 + `display_title`）在前端源码中零引用。**

同时确认后端侧的真实状态：

| 字段 | 后端 API 是否返回 | 前端是否引用 |
|---|---|---|
| `is_duplicate` | ✅ 返回（`backend/app/schemas/knowledge.py:72`） | ❌ 无 |
| `duplicate_of` | ✅ 返回（`backend/app/schemas/knowledge.py:76`） | ❌ 无 |
| `duplicate_group_size` | ✅ 返回（`backend/app/schemas/knowledge.py:80`） | ❌ 无 |
| `display_title` | ❌ **API 未返回**（只在 `backend/app/tutor/retrieve.py:183` 内部打分用） | ❌ 无 —— 前端**没有**猜错 |

> 关于 `display_title`：用户在任务里提示"后端还没加，搜到就是前端猜错了"。实测**前端没搜到**（未猜错）。
> 需要澄清：`display_title` 这个名字**后端确实存在**，但只作为 `kp-titles.json` 的键、在 `retrieve.py` 的检索打分里内部使用（`retrieve.py:182-196`），**从未进入任何 API 响应模型**。所以"后端还没加到 API"的说法准确。

相关后端落点：

```
backend/app/schemas/knowledge.py:72   is_duplicate: bool
backend/app/schemas/knowledge.py:76   duplicate_of: str | None
backend/app/schemas/knowledge.py:80   duplicate_group_size: int
backend/app/kp_view.py:189-191        在构造 KpItemOut 时注入这 3 个字段
backend/app/kp_view.py:120           惰性加载 kp_dedup.json
```

### 影响

- 后端**已经**在列表/详情接口（`KpItemOut`，`GET /api/knowledge-points` 与 `/api/knowledge-points/{id}`）里返回这 3 个字段，但**前端一个都不读** → 这些信息在界面上**完全不可见**。
- 直接后果正是后端加字段要解决的问题：629 个知识点里 **462 个是副本**，同一段材料内容被抽了多遍。前端不消费 `is_duplicate` / `duplicate_group_size`，界面就会**原样显示两个内容一模一样的点**，评委看到会以为数据是凑数的。
- 不会崩溃：TS 接口是编译期的，运行时后端多返回的键会被静静忽略（前端只是"丢弃"，不是报错）。所以这是一个**静默的功能缺失**，没有任何报错提示。

### 建议

- **要不要修**：要。这是"后端已备好料、前端没上桌"的典型缺口。
- **谁修**：前端（P3）。类型层加 3 行即可，UI 展示可另排。
- **多大**：类型层改动约 3 行；若要真在界面用（例如"已合并显示 / 在材料中出现 N 处"角标）是小号 UI 工作。
- **文案红线**（照抄后端注释 `knowledge.py:70-71`）：只能写「**已合并显示**」这类，**不能写"已去重"** —— 副本仍在库里、仍可被检索到，写"已去重"是假的。

**本节结论：前端**还没接**这 3 个新字段（后端已返回，前端零引用；`display_title` 前端也没猜错）。**

---

## ② 前端是否有过时的类型定义

### 发现（事实）

前端 API 类型定义文件：**`frontend/src/lib/types.ts`**（模块注释见 `types.ts:1-22`，其自述口径是"对齐 api-spec"、"冲突时以 `backend/tests/test_schemas.py` 的 `PINNED_FIELDS` 为准"）。

前端 `KnowledgePoint` 接口（`frontend/src/lib/types.ts:319-334`）：

```ts
export interface KnowledgePoint {
  id: string
  name: string
  summary_md: string
  difficulty: Difficulty
  difficulty_reason: string
  kp_type: KpType
  chapter: ChapterRef
  section: SectionRef
  source: SourceRef
  prerequisite_count: number
  example_count: number
  misconception_count: number
  needs_review: boolean
  confidence: number
}
```

后端 `KpItemOut`（`backend/app/schemas/knowledge.py:43-83`）字段清单：

`id, name, summary_md, difficulty, difficulty_reason, kp_type, chapter, section, source, prerequisite_count, example_count, misconception_count, needs_review, confidence, is_duplicate, duplicate_of, duplicate_group_size`

#### 后端有、前端类型里没有的字段（即"前端会丢弃新字段"的风险点）

| 字段 | 后端类型 | 前端是否声明 | 说明 |
|---|---|---|---|
| `is_duplicate` | `bool`（默认 `False`） | ❌ 未声明 | 是否是重复组副本 |
| `duplicate_of` | `str \| None` | ❌ 未声明 | 该组代表的 kp_id |
| `duplicate_group_size` | `int`（默认 `1`） | ❌ 未声明 | 该组共几个成员 |

`KnowledgePointDetail extends KnowledgePoint`（`types.ts:397-401`）继承了同一个基类型，所以**详情接口同样缺这 3 个字段**。

#### 附带发现的类型口径不一致（非本次新增，但同属"前后端对不上"）

| 字段 | 前端 `types.ts` | 后端 pydantic | 差异 |
|---|---|---|---|
| `KpType`（`types.ts:296`） | `'concept' \| 'method' \| 'skill' \| 'principle' \| 'protocol' \| 'other'` | 描述为 `concept / skill / theorem / method / fact`（`knowledge.py:53`） | **枚举词表对不上**（前端多 `principle/protocol/other`，缺 `theorem/fact`） |
| `difficulty_reason` | `string`（必填） | `str \| None`（`knowledge.py:50`） | 前端过严：后端可为 `null` |
| `confidence` | `number`（必填） | `float \| None`（`knowledge.py:64`） | 前端过严：后端可为 `null` |
| `ChapterRef.number` / `SectionRef.number` | `string`（`types.ts:301/307`） | `str \| None`（`knowledge.py:20/27`） | 前端过严：后端可为 `null` |
| `SourceRef.page` / `block_id`（`types.ts:314/315`） | `number` / `string` | `int \| None` / `str \| None`（`knowledge.py:38-39`） | 前端过严：后端可为 `null` |

### 影响

- **主问题（3 个重复组字段）**：前端类型没声明 → 即便有人想用，TS 会报"属性不存在"，逼迫走 `any` 或断言；当前则表现为**静默丢弃**。这与 ① 是同一根因：类型没跟上，消费方自然也没接。
- **附带问题（类型口径不一致）**：前端的 `KpType` 词表与后端不一致（后端实际用的是 `theorem/fact` 等），以及多个"前端声明必填、后端可为 null"的字段 —— 都是**静默漂移**：主路径（列表正常有值）不会暴露，边界（某字段为 `null`）时才可能读到 `undefined`。其中 `KpType` 词表不一致更值得核对，因为它决定前端是否会漏渲染某些类型的点。

### 建议

- **要不要修**：要，且成本很低。
- **谁修**：前端（P3）；`KpType` 词表建议与后端（P2 / `PINNED_FIELDS`）对齐一次口径再定。
- **多大**：
  - 3 个重复组字段：类型层 **+3 行**（`types.ts:333` 后追加），属小改。
  - 类型松紧/枚举对齐：小改，但要先确认后端 `kp_type` 的真实取值集合（以 `tests/test_schemas.py::PINNED_FIELDS` 与数据库 `CHECK` 约束为准，别照文档猜）。

**本节结论：前端类型定义确实过时 —— `KnowledgePoint` / `KnowledgePointDetail` 缺 3 个重复组字段；另有 `KpType` 词表等 5 处口径不一致。**

---

## ③ 线上跑的前端产物是不是最新的（最要紧的一条）

### 发现（事实，命令输出原样贴）

SSH 通了（`ssh xizhi` 直连可用，无需指定 `-i` 与 IP）。

**容器内前端产物：**

```
$ ssh xizhi 'docker exec xizhi ls -la /app/frontend/dist/assets; ... cat /app/frontend/dist/index.html'
total 416
drwxr-xr-x 2 root root   4096 Oct  8 15:53 .
drwxr-xr-x 3 root root   4096 Oct  8 15:53 ..
-rw-r--r-- 1 root root 381074 Oct  8 15:53 index-C9x5krX1.js
-rw-r--r-- 1 root root  29077 Oct  8 15:53 index-CKBlMSo_.css
---INDEX---
    <script type="module" crossorigin src="/assets/index-C9x5krX1.js"></script>
    <link rel="stylesheet" crossorigin href="/assets/index-CKBlMSo_.css">
```

**工作区前端产物（`frontend/dist/`）：**

```
index.html   （Sep 21 15:25）
<script ... src="/assets/index-VgndHg0t.js"></script>
<link ... href="/assets/index-Cubj-nRg.css">

$ ls -la frontend/dist/assets
-rw-r--r-- index-Cubj-nRg.css   28982  Sep 21 15:25
-rw-r--r-- index-VgndHg0t.js   378891  Sep 21 15:25
```

**容器与镜像时间：**

```
$ ssh xizhi 'docker ps --format ...; docker inspect -f ... xizhi'
xizhi | 8b781b0d513d | Up About an hour (healthy) | 2026-10-08 16:00:28 +0800
image=sha256:8b781b0d513d... started=2026-10-08T08:00:29Z created=2026-10-08T08:00:28Z
```

**决定性交叉验证**（用最新前端特性字符串做指纹）：

```
# 容器内 bundle 是否含最新前端特性「点一下填入」（来自 frontend/src/pages/Tutor.tsx:297，提交 9afb401 / 2026-09-23）
$ ssh xizhi 'docker exec xizhi grep -c "点一下填入" /app/frontend/dist/assets/index-C9x5krX1.js'
1
$ ssh xizhi 'docker exec xizhi ls /app/frontend/dist/assets/ | grep -c VgndHg0t'
0

# 工作区旧 dist 是否含该特性
$ grep -c "点一下填入" frontend/dist/assets/index-VgndHg0t.js
0   ← 旧 dist 里没有
```

**容器内后端也确认带了新东西：**

```
$ ssh xizhi 'docker exec xizhi grep -n "is_duplicate|duplicate_group_size|display_title" /app/backend/app/schemas/knowledge.py'
72:    is_duplicate: bool = Field(
80:    duplicate_group_size: int = Field(
     （display_title 未命中，EXIT=1 → 与"未进 API"一致）

$ ssh xizhi 'docker exec xizhi ls -la /app/backend/app/kp_dedup.json /app/backend/app/kp-titles.json'
-rw-rw-rw- 1 root root 168381 Oct  8 15:24 /app/backend/app/kp-titles.json
-rw-rw-rw- 1 root root 108876 Oct  7 20:25 /app/backend/app/kp_dedup.json
```

### 判据与结论

任务给的判据是「**容器产物比工作区 dist 旧 ⇒ 部署没重新构建前端**」。**实测正好相反**：

- 容器 dist = **Oct 8 15:53**，工作区 dist = **Sep 21 15:25** → **容器比工作区新 17 天**。
- 容器 bundle 文件名 `index-C9x5krX1.js` 与工作区 `index-VgndHg0t.js` **不同**，且容器 bundle **含有** 2026-09-23 才加入的最新前端特性「点一下填入」，工作区旧 dist **不含**。
- 镜像创建于 **2026-10-08 08:00 UTC = 16:00 CST（今天）**，容器 `StartedAt` 同日 08:00:29Z。
- 容器内后端 schema **有**新字段，且 `kp_dedup.json` / `kp-titles.json` 都在（时间戳与工作区一致）。

**⇒ 线上部署是新鲜的：前端产物确实随今天（10/08）的镜像重新构建过，且内容对得上当前 `frontend/src`（最后改动是 2026-09-23 的 `9afb401`）；后端也带了新字段与两个数据文件。不存在"前端改了但线上没生效"这个坑。**

工作区的 `frontend/dist/` 是 **Sep 21 的旧残留**，但它**不影响部署**，三重保险都挡住了：

1. `frontend/.gitignore` 含 `dist/` → 未进 git（`git ls-files frontend/dist` 为空）；
2. `.dockerignore:34` 有 `**/dist` → 旧产物**根本进不了构建上下文**；
3. `Dockerfile` 阶段 1 用 `npm ci && npm run build` **强制重建**（见下节）。

### 影响

- **当前无影响**：线上前后端都是新鲜的。用户担心的"线上跑旧产物"**本轮未发生**。
- **残余风险**：镜像构建/部署必须"重新构建前端"才安全。虽然当前 Dockerfile 已经做到（`**/dist` 被排除、无法误用旧产物），但这条依赖"部署时走的是当前 Dockerfile"。若有人绕过 Dockerfile 用本地产物直接替换 `/app/frontend/dist`，就可能发旧包 —— 这是流程风险，不是当前故障。

### 建议

- **要不要修**：不需要修，**保持现有 Dockerfile + .dockerignore 组合**即可（它从设计上就杜绝了"发旧前端"）。
- **建议补充**：在部署脚本（`scripts/deploy.sh`）里加一条部署后断言 —— 例如"容器内 `dist/index.html` 引用的 JS 文件名 == 本地 `npm run build` 产物名"，或至少断言容器 dist 时间戳晚于本次构建开始时间。这样"前端改了没生效"以后会被**主动发现**，而不是靠人工比对。

**本节结论：已验证 —— 线上前端产物是最新的（Oct 8 15:53，含最新前端特性），不比工作区 dist 旧，反而新 17 天。**

---

## 附：构建命令与 Dockerfile（任务"顺便查"部分）

### `frontend/package.json` 构建命令

`frontend/package.json:7-12`：

```json
"scripts": {
  "dev": "vite",
  "build": "tsc --noEmit && vite build",
  "preview": "vite preview",
  "typecheck": "tsc --noEmit"
}
```

即 `npm run build` = **先 `tsc --noEmit` 类型检查、再 `vite build`**。注意：这一步会把 ② 里的类型不一致**当作编译期检查**——但因为它只是"多返回字段未声明"，不是类型错误，`tsc` 不会报错，所以**编译能过、问题不暴露**。

### Dockerfile 有没有前端构建步骤

**有。** `Dockerfile` 是两阶段构建：

- 阶段 1（`Dockerfile:33-54`，`FROM node:22-alpine AS frontend`）：`COPY . .` 后，若检测到 `frontend/package.json` 则 **`cd frontend && npm ci && npm run build`**（`Dockerfile:47-49`）。
- 阶段 2（`Dockerfile:80`）：`COPY --from=frontend /src/frontend/dist /app/frontend/dist`。

**⇒ Dockerfile 不是"只 COPY dist"，而是**从源码重新构建**前端。** 配合 `.dockerignore:34` 的 `**/dist`（旧产物进不了上下文），前端**必须**在镜像构建时现场重编，没有"本地构建后再部署"这个必需前提 —— 这正是为什么线上产物是新的。

---

## ⭐ 一句话结论

**不一致** —— 后端已返回 3 个重复组新字段、前端类型未声明也从未消费（属"后端备好料、前端没上桌"的类型 + 消费双向缺口）；但**线上部署本身是新鲜的**（前后端都随 2026-10-08 的镜像重建，不存在"前端改了没生效"的坑，工作区那份 Sep 21 旧 dist 被 gitignore + dockerignore + Dockerfile 重建三重隔离，不影响部署）。
