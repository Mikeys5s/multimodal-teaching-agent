# 数据模型规格

> 上游文档：[`../SPEC.md`](../SPEC.md) §4.6
> 版本：v1.4 · 2026-09-17
>
> **v1.4 变更**：新增 §0「数据完整性约定」—— ① **层级链一致性改用复合外键在数据库层强制保证**
> （原设计每个层级字段各挂一个单列外键，只能保证"各自存在"、保证不了"同属一条链"，错链数据不报错
> 却会让查询与质量报告算错）；② **时间字段收敛为唯一格式 + 三层防护**（ORM 默认值 / 数据库默认值 /
> CHECK 归一化校验），修复"混进本地时区偏移会让字典序静默出错"。
>
> **v1.3 变更**：主键由随机 UUID 改为**确定性路径式 ID**（原约定与验收项 A2-7「同输入可复现」冲突，
> 且重跑无法逐条 diff）；`materials` 补上 `file_hash` 字段（SPEC §5.1 C2 与 §8.2 D2 要求"按文件 hash
> 建唯一索引"，此前规格漏写）。
>
> 实现：SQLite（WAL 模式）+ SQLAlchemy 2.x ORM + Alembic 迁移
> 时间统一 UTC ISO8601 字符串（唯一格式，见 §0）。

### 主键约定（v1.3 重写）

**主键统一 `TEXT`，但采用确定性路径式 ID，不用随机 UUID。**

| 实体 | 格式 | 示例 |
|---|---|---|
| `materials` | `mat_<sha1(文件内容)[:8]>` | `mat_a1b2c3d4` |
| `material_blocks` | `blk_<材料hash8>_<seq:05d>` | `blk_a1b2c3d4_00007` |
| `chapters` | `ch_<材料hash8>_<章seq:03d>` | `ch_a1b2c3d4_002` |
| `sections` | `sec_<材料hash8>_<章seq:03d>_<节seq:03d>` | `sec_a1b2c3d4_002_003` |
| `knowledge_points` | `kp_<材料hash8>_<章seq>_<节seq>_<节内seq:03d>` | `kp_a1b2c3d4_002_003_007` |
| `kp_prerequisites` | 复合主键 `(kp_id, prereq_kp_id)` | — |

> ⚠️ **ID 里用位置序号 `seq`，不用章节号 `number`**（这是刻意的）。
> 章节号是展示用的原貌值（`3.2` 这种），直接拼进 ID 会有两个问题：
> ① 节号若不含章前缀（有的材料节号就是 `1`/`2`），跨章会撞 ID；
> ② 需要额外的规范化规则，规则越多越容易出错。
> `seq` 由我们在解析时按文档顺序赋值，同一父节点下天然唯一，无歧义。
> 章节号仍然完整存在 `number` 字段里供展示与检索。

**为什么不用随机 UUID**（这是 v1.3 的核心修正）：

1. **验收项 A2-7 要求「同输入可复现」** —— 随机 ID 会让同一份材料重跑后得到完全不同的主键，
   "可复现"就只剩一句口号。确定性 ID 让 A2-7 天然成立。
2. **抽取是离线、可反复重跑的**（SPEC §4.8）。"这次重跑比上次改了什么"必须能回答；
   随机 ID 会把逐条 diff 退化成整库重灌。
3. **ID 自带归属信息**（哪个材料、哪章哪节），调试与人工校验时省事。
4. 与成本控制 **C2** 天然合一：`material_id` 由文件内容 hash 决定，重复上传同一文件得到同一个 ID。

**代价（已知并接受）**：ID 较长；材料内容一变，其下所有 ID 全变 —— 但这本来就是应该发生的事
（内容变了就是新的抽取产物）。

> 章节号取自材料自身的编号（`number` 字段，保留原貌）；节内序号取自 `knowledge_points.seq`。

### 数据完整性约定（v1.4 新增）

**① 层级链一致性 —— 用复合外键在数据库层强制保证**

