# 接口规格（API Spec）

> 上游文档：[`../SPEC.md`](../SPEC.md) §4
> 版本：**v1.3** · 2026-09-17
>
> **v1.3 变更（冻结前补齐 6 处缺口，见 SPEC §12 变更日志）**：
> ① 新增 **`/api/health/pragma`**（实现早于规格，本应登记）—— 端点数 27 → **28**；
> ② 明确**非 JSON 响应**（markdown / CSV）的 `request_id` 走 **`X-Request-ID` 响应头**；
> ③ SSE 事件补 **`id:` 字段**（会话内单调递增），`Last-Event-ID` 续推才有依据；
> ④ `gap-analysis` 的 `student_evidence` 明确为**可重复查询参数**；
> ⑤ `needs_review` 查询参数统一为**布尔** `true`/`false`；
> ⑥ 分页补上**默认值与越界行为**。
>
> v1.2 · 2026-09-17（无端点增删，仅同步 SPEC 变更：音频链路移除；图谱/路径/报告增补创新点相关字段）
> 风格：REST + JSON；流式接口用 SSE
> 前缀：`/api`（生产环境下前端静态资源在 `/`，后端在 `/api`，同源无 CORS）

---

## 1. 通用约定

### 1.1 响应包封

成功：
```json
{ "ok": true, "data": { ... }, "request_id": "req_8f21" }
```

失败：
```json
{
  "ok": false,
  "error": { "code": "UNSUPPORTED_FORMAT", "message": "暂不支持 .pages 格式，请转为 PDF 或 DOCX", "detail": {} },
  "request_id": "req_8f21"
}
```

**规则**：`error.message` 必须是**能直接展示给用户的中文**，不允许出现英文堆栈或裸错误码。这是用户体验评分项。

**例外：非 JSON 响应（v1.3 新增）**

`GET /api/materials/{id}/markdown` 返回 `text/markdown`、`GET /api/export/knowledge-points?format=csv` 返回 `text/csv`。
这类响应**无法包封**（body 里塞不进 `ok` / `request_id`），因此约定：

| 情况 | 约定 |
|---|---|
| 成功 | 直接返回原始内容；`Content-Type` 为对应类型；**请求标识走 `X-Request-ID` 响应头** |
| 失败 | **仍返回 JSON 包封**（`Content-Type` 切回 `application/json`），错误结构与普通端点完全一致 |

这样前端只需要一套错误处理逻辑：**先看 `Content-Type`，非 JSON 时把错误分支交给那套包封解析**。

### 1.2 错误码

| HTTP | code | 场景 |
|---|---|---|
| 400 | `INVALID_PARAM` | 参数校验失败 |
| 400 | `UNSUPPORTED_FORMAT` | 文件格式不在白名单 |
| 400 | `FILE_TOO_LARGE` | 超过 50MB |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `JOB_IN_PROGRESS` | 同一资源已有任务在跑 |
| 422 | `LLM_SCHEMA_INVALID` | 结构化输出校验失败（已重试后） |
| 500 | `INTERNAL` | 兜底 |
| 503 | `LLM_UNAVAILABLE` | 模型服务不可用 |

### 1.3 分页

请求：`?page=1&page_size=20`

| 参数 | 默认 | 取值 | 越界行为 |
|---|---|---|---|
| `page` | `1` | 整数 ≥ 1 | 返回 `400 INVALID_PARAM` |
| `page_size` | `20` | 整数 1–100 | 返回 `400 INVALID_PARAM` |

响应：`{ "items": [...], "total": 137, "page": 1, "page_size": 20 }`

> **默认值必须写死在规格里**（v1.3 补充）。否则前端会按自己猜的默认值写死分页控件，
> 而 mock 与真实实现又可能不一致 —— 这类偏差在联调时才暴露，返工成本高。

### 1.4 任务轮询

耗时操作一律**立即返回 `job_id`**，前端轮询 `/api/jobs/{job_id}`。
任务完成前返回 `202 Accepted`。

---

## 2. 健康检查与元信息

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | `{ status, db, llm, version }` —— 演示前自检用 |
| GET | `/api/health/pragma` | **v1.3 补登记**：读回当前连接的实际 SQLite pragma 值。**`foreign_keys` 必须为 1** —— 它是"外键约束真的生效了吗"的可验证答案，而不是靠读代码猜 |
| GET | `/api/meta/capabilities` | 返回支持的素材类型、大小限制、当前 LLM provider/model，**前端据此渲染上传提示，避免硬编码** |

`/api/health/pragma` 响应：

```json
{
  "ok": true,
  "data": {
    "pragmas": { "journal_mode": "wal", "foreign_keys": "1", "busy_timeout": "5000" },
    "db_file": "D:\\...\\backend\\app.db"
  },
  "request_id": "req_8f21"
}
```

---

## 3. 素材（Stage 1）

### 3.1 上传素材

```
POST /api/materials
Content-Type: multipart/form-data
Body: files=<binary>[, files=<binary>...]
```

响应 `202`：
```json
{
  "ok": true,
  "data": {
    "accepted": [{ "material_id": "mat_a1", "filename": "第3章-排序.pdf", "job_id": "job_x1" }],
    "rejected": [{ "filename": "notes.pages", "reason": "暂不支持 .pages 格式，请转为 PDF 或 DOCX" }]
  }
}
```

**规则**：部分文件被拒绝时仍返回 `202`，`rejected` 数组必须给出可读原因；不得整批失败。

### 3.2 素材清单

```
GET /api/materials?status=&page=&page_size=
```

响应 `data.items[i]`：
```json
{
  "id": "mat_a1",
  "filename": "第3章-排序.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 2481920,
  "source_type": "pdf_scan",
  "parse_method": "multimodal_llm",
  "status": "partial",
  "page_count": 20,
  "duration_sec": null,
  "char_count": 18422,
  "quality_score": 0.86,
  "uncertain_count": 3,
  "uncertain_notes": [
    { "kind": "missing_field", "page": 12, "message": "第 12 页第 3 题只有题干与选项，未找到答案", "severity": "high" }
  ],
  "created_at": "2026-09-16T13:02:11Z"
}
```

> 这就是**素材清单**的数据源，字段设计直接对应 A1-4 验收。

### 3.3 素材详情 / 解析产物

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/materials/{id}` | 单份素材详情（同 3.2 结构） |
| GET | `/api/materials/{id}/blocks?page_no=&block_type=` | 解析块列表（Markdown 预览数据源） |
| GET | `/api/materials/{id}/markdown` | 拼接后的整篇 Markdown（`text/markdown`） |
| GET | `/api/materials/{id}/outline` | 章节骨架（章 → 节，未抽知识点时的中间态） |
| GET | `/api/materials/{id}/questions` | 从该素材抽出的题目列表 |

`/blocks` 响应元素：
```json
{
  "id": "blk_9f2a",
  "seq": 42,
  "page_no": 7,
  "line_start": 3,
  "line_end": 9,
  "block_type": "paragraph",
  "heading_level": null,
  "content_md": "分区完成后，基准元素左侧均不大于它……",
  "image_path": null,
  "ocr_confidence": 0.94
}
```

### 3.4 重试与删除

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/materials/{id}/reparse` | 重新解析，返回新 `job_id`（失败隔离，可单独重试） |
| DELETE | `/api/materials/{id}` | 删除素材及其级联数据 |

---

## 4. 知识点抽取与查询（Stage 2）

### 4.1 触发抽取

```
POST /api/extract/knowledge
Body: { "material_ids": ["mat_a1"], "force": false }
```

响应 `202`：`{ "job_id": "job_k1", "estimated_seconds": 120 }`
冲突时返回 `409 JOB_IN_PROGRESS`。

### 4.2 知识点查询

```
GET /api/knowledge-points
    ?chapter_id=&section_id=&material_id=
    &difficulty_min=1&difficulty_max=5
    &kp_type=&needs_review=
    &q=<关键词>
    &page=&page_size=
```

**查询参数取值（v1.3 明确）**