`knowledge_points` 与 `sections` 都存了冗余的层级字段（`chapter_id` / `material_id`），
用途是"便于按章 / 按材料查询"。但**单列外键保证不了它们同属一条链** ——
单列外键只能说"这个 chapter 存在""这个 material 存在"，
说不了"这个 chapter 属于这个 material"。错链数据不会报错，只会让查询与质量报告悄悄算错。

因此改用**复合外键**：

| 表 | 复合外键 | 保证的事 |
|---|---|---|
| `sections` | `(chapter_id, material_id) → chapters(id, material_id)` | 节所属的章，必须属于该节声明的材料 |
| `knowledge_points` | `(section_id, chapter_id, material_id) → sections(id, chapter_id, material_id)` | 知识点声明的节 / 章 / 材料必须是同一条链 |

配套的父侧唯一索引（复合外键的前置条件）：`chapters` 需 `UNIQUE(id, material_id)`，
`sections` 需 `UNIQUE(id, chapter_id, material_id)`。

均带 `ON UPDATE CASCADE` —— 调整某节归属时，其下知识点自动跟随，不必手工改。

> **代价（已知并接受）**：多 2 个复合外键 + 3 个唯一索引；插入顺序必须是
> materials → chapters → sections → knowledge_points（本来也是这个顺序）。

**② 时间字段格式 —— 唯一格式 + 三层防护**

时间列是 `TEXT`，排序依赖字符串字典序。**只要混进一个带本地时区偏移的时间**
（如 `2026-09-17T20:00:00+08:00`），字典序就会把一个"实际更早"的时间排到后面，
**而且全程不报错**。

因此把格式收敛为**唯一形式**：`UTC_ISO_FORMAT = %Y-%m-%dT%H:%M:%S+00:00`
（即 `2026-09-17T12:00:00+00:00`：UTC、秒精度、带 `+00:00` 偏移）。

| 层 | 手段 |
|---|---|
| ORM | `default=utc_now_iso`（`updated_at` 另有 `onupdate`） |
| 数据库 | `server_default = (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))` |
| 约束 | `CHECK (col IS strftime('%Y-%m-%dT%H:%M:%S+00:00', col))` |

> **为什么 CHECK 用 `strftime` 归一化比对而不是 GLOB 模式匹配**：GLOB 只校验"形状"，
> 实测 `2026-13-17T12:00:00+00:00`（13 月）能骗过它；而 `strftime` 会把这种值归一化成
> NULL 从而拒绝。它还会拒绝带本地偏移的时间，等于强制全库统一 UTC。

---

## 1. ER 总览

```
materials
  │
  ├─1:N─> material_blocks           溯源原子单位（页码/行号锚点）
  │         │
  │         └─<─ source_block_id ──┐
  ├─1:N─> chapters ─1:N─> sections ─┼─1:N─> knowledge_points
  │                                             │
  │                                             ├─1:N─> kp_examples
  │                                             ├─1:N─> kp_misconceptions
  │                                             ├─1:1─> kp_embeddings
  │                                             └─N:M─> knowledge_points
  │                                                     (kp_prerequisites, 前置 DAG)
  ├─1:N─> questions                从材料抽出的题目实体
  │
qa_sessions ─1:N─> qa_turns        答疑轮次（含检索依据、接地标记、诊断）
jobs                               异步任务状态
llm_calls                          LLM 调用日志（可观测性）
```

---

## 2. 表定义

### 2.1 `materials` — 素材