| 参数 | 取值 | 说明 |
|---|---|---|
| `difficulty_min` / `difficulty_max` | 整数 1–5 | 越界返回 `400 INVALID_PARAM`；`min > max` 同样返回 400 |
| `kp_type` | `concept` / `skill` / `theorem` / `method` / `fact` | 非法值返回 `400 INVALID_PARAM` |
| **`needs_review`** | **布尔 `true` / `false`**（v1.3 统一） | 不传 = 不过滤；非法值返回 `400 INVALID_PARAM` |
| `q` | 关键词 | 全文检索；空字符串等同不传 |

> `needs_review` 此前未定义取值，容易同时出现 `1` / `0` / `true` / `false` 四种写法。
> 统一为布尔字符串，`0`/`1` 视为非法值（**不静默兼容**，避免前端长期带着两套写法）。

响应 `data.items[i]`：
```json
{
  "id": "kp_3c81",
  "name": "快速排序的分区思想",
  "summary_md": "通过一次分区把基准元素放到最终位置，左侧均不大于它、右侧均不小于它。",
  "difficulty": 3,
  "difficulty_reason": "需要理解指针交换过程与不变式，但无需复杂数学",
  "kp_type": "method",
  "chapter": { "id": "ch_2", "number": "3", "title": "排序" },
  "section": { "id": "sec_2_2", "number": "3.2", "title": "交换排序" },
  "source": {
    "material_id": "mat_a1",
    "material_name": "第3章-排序.pdf",
    "page": 9,
    "block_id": "blk_9f2a",
    "quote": "分区完成后，基准元素左侧均不大于它……"
  },
  "prerequisite_count": 2,
  "example_count": 3,
  "misconception_count": 1,
  "needs_review": false,
  "confidence": 0.93
}
```

### 4.3 知识点详情

```
GET /api/knowledge-points/{id}
```

在 4.2 结构上追加：
```json
{
  "prerequisites": [
    { "kp_id": "kp_2f04", "name": "比较排序的时间下界", "relation_type": "hard", "reason": "不理解下界就无法解释快排的平均复杂度优势", "confidence": 0.88 }
  ],
  "examples": [
    { "id": "ex_1", "question_type": "single_choice", "stem_md": "...", "options_json": [...], "answer_md": "B", "analysis_md": "...", "difficulty": 3, "source_page": 11 }
  ],
  "misconceptions": [
    { "id": "mis_7d22", "description": "认为分区后基准元素仍可能移动", "cause": "把『分区』与『排序』混为一谈", "remedy": "强调分区只做一次交换定位，之后基准不再参与比较", "source": "human", "confidence": 0.9 }
  ]
}
```

### 4.4 地图与路径

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/knowledge-graph?material_id=&chapter_id=&max_nodes=200` | DAG 数据：`{ nodes: [...], edges: [...] }`，节点带 `difficulty`（前端颜色映射）、`needs_review`；边带 `relation_type` |
| GET | `/api/learning-path?kp_id=kp_3c81` | 学习路径：拓扑有序数组 `[{ order, kp_id, name, difficulty, reason }]`，含 `is_start_point` 标记 |
| GET | `/api/knowledge-points/{id}/gap-analysis` | **卡点根因回溯**（F3.8）：沿 `hard` 边反向可达，返回该知识点的全部硬前置与"最可能的断层"排序 |

**`gap-analysis` 的可选参数（v1.3 明确）**

```
GET /api/knowledge-points/{id}/gap-analysis?student_evidence=<误区id>&student_evidence=<误区id>
```

| 参数 | 取值 | 说明 |
|---|---|---|
| `student_evidence` | `kp_misconceptions.id` | **可重复**（`?student_evidence=a&student_evidence=b`），一次可传多个。传了它，系统会把命中的误区纳入"最可能断层"的排序依据 |
| `student_evidence` 无效值 | 不存在的 id | **忽略该值而非报错** —— 它只影响排序精度，不该让整个请求失败 |


`/learning-path` 的 `reason` **必须来自边上的 `reason`**（P10 产出），前端逐条展示 —— 这样"为什么这个要排在前面"是可解释的，不是黑盒拓扑排序的结果。

`/gap-analysis` 响应：
```json
{
  "target_kp": { "kp_id": "kp_5t13", "name": "TCP 拥塞控制" },
  "hard_prerequisites": [
    { "kp_id": "kp_5t09", "name": "滑动窗口机制", "depth": 1, "reason": "不理解窗口就无法理解 cwnd 的调节对象" }
  ],
  "likely_gap": {
    "kp_id": "kp_5t09",
    "name": "滑动窗口机制",
    "evidence": "本轮命中误区『把拥塞窗口与接收窗口混为一谈』",
    "source": { "material_id": "mat_a1", "page": 88 }
  },
  "suggestion": "你这一题卡在 TCP 拥塞控制，但根因更可能是滑动窗口没吃透 —— 建议先回第 88 页，再回来学拥塞控制。"
}
```

`/knowledge-graph` 响应：
```json
{
  "nodes": [
    { "id": "kp_3c81", "name": "快速排序的分区思想", "difficulty": 3, "chapter_id": "ch_2", "section_id": "sec_2_2", "needs_review": false }
  ],
  "edges": [
    { "source": "kp_2f04", "target": "kp_3c81", "relation_type": "hard" }
  ],
  "stats": { "node_count": 42, "edge_count": 67, "cycle_count": 0, "pruned_count": 2, "conflict_count": 3, "hard_edge_count": 41, "soft_edge_count": 26 }
}
}
```

**`edges` 的方向语义（v1.5 明确 —— 之前只在代码注释里，文档没写）**

| 层 | 前置 | 后置 |
|---|---|---|
| **API**（本接口的 `edges`） | **`source`** | **`target`** |
| 数据库 `kp_prerequisites` | `prereq_kp_id` | `kp_id` |

> **`source` 是前置，`target` 是后置。** 即 **「要学会 `target`，得先会 `source`」**。
>
> 例：`{ "source": "kp_2f04", "target": "kp_3c81" }`
> 读作 **「要学会 `kp_3c81`，得先会 `kp_2f04`」**。
>
> ⚠️ **前端画箭头时不要搞反。** 这一条出错**不会报任何错** ——
> 只会让图谱里的依赖箭头与学习路径**整个反过来**，
> 而"顺着箭头看"的人会得到完全错误的学习顺序。
> **所以它是文档级的硬约定，不是注释级的小事。**
>
> 代码里的定义（两处都有，但都在代码里、不在文档里，故在此固化）：
> `backend/app/models/knowledge.py` 的 `KpPrerequisite` docstring、
> `backend/app/schemas/graph.py` 的 `GraphEdgeOut` docstring。

> `stats.cycle_count` 必须在 UI 上展示为 0 —— **把 DAG 无环这个工程指标变成评委可见的信任信号**。
>
> 同时展示 `pruned_count`（因成环被剪除的边数）与 `conflict_count`（结构-语义冲突边数）：**"检出了 2 条会成环的边并已剪除"比只写"环数 0"更有说服力** —— 前者证明系统真的在检查，而不只是恰好没出错（对应 B1-2 / B1-4）。

### 4.5 导出

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/export/knowledge-points?format=json` | 全字段 JSON 导出 |
| GET | `/api/export/knowledge-points?format=csv` | 扁平 CSV，含溯源列 |

### 4.6 质量报告

```
GET /api/report/quality
```

```json
{
  "materials": { "total": 6, "done": 5, "failed": 1, "avg_quality_score": 0.88 },
  "knowledge_points": {
    "total": 184,
    "structure_complete_rate": 1.0,
    "five_field_complete_rate": 0.97,
    "grounding_rate": 1.0,
    "needs_review_count": 6
  },
  "graph": { "edge_count": 267, "cycle_count": 0, "pruned_count": 2, "conflict_count": 3, "reason_complete_rate": 1.0, "prerequisite_sampling_pass_rate": 0.84 },
  "qa": { "session_count": 3, "turn_count": 41, "grounded_rate": 1.0, "refuse_count": 5 }
}
```

> 这个接口是「质量报告页」（F4.3）的数据源，也是 Demo 视频里的一个亮点镜头 —— 把工程严谨度可视化。

---

## 5. 答疑辅导（Stage 3）