用户上传的原始文件，一行一份。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | `mat_<sha1(文件内容)[:8]>`，确定性 ID，见 §0 |
| `filename` | TEXT | NOT NULL | 原始文件名 |
| `file_hash` | TEXT | **NOT NULL, UNIQUE** | 文件内容 SHA-256（十六进制全串）。**成本控制 C2**：同一文件重复上传不重复抽取。也是 `id` 的生成依据 |
| `stored_path` | TEXT | NOT NULL | 落盘路径（相对 `UPLOAD_DIR`） |
| `mime_type` | TEXT | NOT NULL | MIME |
| `size_bytes` | INTEGER | NOT NULL | 文件大小 |
| `source_type` | TEXT | NOT NULL, CHECK IN (...) | `pdf_text` / `pdf_scan` / `docx` / `pptx` / `image` / `audio` |
| `parse_method` | TEXT | NULL, CHECK IN (...) | `text_extract` / `multimodal_llm` / `ocr` / `asr`，实际使用的方式 |
| `status` | TEXT | NOT NULL DEFAULT 'pending' | `pending` / `parsing` / `done` / `failed` / `partial` |
| `error_message` | TEXT | NULL | 失败原因（面向用户的文案） |
| `page_count` | INTEGER | NULL | 页数（音频为 NULL） |
| `duration_sec` | INTEGER | NULL | 音频时长 |
| `char_count` | INTEGER | NULL | 解析后正文字符数 |
| `uncertain_notes` | TEXT | NULL | **存疑处 JSON 数组**，见 §3.1 |
| `quality_score` | REAL | NULL | 解析质量自评 0–1 |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

索引：`idx_materials_status(status)`、`idx_materials_created(created_at)`

> **关于 `idx_materials_created` 为什么不写 DESC**（v1.3 修正）：
> ① SQLite 可以**双向遍历索引**，升序索引即可支持 `ORDER BY created_at DESC`，DESC 索引不带来收益；
> ② 表达式索引（`text("created_at DESC")`）**Alembic 的 autogenerate 识别不了，会静默漏掉** ——
> 实测踩过，迁移里少了这个索引而模型里有，两边不一致。用普通列索引可避免这类隐蔽偏差。

> **v1.3 新增 `file_hash`**：SPEC §5.1 C2 与 §8.2 D2 都要求"素材按文件 hash 建唯一索引，
> 同一文件重复上传不重复抽取"，但本文档此前漏写该字段。它是**成本控制的关键**——
> 没有它，改一次前端就要重跑一次解析、白烧 Credits。

### 2.2 `material_blocks` — 解析块（溯源原子单位）

素材解析后的最小 Markdown 单元。**一切溯源最终都落到这一行。**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | |
| `material_id` | TEXT | NOT NULL, FK → materials(id) ON DELETE CASCADE | |
| `seq` | INTEGER | NOT NULL | 文档内顺序，从 0 开始 |
| `page_no` | INTEGER | NULL | 页码（1-based）；音频为 NULL |
| `ts_start_ms` | INTEGER | NULL | 音频起始毫秒 |
| `ts_end_ms` | INTEGER | NULL | 音频结束毫秒 |
| `line_start` | INTEGER | NULL | 在该页内的起始行号 |
| `line_end` | INTEGER | NULL | 结束行号 |
| `block_type` | TEXT | NOT NULL | `heading` / `paragraph` / `table` / `code` / `formula` / `image_caption` / `question` / `other` |
| `heading_level` | INTEGER | NULL | 1–6，仅 heading |
| `content_md` | TEXT | NOT NULL | Markdown 内容 |
| `image_path` | TEXT | NULL | 关联图片（图片块、题图） |
| `bbox` | TEXT | NULL | 版面坐标 JSON `[x1,y1,x2,y2]`，用于高亮定位（可选） |
| `ocr_confidence` | REAL | NULL | 该块识别置信度 0–1 |

约束：`UNIQUE(material_id, seq)`
索引：`idx_blocks_material_seq(material_id, seq)`

> **音频相关字段说明（v1.2）**：`source_type` 的 `audio` 取值、`parse_method` 的 `asr` 取值、`ts_start_ms` / `ts_end_ms` / `duration_sec` 字段**全部保留但初赛不启用** —— SPEC §6.1 已决定完全不做音频链路（D-08 反转）。保留是为了不阻塞将来的扩展，**代码中不得存在依赖这些字段的业务分支**，避免留下"半成品痕迹"。