### 5.1 会话

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/qa/sessions` | Body: `{ "material_scope": ["mat_a1"], "student_label": "demo" }` → `{ session_id }` |
| GET | `/api/qa/sessions/{id}` | 会话详情 + 全部轮次 |
| DELETE | `/api/qa/sessions/{id}` | 删除 |
| GET | `/api/qa/sessions/{id}/report` | 会话诊断报告（汇总全部卡点与建议练习） |

#### 响应字段表（v1.5 补齐 —— 之前**只列了端点、没写字段**，导致前端只能猜）

> **⚠️ 本节字段以 pydantic 模型为准。**
> 冲突时以 `backend/tests/test_schemas.py` 的 `PINNED_FIELDS` 为最终依据 ——
> **那是一份被测试守住的名字清单，而本表是人工维护的、会漂。**
> 补这一节的目的：把那份清单**翻译成给人读的形式**，让下一个人不必去读代码。

**`SessionDetailOut`**（`GET /api/qa/sessions/{id}`）

| 字段 | 类型 | 说明 |
|---|---|---|
| **`id`** | `str` | ⚠️ **叫 `id`，不叫 `session_id`**（与下面的 `SessionReportOut` 不一致 —— 历史遗留，D9 前不改） |
| `student_label` | `str \| null` | |
| `material_scope` | `list[str]` | 本次会话覆盖的素材 id |
| `created_at` / `updated_at` | `str` | ISO 时间 |
| `turns` | `list[TurnOut]` | 按 `seq` 升序 |

**`TurnOut`**（`SessionDetailOut.turns` 的元素）

| 字段 | 类型 | 说明 |
|---|---|---|
| **`id`** | `str` | ⚠️ **叫 `id`，不叫 `turn_id`** |
| `seq` | `int` | 会话内单调递增，**与 SSE 的 `id:` 是同一个序列** |
| `role` | `str` | `student` / `tutor` |
| **`content_md`** | `str` | ⚠️ **学生轮与导师轮都是它** —— 没有单独的 `question` / `answer_md` |
| `turn_type` | `str \| null` | 导师轮才有（`refuse` / `explain` / `probe`…） |
| `retrieved_kp_ids` | `list[str]` | |
| `retrieved_block_ids` | `list[str]` | |
| `grounded` | `bool` | 是否基于材料（**幻觉率的分母只用导师轮**） |
| `diagnosis` | `DiagnosisOut \| null` | 每轮三件产出：`knowledge_points` / `stuck_at` / `next_practice` |
| `latency_ms` | `int \| null` | |
| `created_at` | `str` | |

**`SessionReportOut`**（`GET /api/qa/sessions/{id}/report`）

| 字段 | 类型 | 说明 |
|---|---|---|
| **`session_id`** | `str` | ⚠️ **这个叫 `session_id`**（与 `SessionDetailOut.id` 不一致 —— 历史遗留，D9 前不改） |
| `turn_count` | `int` | |
| `grounded_rate` | `float` | **分母不含拒答轮次**（拒答是能力不是缺陷） |
| `stuck_points` | `list` | 卡点汇总 |
| **`suggested_practices`** | `list` | ⚠️ **是复数** —— 不是 `suggested_practice` |
| `summary_md` | `str` | |

### 5.2 提问（SSE 流式）

```
POST /api/qa/sessions/{id}/ask
Accept: text/event-stream
Body: { "question": "这题为什么用快排不用冒泡？" }
```

SSE 事件序列（顺序固定）。**每个事件都带 `id:`，值为会话内单调递增的 `seq`**（v1.3 补充）：

```
id: 41
event: retrieved
data: {"seq":41,"kp_ids":["kp_3c81","kp_2f04"],"block_ids":["blk_9f2a"],"is_out_of_scope":false}

id: 42
event: state
data: {"seq":42,"turn_type":"probe","state":"S1_PROBE","hint_level":0}

id: 43
event: delta
data: {"seq":43,"text":"先想一个问题："}

id: 44
event: delta
data: {"seq":44,"text":"如果数组已经是升序的，快排还需要比较多少次？"}

id: 45
event: diagnosis
data: {"seq":45,
       "knowledge_points":[{"kp_id":"kp_3c81","name":"快速排序的分区思想","difficulty":3}],
       "stuck_at":{"step":"尚未建立分区与最终位置的关系","evidence_kp_id":"kp_3c81","evidence_misconception_id":null},
       "next_practice":[{"kp_id":"kp_3c81","task":"手写一次 Hoare 分区过程"}]}

id: 46
event: done
data: {"seq":46,"turn_id":"turn_88","latency_ms":2310,"usage":{"input_tokens":1820,"output_tokens":96}}
```

**约定**
- **`id:` 行必须有，且与 `data.seq` 一致**（v1.3 补充）。SSE 协议的 `Last-Event-ID` 请求头携带的就是 `id:` 的值；
  规格此前只提了续推、没定义 `seq` 来源，实现时无从下手。**`seq` 在一个会话内单调递增，跨轮次不重置。**
- `retrieved` 必须先于任何 `delta` —— 前端据此先渲染溯源卡片，让"先检索再回答"这件事**在界面上可见**。
- 越界时：`retrieved.is_out_of_scope = true`，`state` 事件为 `turn_type: "refuse"`，`delta` 内容为拒答模板，**不得包含任何材料外知识断言**。
- 进入降级讲解时：`state` 事件 `turn_type: "explain"`，前端据此展示"连续两次没答上，我直接讲"的提示。
- 连接中断：客户端带 `Last-Event-ID: <最后一个 seq>` 重连，服务端**从该 seq 之后**续推。

### 5.3 状态机查询（供前端渲染进度）

```
GET /api/qa/sessions/{id}/state
```

```json
{
  "state": "S2_HINT1",
  "hint_level": 1,
  "consecutive_failures": 1,
  "current_kp_id": "kp_3c81",
  "next_action": "hint2",
  "explain_threshold": 2
}
```

> **为什么要有这个接口**：苏格拉底状态机是产品的核心差异化，但它是"看不见的逻辑"。把它暴露成接口 + 前端可视化（如三轮进度指示器），就能让评委**看得见引导策略的存在**。这是技术创新性得分的具体抓手。

---

## 6. 任务

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/jobs/{job_id}` | 单任务详情 → `JobOut`（字段见下） |
| GET | `/api/jobs?target_id=&job_type=` | 按资源查任务 → `JobListOut` |

`stage_detail` 示例：`"正在识别第 7/20 页"`、`"正在抽取 3.2 交换排序 的知识点"`。**必须是人类可读中文**，前端直接展示，不加工。

#### `JobOut` 字段表（v1.5 修正 —— 之前这行写的是 `{ status, progress, stage_detail, result, error }`，**`result` / `error` 两个名字是错的**）

> ⚠️ **这行曾经把前端带偏过**：`result` 与 `error` 这两个名字**不存在**，
> 真实的字段名是 **`result_json`** 与 **`error_message`**。
> 前端照旧那行写类型，在主路径（读 `status` / `progress`）上完全正常，
> **只有走到完成/失败分支才会读到 `undefined` —— 而且不报错。**
> 所以这一节改成逐字段列出，不再用一行内联结构描述。

| 字段 | 类型 | 说明 |
|---|---|---|
| **`id`** | `str` | ⚠️ **叫 `id`，不叫 `job_id`** —— 但**请求路径参数**仍叫 `{job_id}`（`/api/jobs/{job_id}`） |
| `job_type` | `str` | 如 `parse` / `extract` / `ocr` |
| `target_id` | `str \| null` | 该任务作用的资源 id（素材 / 知识点集…） |
| `status` | `str` | `pending` / `running` / `done` / `failed` / `partial` |
| `progress` | `int` | **0–100**。前端进度条用它 |
| `stage_detail` | `str \| null` | **人类可读中文，直接展示不加工**；分页进度也拼在这里（如"正在识别第 7/20 页"），**不另开结构化字段** |
| **`result_json`** | `str \| null` | ⚠️ **是 JSON 字符串，不是对象** —— 前端要 `JSON.parse` |
| **`error_message`** | `str \| null` | ⚠️ **是字符串，不是 `{code, message}`** |
| `started_at` / `finished_at` | `str \| null` | ISO 时间 |
| `created_at` | `str` | |