### 2.3 `chapters` / `sections` — 章与节

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | |
| `material_id` | TEXT | NOT NULL, FK → materials(id) | 来源素材（跨素材合并章节为 v2 需求，初赛不做） |
| `parent_id` | TEXT | NULL | sections 指向 chapters.id |
| `number` | TEXT | NULL | 章节号，如 `3.2`（保留材料原貌） |
| `title` | TEXT | NOT NULL | 章节标题 |
| `seq` | INTEGER | NOT NULL | 同级排序 |
| `source_block_id` | TEXT | NULL, FK → material_blocks(id) | 溯源 |
| `summary_md` | TEXT | NULL | 该节内容摘要（用于检索） |

> 实现说明：`chapters` 与 `sections` 可共用一张 `outline_nodes` 表（`level` 区分 1/2），但初赛**建议分表**，因为二者的业务语义与查询模式不同，分表更利于代码可读性 —— 这是给"工程完整性"评分的。

### 2.4 `knowledge_points` — 知识点（核心表）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | |
| `section_id` | TEXT | NOT NULL, FK → sections(id) | **非空**，保证三级结构完整率 100%（A2-1） |
| `chapter_id` | TEXT | NOT NULL, FK → chapters(id) | 冗余字段，便于按章查询 |
| `material_id` | TEXT | NOT NULL, FK → materials(id) | 冗余字段 |
| `name` | TEXT | NOT NULL | 知识点名称，如「快速排序的分区思想」 |
| `summary_md` | TEXT | NOT NULL | 一句话讲清楚"这是什么" |
| `difficulty` | INTEGER | NOT NULL, CHECK BETWEEN 1 AND 5 | 难度 |
| `difficulty_reason` | TEXT | NULL | 为什么是这个难度（A2-3 的支撑） |
| `kp_type` | TEXT | NOT NULL DEFAULT 'concept' | `concept` / `skill` / `theorem` / `method` / `fact` |
| `source_material_id` | TEXT | NOT NULL, FK → materials(id) | **溯源必填** |
| `source_page` | INTEGER | NULL | 页码 |
| `source_block_id` | TEXT | NULL, FK → material_blocks(id) | 精确定位 |
| `source_quote` | TEXT | NOT NULL | 原文片段（A2-3 要求非空） |
| `confidence` | REAL | NULL | 抽取置信度 0–1 |
| `needs_review` | INTEGER | NOT NULL DEFAULT 0 | 待核实标记；缺失字段或低置信度置 1 |
| `seq` | INTEGER | NOT NULL | 节内顺序 |
| `created_at` | TEXT | NOT NULL | |

索引：`idx_kp_section(section_id, seq)`、`idx_kp_difficulty(difficulty)`、`idx_kp_review(needs_review)`
**唯一性**：`UNIQUE(section_id, name)` —— 同一节内不允许重名知识点。

> **不变量（数据库层校验 + 应用层双重保证）**：
> `source_quote` 为空的知识点视为抽取失败，**不得入库**，必须落到 `needs_review` 的待办列表中由人工处置。

### 2.5 `kp_prerequisites` — 前置依赖（DAG 的边）· ★本项目主创新点

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `kp_id` | TEXT | PK(复合), FK → knowledge_points(id) | 后置方（"要学会 A"） |
| `prereq_kp_id` | TEXT | PK(复合), FK → knowledge_points(id) | 前置方（"得先会 B"） |
| `relation_type` | TEXT | NOT NULL, CHECK IN ('hard','soft') | `hard`（不会就学不动）/ `soft`（会了更好懂） |
| `reason` | TEXT | **NOT NULL** | **依赖理由**（写清"不学懂前置会卡在哪"）。B1-5 要求 100% 完备 |
| `evidence_quote` | TEXT | NULL | 材料原文中支持这条依赖的片段（边级溯源，F2.11） |
| `source_channel` | TEXT | NOT NULL DEFAULT 'semantic' | `structure` / `semantic` / `both` —— 这条边由哪条线索产生 |
| `confidence` | REAL | NULL | 融合后的置信度 |
| `needs_review` | INTEGER | NOT NULL DEFAULT 0 | **结构-语义冲突标记**：语义判定与章节顺序矛盾时置 1（B1-4） |
| `pruned` | INTEGER | NOT NULL DEFAULT 0 | 是否因 DAG 环校验被剪除（被剪边保留记录，便于解释性，见 `innovation.md` §5.1 Step E） |
| `created_at` | TEXT | NOT NULL | |

约束：`CHECK (kp_id != prereq_kp_id)`（禁自环）

**服务层强制校验（写入前后各一次）**

```
写入前：对候选边集合做「预检」——加入后是否产生环？产生则不写入，标记 needs_review
写入后：全局拓扑排序校验
        有环 → 按 confidence 升序剪边（置 pruned=1，不物理删除）直到无环
             → 每剪一条边写 WARN 日志（哪条边 / 为什么 / 剪后图状态）
不变量：SELECT COUNT(*) FROM 图中环 = 0   （B1-2）
```

> **`pruned` 用软删除而非物理删除是刻意的**：被剪的边本身就是"系统发现并处理了矛盾"的证据，在质量报告页展示"本轮检出并剪除 N 条成环边"比只说"环数 0"更有说服力。

**边的稀疏性约束**：每个知识点**最多 3 条入边、最多 4 条出边**（在 P10 契约里已约束，服务层再做一次校验并拒绝超标写入）。理由：教学依赖关系应当是稀疏的，一个知识点依赖七八个前置在教学上不成立。

### 2.6 `kp_examples` — 典型例题

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | |
| `kp_id` | TEXT | NOT NULL, FK → knowledge_points(id) ON DELETE CASCADE | |
| `question_type` | TEXT | NOT NULL | `single_choice` / `multi_choice` / `fill_blank` / `short_answer` / `coding` / `true_false` / `other` |
| `stem_md` | TEXT | NOT NULL | 题干 |
| `options_json` | TEXT | NULL | 选项数组 `[{"key":"A","content":"..."}]` |
| `answer_md` | TEXT | NOT NULL | 答案 |
| `analysis_md` | TEXT | NULL | 解析 |
| `difficulty` | INTEGER | NULL, CHECK 1–5 | |
| `source_block_id` | TEXT | NULL, FK → material_blocks(id) | 溯源 |
| `source_page` | INTEGER | NULL | |
| `seq` | INTEGER | NOT NULL DEFAULT 0 | |

### 2.7 `kp_misconceptions` — 常见误区

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | |
| `kp_id` | TEXT | NOT NULL, FK → knowledge_points(id) ON DELETE CASCADE | |
| `description` | TEXT | NOT NULL | 误区是什么（学生的错误理解） |
| `cause` | TEXT | NULL | 为什么会这样错 |
| `remedy` | TEXT | NULL | 怎么纠正 —— **直接服务于答疑的提示语生成** |
| `trigger_pattern` | TEXT | NULL | 触发特征（学生这样问/这样答时命中该误区） |
| `source` | TEXT | NULL | `material` / `llm_inferred` / `human` —— **区分来源，LLM 推断的必须标注** |
| `confidence` | REAL | NULL | |

> 跨专业成员（教学背景）负责校验 `cause` / `remedy` / `trigger_pattern` 的真实性，并在 `source` 字段标记为 `human` 的条目上签字。

### 2.8 `kp_embeddings` — 向量

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `kp_id` | TEXT | PK, FK → knowledge_points(id) ON DELETE CASCADE | |
| `model` | TEXT | NOT NULL | embedding 模型标识 |
| `dim` | INTEGER | NOT NULL | 维度 |
| `vector` | BLOB | NOT NULL | `float32` 小端连续数组，`numpy.frombuffer` 直接读 |
| `text_hash` | TEXT | NOT NULL | 用于判断是否需要重新生成 |
| `created_at` | TEXT | NOT NULL | |