**异步任务的统一用法**（`POST /api/materials`、`POST /api/extract/knowledge` 等一律如此）：

```
POST <触发端点>          → 202 { job_id, estimated_seconds }
GET  /api/jobs/{job_id}  → JobOut（上面的表）   ← 用同一个 job_id 轮询
```

**前端直接复用同一套轮询逻辑即可**，不需要为不同任务类型写多套 ——
`job_type` 只用来区分语义，轮询行为完全一致。

---

## 7. 接口清单速查

| # | 方法 | 路径 | 所属 | 阶段 |
|---|---|---|---|---|
| 1 | GET | `/api/health` | 运维 | — |
| 2 | GET | `/api/meta/capabilities` | 元信息 | — |
| 3 | GET | `/api/health/pragma` | 运维 | — |
| 4 | POST | `/api/materials` | 素材 | Stage 1 |
| 5 | GET | `/api/materials` | 素材 | Stage 1 |
| 6 | GET | `/api/materials/{id}` | 素材 | Stage 1 |
| 7 | GET | `/api/materials/{id}/blocks` | 素材 | Stage 1 |
| 8 | GET | `/api/materials/{id}/markdown` | 素材 | Stage 1 |
| 9 | GET | `/api/materials/{id}/outline` | 素材 | Stage 1 |
| 10 | GET | `/api/materials/{id}/questions` | 素材 | Stage 1 |
| 11 | POST | `/api/materials/{id}/reparse` | 素材 | Stage 1 |
| 12 | DELETE | `/api/materials/{id}` | 素材 | Stage 1 |
| 13 | POST | `/api/extract/knowledge` | 抽取 | Stage 2 |
| 14 | GET | `/api/knowledge-points` | 知识点 | Stage 2 |
| 15 | GET | `/api/knowledge-points/{id}` | 知识点 | Stage 2 |
| 16 | GET | `/api/knowledge-graph` | 图谱 | Stage 2 |
| 17 | GET | `/api/learning-path` | 路径 | Stage 2 |
| 18 | GET | `/api/export/knowledge-points` | 导出 | Stage 2 |
| 19 | GET | `/api/report/quality` | 报告 | 全 |
| 20 | POST | `/api/qa/sessions` | 答疑 | Stage 3 |
| 21 | GET | `/api/qa/sessions/{id}` | 答疑 | Stage 3 |
| 22 | POST | `/api/qa/sessions/{id}/ask` | 答疑（SSE） | Stage 3 |
| 23 | GET | `/api/qa/sessions/{id}/state` | 答疑 | Stage 3 |
| 24 | GET | `/api/qa/sessions/{id}/report` | 答疑 | Stage 3 |
| 25 | DELETE | `/api/qa/sessions/{id}` | 答疑 | Stage 3 |
| 26 | GET | `/api/jobs/{job_id}` | 任务 | — |
| 27 | GET | `/api/jobs` | 任务 | — |
| **28** | GET | `/api/knowledge-points/{id}/gap-analysis` | **卡点根因回溯** | Stage 3 |

**共 28 个端点**（v1.3 加入 `/api/health/pragma`，原为 27）。任何新增端点需走 SPEC §12 变更流程。

> 这张表是 `tests/test_api_contract.py` 的**解析来源** —— 测试会把它与 `app.openapi()` 的实际端点集合做比对，
> 多一个少一个都失败。**所以新增端点必须先改这张表**，规格与实现的漂移会立刻暴露。

---

## 8. 前端路由与端点对应

| 路由 | 页面 | 主要端点 |
|---|---|---|
| `/` | 概览（可选） | `/api/report/quality` |
| `/materials` | 素材工作台 | 3、4、5、6、7、10、11、25 |
| `/graph` | 知识图谱 | 12、13、14、15 |
| `/path` | 学习路径 | 16 |
| `/tutor` | 答疑辅导 | 19–24 |
| `/report` | 质量报告 | 18 |