约束：`CHECK (dim = length(vector) / 4)`

### 2.9 `questions` — 从材料抽出的题目实体

与 `kp_examples` 的区别：`questions` 是**从材料里抽出来的原始题目**（可能还没归属到知识点）；`kp_examples` 是**归属于某知识点的典型例题**（是精选后的）。两者可有一对多关系。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | |
| `material_id` | TEXT | NOT NULL, FK → materials(id) | |
| `source_block_id` | TEXT | NULL, FK → material_blocks(id) | |
| `source_page` | INTEGER | NULL | |
| `question_type` | TEXT | NOT NULL | 同 kp_examples |
| `stem_md` | TEXT | NOT NULL | |
| `options_json` | TEXT | NULL | |
| `answer_md` | TEXT | NULL | 材料未给答案时为 NULL，并记 `answer_missing=1` |
| `answer_missing` | INTEGER | NOT NULL DEFAULT 0 | **对应 Stage 1 的"存疑处"** |
| `extraction_confidence` | REAL | NULL | |
| `pk_kp_id` | TEXT | NULL, FK → knowledge_points(id) | 归属知识点（Stage 2 回填） |

### 2.10 `qa_sessions` / `qa_turns` — 答疑

**qa_sessions**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `student_label` | TEXT | 演示用标签（不做登录，可空） |
| `material_scope` | TEXT | 答疑范围：JSON 数组，空数组=全部材料 |
| `created_at` / `updated_at` | TEXT | |

**qa_turns**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `session_id` | TEXT NOT NULL FK → qa_sessions(id) ON DELETE CASCADE | |
| `seq` | INTEGER NOT NULL | 轮次序号 |
| `role` | TEXT NOT NULL | `student` / `tutor` |
| `content_md` | TEXT NOT NULL | 消息内容 |
| `turn_type` | TEXT NULL | `probe` / `hint1` / `hint2` / `explain` / `confirm` / `refuse` / `student_answer` / `student_question` |
| `retrieved_kp_ids` | TEXT NULL | JSON 数组，本轮的检索依据 |
| `retrieved_block_ids` | TEXT NULL | JSON 数组，溯源到具体块 |
| `grounded` | INTEGER NOT NULL DEFAULT 0 | 是否基于材料（1/0）。**拒答轮次记为 0** |
| `diagnosis_json` | TEXT NULL | 三件产出，见 §3.2 |
| `llm_call_id` | TEXT NULL | 关联 llm_calls |
| `latency_ms` | INTEGER NULL | 本轮耗时 |
| `created_at` | TEXT NOT NULL | |

约束：`UNIQUE(session_id, seq)`
索引：`idx_turns_session(session_id, seq)`

### 2.11 `jobs` — 异步任务

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | job_id |
| `job_type` | TEXT NOT NULL | `parse` / `extract_knowledge` / `embed` / `reindex` |
| `target_id` | TEXT NULL | 关联的资源 id（如 material_id） |
| `status` | TEXT NOT NULL | `queued` / `running` / `done` / `failed` |
| `progress` | INTEGER NOT NULL DEFAULT 0 | 0–100 |
| `stage_detail` | TEXT NULL | 当前阶段的人类可读描述（前端直接展示，如"正在识别第 7/20 页"） |
| `result_json` | TEXT NULL | 结果摘要 |
| `error_message` | TEXT NULL | |
| `started_at` / `finished_at` / `created_at` | TEXT NULL | |

> `stage_detail` 是刻意设计的：进度必须**对用户可读**，这是用户体验 20% 里的具体得分点。

### 2.12 `llm_calls` — LLM 调用日志

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `caller` | TEXT NOT NULL | 调用来源，如 `parse.image_to_md` |
| `prompt_version` | TEXT NOT NULL | Prompt 契约版本号，如 `P2@v1` |
| `provider` / `model` | TEXT NOT NULL | |
| `temperature` | REAL | |
| `input_tokens` / `output_tokens` | INTEGER | |
| `latency_ms` | INTEGER | |
| `schema_valid` | INTEGER NULL | 结构化输出是否通过校验 |
| `retry_count` | INTEGER NOT NULL DEFAULT 0 | |
| `error_message` | TEXT NULL | |
| `created_at` | TEXT NOT NULL | |

> 不存完整 prompt 正文（隐私与体积），只存 hash 与版本号；调试期可通过 `DEBUG_LLM=1` 环境变量开启全量落盘。

---

## 3. JSON 结构约定

### 3.1 `materials.uncertain_notes` — 存疑处

```json
[
  {
    "kind": "low_confidence_ocr",
    "page": 7,
    "block_id": "blk_9f2a",
    "message": "第 7 页手写批注识别置信度 0.62，可能是『O(n log n)』",
    "severity": "medium"
  },
  {
    "kind": "missing_field",
    "page": 12,
    "message": "第 12 页第 3 题只有题干与选项，未找到答案",
    "severity": "high"
  }
]
```

`kind` 枚举：`low_confidence_ocr` / `missing_field` / `ambiguous_structure` / `asr_uncertain` / `unsupported_element`
`severity` 枚举：`low` / `medium` / `high`

### 3.2 `qa_turns.diagnosis_json` — 每轮三件产出

```json
{
  "knowledge_points": [
    { "kp_id": "kp_3c81", "name": "快速排序的分区思想", "difficulty": 3 }
  ],
  "stuck_at": {
    "step": "未能建立『分区后基准位即为最终位置』这一关键认识",
    "evidence_kp_id": "kp_3c81",
    "evidence_misconception_id": "mis_7d22",
    "evidence_quote": "原文第 9 页：分区完成后，基准元素左侧均不大于它，右侧均不小于它"
  },
  "next_practice": [
    { "kp_id": "kp_3c81", "task": "手写一次 Hoare 分区过程，标注每轮 i/j 指针位置" },
    { "kp_id": "kp_2f04", "task": "复习『比较排序下界』，理解为什么快排平均是 O(n log n)" }
  ],
  "confidence": 0.82
}
```

**字段非空是 A3-6 的验收对象**：`knowledge_points`、`stuck_at.step`、`next_practice` 三者缺一即为不合格。

### 3.3 `qa_turns.retrieved_kp_ids` / `retrieved_block_ids`

```json
{ "kp_ids": ["kp_3c81", "kp_2f04"], "scores": [0.91, 0.74], "retrieval_mode": "hybrid_rrf" }
```

---

## 4. 与验收指标的对应关系

| 验收项 | 依赖的数据约束 |
|---|---|
| A2-1 三级结构完整率 100% | `knowledge_points.section_id` / `chapter_id` NOT NULL |
| A2-3 溯源覆盖率 100% | `knowledge_points.source_quote` NOT NULL + 入库校验 |
| A2-4 DAG 环数量 0 | `kp_prerequisites` 批量写入后拓扑校验 + 回滚 |
| A2-7 同输入可复现 | `kp_embeddings.text_hash` + `knowledge_points` 重跑 diff 脚本 |
| A3-6 三件产出完整率 100% | `qa_turns.diagnosis_json` 字段非空校验 |
| A1-4 素材清单完整性 | `materials.parse_method` / `uncertain_notes` 非空 |

---

## 5. 迁移与种子数据

- 迁移：Alembic，`alembic upgrade head` 为启动前置步骤，容器 entrypoint 内自动执行。
- 种子：`backend/seeds/demo_materials/` 放置预置演示材料（A4-7），首次启动时可一键导入（`make seed`）。
- 备份：`scripts/backup.sh` 打包 `app.db` + `uploads/`，演示前执行一次。
