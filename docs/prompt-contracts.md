# Prompt 契约（Prompt Contracts）

> 上游文档：[`../SPEC.md`](../SPEC.md) §4.3
> 版本：v1.3 · 2026-09-17
> 实现位置：`backend/app/llm/prompts/`，每个契约一个文件，文件名即契约号

---

## 0. 通用约定

### 0.0 契约与 Provider 的对应（v1.1 新增，v1.2 / v1.3 更新）

> ⚠️ **v1.3 重要说明 —— 下表的 Provider 列「保留但不启用」**
>
> 赛事规则不允许作品调用第三方大模型 API（SPEC §4.8 / D-13）。**实际执行载体**改为：
>
> | 环节 | 执行载体 |
> |---|---|
> | P3 / P4 / P10（构建期抽取） | **LearnBuddy 平台**（主，赛事指定，2500 Credits）→ **本地 3B 量化模型**（兜底） |
> | P5 / P6 / P7 / P8（运行期） | **不调用模型** —— 检索用 FTS5 + NumPy，状态机为代码层，**回复由模板库 + 检索到的原文片段组装** |
> | P1 / P2（图片路径） | **PaddleOCR 本地解析** + 人工校验（不再使用视觉大模型） |
>
> **契约本身全部不变**：P1~P10 定义的是**输入输出结构与约束**，与执行载体无关。无论用 LearnBuddy、本地 3B 还是云端 API，抽取产出的 JSON 必须符合同一个 schema —— 这正是当初坚持做 Provider 抽象的回报。
>
> **附带好处**：本地 3B 的结构化输出遵循率较差，P10 契约里的"校验 + 重试 + 宽松解析兜底"设计现在承担更重要的角色。

| 契约 | Provider（保留不启用） | 备注 |
|---|---|---|
| P1 图文 → Markdown | ~~阿里云百炼 Qwen-VL~~ → **PaddleOCR** | 必须视觉能力；v1.3 改为本地 OCR |
| P2 题目字段抽取 | ~~Qwen-VL / DeepSeek~~ → **规则模板 + 人工校验** | 按输入形态分流 |
| P3 章节目录识别 | LearnBuddy（主）/ 本地 3B（兜底） | 纯文本短输入 |
| P4 逐节知识点抽取 | LearnBuddy（主）/ 本地 3B（兜底） | 调用量最大。**只抽节点，不抽边** |
| P5 查询改写 | **不调用模型**（规则 + 关键词扩展） | 运行期 |
| P6 重排与越界判定 | **不调用模型**（阈值 + 词面匹配，`is_out_of_scope` 由规则判定） | 运行期 |
| P7 苏格拉底式教练 | **模板库 + 检索片段组装** | 运行期；模板设计见 SPEC §4.8 |
| P8 卡点诊断 | **规则 + 数据槽位组装** | 运行期 |
| **P10 前置依赖边抽取** | LearnBuddy（主）/ 本地 3B（兜底） | **本项目主创新点所在**（SPEC §1.5 / `innovation.md` §5） |

> **v1.2 移除 P9（音频术语归一化）**：SPEC §6.1 已决定完全不做音频链路（D-08 反转），相关契约随之删除，不留孤立契约。

路由写在 `config/llm_routing.yaml`，**不得硬编码在业务代码里**（SPEC §4.3）。

### 0.1 版本化

每个 Prompt 模板文件头部必须声明：

```
# contract: P4
# version: v1
# caller: extract.section_to_kps
# provider: deepseek
# temperature: 0.0
# response_schema: P4.schema.json
```

调用时把 `prompt_version`（如 `P4@v1`）写入 `llm_calls` 表。**改一个字都要升版本号** —— 这是 A2-7「同输入可复现」与质量归因的底座。

### 0.2 三条通用铁律（每个 Prompt 的系统提示里都要有）

1. **不许编造**：只使用输入材料中出现的信息。材料里没有的，填 `null` 或写入 `uncertain` 字段，**绝不推测填充**。
2. **必须可溯源**：凡是断言知识点/答案，必须给出材料中的原文片段（`source_quote`），不得改写原意。
3. **只输出 JSON**：不输出解释性文字、不输出 Markdown 代码块围栏，直接输出符合 schema 的 JSON 对象。

### 0.3 解析与重试

- 统一 `temperature=0.0`，`seed` 固定（provider 支持时）。
- 结构化输出失败 → 第 1 次重试在消息末尾追加：
  ```
  上一次输出无法被解析，错误信息如下：
  {error}
  请严格按要求只输出合法 JSON。
  ```
- 第 2 次仍失败 → 落库 `status='failed'`，返回原始文本供人工处置，**记 WARN 日志，不静默吞掉**。

### 0.4 few-shot 策略

每个契约至少给 **1 个正例 + 1 个负例**。负例优先选"模型容易犯的错"（如：把材料里没有的答案补齐、把章节标题拆成知识点）。负例比正例更能约束行为。

---

## P1 · 图文 → Markdown

| 项 | 内容 |
|---|---|
| 用途 | PDF 扫描页 / 板书照片 / 题目图片 → 结构化 Markdown，保留版式语义 |
| 调用 | `parse.image_to_md`、`parse.pdf_scan_page_to_md` |
| 输入 | 一张或多张页面图片 |
| 输出 | Markdown 文本（不是 JSON） |

**系统提示要点**

```
你是教学材料的版面转写器。把图片中的内容完整转写为 Markdown。

规则：
1. 保留标题层级，用 #/##/### 表示；标题内容和编号保持原样，不要改写。
2. 表格转 Markdown 表格；公式用 $...$ 或 $$...$$（LaTeX）；代码用 ``` 围栏。
3. 题目保持原排版：题干、选项（A. B. C. D.）分行，答案与解析若页面上有则保留并标为「答案：」「解析：」。
4. 手写批注用 > 引用块表示，并标注「（手写）」。
5. 图片中看不清的内容写 [无法辨认]，不要猜测、不要补全。
6. 不要添加任何图片里没有的内容，不要写「以下是转写结果」之类的说明。
```

**为什么这样设计**：第 5 条是"显式不确定性"原则的落地 —— `[无法辨认]` 会成为下游 `uncertain_notes` 的数据源，最终在素材清单里展示给用户。宁可露出残缺，不要制造幻觉。

---

## P2 · 题目字段抽取

| 项 | 内容 |
|---|---|
| 用途 | 从 Markdown 或图片中抽取题目结构（对应 SPEC §5.1 F1.5） |
| 调用 | `parse.extract_questions` |
| 输入 | 一段 Markdown（通常来自 P1 的产出）或页面图片 |
| 输出 | JSON 数组 |

**输出 Schema**

```json
{
  "type": "object",
  "required": ["questions", "uncertain"],
  "properties": {
    "questions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["question_type", "stem_md", "source_quote"],
        "properties": {
          "question_type": { "enum": ["single_choice", "multi_choice", "fill_blank", "short_answer", "coding", "true_false", "other"] },
          "stem_md": { "type": "string" },
          "options": {
            "type": ["array", "null"],
            "items": { "type": "object", "required": ["key", "content"], "properties": { "key": { "type": "string" }, "content": { "type": "string" } } }
          },
          "answer_md": { "type": ["string", "null"] },
          "analysis_md": { "type": ["string", "null"] },
          "knowledge_hint": { "type": ["string", "null"], "description": "题干中显式提到的知识点名称，无则 null" },
          "source_quote": { "type": "string", "description": "材料中的原文片段，用于溯源" },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
        }
      }
    },
    "uncertain": {
      "type": "array",
      "description": "存疑项，对应 materials.uncertain_notes",
      "items": { "type": "object", "required": ["kind", "message", "severity"], "properties": {
        "kind": { "enum": ["low_confidence_ocr", "missing_field", "ambiguous_structure", "asr_uncertain", "unsupported_element"] },
        "message": { "type": "string" },
        "severity": { "enum": ["low", "medium", "high"] }
      }}
    }
  }
}
```

**关键约束（写进 Prompt）**

- 材料中**没有给出答案**时，`answer_md` 必须为 `null`，并追加一条 `uncertain` 记录 `kind="missing_field"`, `severity="high"`。**严禁自行解题补上答案。**
- 选项不完整（如只有 A、B 两个）时，`options` 按实际填写，并记 `uncertain`。

**负例（必须放在 Prompt 里）**

> ❌ 错误示范：材料只给了题干，输出 `"answer_md": "B"`
> 理由：这是模型自己算出来的答案，不是材料里的。必须在 `answer_md` 填 `null` 并记存疑。

---

## P3 · 章节目录识别

| 项 | 内容 |
|---|---|
| 用途 | 整份 Markdown → 章/节骨架（Stage 2 Step 1） |
| 调用 | `extract.outline` |
| 输入 | 素材的标题块序列（`block_type='heading'`，只投喂标题与层级，不投喂正文，省 token） |
| 输出 | 两级目录树 |

```json
{
  "type": "object",
  "required": ["chapters"],
  "properties": {
    "chapters": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["number", "title", "sections"],
        "properties": {
          "number": { "type": ["string", "null"] },
          "title": { "type": "string" },
          "source_block_id": { "type": ["string", "null"] },
          "sections": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["number", "title"],
              "properties": {
                "number": { "type": ["string", "null"] },
                "title": { "type": "string" },
                "source_block_id": { "type": ["string", "null"] }
              }
            }
          }
        }
      }
    },
    "structure_confidence": { "type": "number" },
    "notes": { "type": ["string", "null"] }
  }
}
```

**约束**

- 章节号与标题**保持材料原貌**，不做重命名、不做归一化。
- 若材料层级混乱（如只有章没有节），则把章作为节的下属、或生成单节包裹，并在 `notes` 说明；`structure_confidence` < 0.6 时前端提示"章节结构存疑，建议人工确认"。

---

## P4 · 逐节知识点抽取

| 项 | 内容 |
|---|---|
| 用途 | 一个"节"的正文 → 该节的知识点列表（Stage 2 Step 2，**主力 Prompt**） |
| 调用 | `extract.section_to_kps` |
| 输入 | 章节上下文（章名、节名）+ 该节的全部 `material_blocks`（带 block_id 与 page_no） |
| 输出 | 知识点数组，含五要素 |

```json
{
  "type": "object",
  "required": ["knowledge_points"],
  "properties": {
    "knowledge_points": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "summary_md", "difficulty", "source_block_id", "source_quote"],
        "properties": {
          "name": { "type": "string", "maxLength": 40 },
          "summary_md": { "type": "string" },
          "kp_type": { "enum": ["concept", "skill", "theorem", "method", "fact"] },
          "difficulty": { "type": "integer", "minimum": 1, "maximum": 5 },
          "difficulty_reason": { "type": "string" },
          "examples": {
            "type": "array",
            "maxItems": 3,
            "items": {
              "type": "object",
              "required": ["question_type", "stem_md", "answer_md"],
              "properties": {
                "question_type": { "enum": ["single_choice", "multi_choice", "fill_blank", "short_answer", "coding", "true_false", "other"] },
                "stem_md": { "type": "string" },
                "options": { "type": ["array", "null"], "items": { "type": "object" } },
                "answer_md": { "type": "string" },
                "analysis_md": { "type": ["string", "null"] },
                "source_block_id": { "type": ["string", "null"] }
              }
            }
          },
          "misconceptions": {
            "type": "array",
            "maxItems": 3,
            "items": {
              "type": "object",
              "required": ["description"],
              "properties": {
                "description": { "type": "string" },
                "cause": { "type": ["string", "null"] },
                "remedy": { "type": ["string", "null"] },
                "trigger_pattern": { "type": ["string", "null"], "description": "学生什么样的说法/答法表示踩中了这个误区，用于答疑时匹配" }
              }
            }
          },
          "source_block_id": { "type": "string" },
          "source_page": { "type": ["integer", "null"] },
          "source_quote": { "type": "string", "description": "块中的原文片段，不得改写" },
          "confidence": { "type": "number" }
        }
      }
    },
    "coverage_note": { "type": ["string", "null"], "description": "本节有哪些内容未被抽成知识点、原因是什么" }
  }
}
```

**关键约束（写进 Prompt）**

1. **粒度规则**：一个知识点 = 一个可被单独考查的能力或认识。**反面示例**：把"3.2 交换排序"这个标题本身当成知识点（那是节）；把一整章拆成一个知识点（太粗）。正面：`快速排序的分区思想`、`冒泡排序的提前退出优化`。
2. **数量约束**：每节 3–12 个知识点。少于 3 个说明粒度太粗，多于 12 个说明在拆标题。
3. **不输出前置依赖**：边由 **P10 单独产出**。P4 即使"顺手想到"了依赖关系，也**不要写进输出** —— 两类信息混在一次调用里会相互污染（见 P10 章节的说明）。**v1.3 从 schema 中移除了 `prerequisites` 字段。**
4. **例题必须有答案**：`answer_md` 若材料未给，则该例题**不要抽出来**（不要自己解题）。这条通过"宁缺毋滥"避免幻觉。
5. **误区必须具体**：`description` 要描述"学生会怎么错"，不能写"容易混淆"。要写"认为分区后基准元素还会移动"。
6. `misconceptions.source` 由系统置为 `llm_inferred`，人工校验后改 `human`。

**负例（必须放在 Prompt 里）**

> ❌ 输入是"3.2 交换排序"这一节的标题行，输出知识点 `{name: "交换排序", difficulty: 2}`。
> 理由：这是节标题不是知识点。"交换排序"下应抽出 `冒泡排序的基本思想`、`冒泡的提前退出优化`、`快速排序的分区思想`、`快排的递归实现` 等。

---

## P5 · 查询改写与扩展

| 项 | 内容 |
|---|---|
| 用途 | 学生的口语化提问 → 检索友好的查询（Stage 3 检索前置） |
| 调用 | `retrieve.rewrite_query` |
| 输入 | 学生原问题 + 最近 3 轮对话 |
| 输出 | 多路查询 + 意图 |

```json
{
  "type": "object",
  "required": ["rewritten_queries", "intent"],
  "properties": {
    "rewritten_queries": { "type": "array", "items": { "type": "string" }, "minItems": 1, "maxItems": 4,
      "description": "把口语化问题改写为术语化查询；同时给 1-2 个同义/上位表述以提升召回" },
    "intent": { "enum": ["concept_explain", "why_choice", "debug_understanding", "exercise_help", "chitchat", "other"] },
    "mentioned_terms": { "type": "array", "items": { "type": "string" }, "description": "问题中提到的术语原文" }
  }
}
```

**用途说明**：学生说"这题为啥不用冒泡" → 改写为 `["快速排序 与 冒泡排序 复杂度对比", "比较排序 时间复杂度 下界", "冒泡排序 适用场景"]`。

---

## P6 · 检索重排与越界判定

| 项 | 内容 |
|---|---|
| 用途 | 对混合召回的 top-8 做相关性判定 + 判定是否为材料外问题（Stage 3 的保命环节） |
| 调用 | `retrieve.rerank_and_judge` |
| 输入 | 学生问题 + 8 个候选知识点（含名称、摘要、溯源原文片段）；**注意：只给知识点，不给材料全文** |
| 输出 | 排序后的相关知识点 + 越界标记 |

```json
{
  "type": "object",
  "required": ["is_out_of_scope", "relevant"],
  "properties": {
    "is_out_of_scope": { "type": "boolean",
      "description": "候选知识点能否真正支撑回答该问题。若都不相关，或问题问的是候选之外的领域，则为 true" },
    "relevant": {
      "type": "array", "maxItems": 4,
      "items": {
        "type": "object",
        "required": ["kp_id", "relevance"],
        "properties": {
          "kp_id": { "type": "string" },
          "relevance": { "type": "number", "minimum": 0, "maximum": 1 },
          "why": { "type": "string" }
        }
      }
    },
    "closest_alternatives": {
      "type": "array", "maxItems": 3,
      "description": "越界时给用户的替代入口：材料里最接近的 2-3 个知识点",
      "items": { "type": "object", "required": ["kp_id", "name"], "properties": { "kp_id": { "type": "string" }, "name": { "type": "string" } } }
    },
    "out_of_scope_reason": { "type": ["string", "null"] }
  }
}
```

**这是"幻觉率必须为 0"（A3-3）的关键闸门。** Prompt 里必须写明：

```
你不负责回答学生的问题，只负责判断"上面列出的知识点里，有没有能真正支撑回答这个问题的"。
若没有，或问题涉及候选以外的知识领域，必须把 is_out_of_scope 设为 true。
宁可判错成 true（保守拒答），也不要判成 false 让下游编造答案。
```

> 保守偏置是刻意的：拒答只是体验略差，编造答案会击穿整个产品的信任基础。

---

## P7 · 苏格拉底式教练（状态机驱动）

| 项 | 内容 |
|---|---|
| 用途 | 生成 S1 PROBE / S2 HINT1 / S3 HINT2 / S4 EXPLAIN / CONFIRM 的回复（SPEC §5.3） |
| 调用 | `tutor.respond` |
| 输入 | 学生问题 + 命中知识点详情（含误区、例题）+ **本轮状态** + 最近 3 轮对话 |
| 输出 | 纯文本回复（流式）+ 结构化的对话元信息 |

**分支行为表（这是 Prompt 的核心，按 `turn_type` 分支）**

| turn_type | 必须做 | 禁止做 |
|---|---|---|
| `probe` | 反问一个**能暴露学生理解偏差**的问题，指向命中知识点与已知误区 | **禁止给答案、禁止给解题步骤、禁止暗示正确选项** |
| `hint1` | 给一个方向性提示（指向该知识点的关键概念或原文片段） | 禁止给出完整解法 |
| `hint2` | 给一个强提示（缩小到具体步骤，可引用原文片段） | 禁止写出最终结论 |
| `explain` | 完整、分步讲解，明确引用材料原文；结尾给一个自查问题 | 不要道歉、不要过度铺垫 |
| `confirm` | 确认学生说对了，补充一个边角知识点巩固 | 不要重复已讲内容 |

**统一输出要求**

- 语气：对学生用第二人称，专业但不端着。不用"同学你好呀"这类浮夸开场，也不用"综上所述"这类论文腔。
- 每次回复 **150–400 字**，不写长篇大论。苏格拉底式引导的要义是简短。
- `probe` / `hint` 类回复**必须带问号**（要学生回应），且一次只问一个问题。
- 只能使用输入中给出的知识点信息。**输入里没有的，不许出现在回复里。**

**结构化元信息（与文本一并返回）**

```json
{
  "type": "object",
  "required": ["turn_type", "used_kp_ids"],
  "properties": {
    "turn_type": { "enum": ["probe", "hint1", "hint2", "explain", "confirm", "refuse"] },
    "used_kp_ids": { "type": "array", "items": { "type": "string" } },
    "used_block_ids": { "type": "array", "items": { "type": "string" } },
    "student_answer_state": { "enum": ["correct", "partially_correct", "incorrect", "no_attempt", "not_an_answer"] },
    "cited_quote": { "type": ["string", "null"], "description": "回复中引用的原文片段，必须逐字来自输入" }
  }
}
```

> `student_answer_state` 是驱动状态机前进/降级的输入。判定规则写死在 Prompt 里，**不额外用一次 LLM 调用**，省成本也省延迟。

**兜底降级（代码层强制，不依赖 LLM 自觉）**

```
若 consecutive_failures >= 2 且 state 仍在 probe/hint1/hint2 区间：
    强制改写 state = explain，忽略 LLM 建议的 turn_type
若无命中知识点（is_out_of_scope）：
    强制走 refuse 模板，不调用 LLM 生成正文
```

---

## P8 · 卡点诊断汇总

| 项 | 内容 |
|---|---|
| 用途 | 生成本轮三件产出（SPEC R5，对应 `qa_turns.diagnosis_json`） |
| 调用 | `tutor.diagnose` |
| 输入 | 本轮问答对 + 命中知识点 + 命中误区 + 该知识点的前置依赖列表 |
| 输出 | JSON |

```json
{
  "type": "object",
  "required": ["knowledge_points", "stuck_at", "next_practice"],
  "properties": {
    "knowledge_points": { "type": "array", "minItems": 1,
      "items": { "type": "object", "required": ["kp_id", "name"], "properties": {
        "kp_id": { "type": "string" }, "name": { "type": "string" }, "difficulty": { "type": "integer" } } } },
    "stuck_at": {
      "type": "object",
      "required": ["step"],
      "properties": {
        "step": { "type": "string", "description": "学生具体卡在认知的哪一步，一句话说清" },
        "evidence_kp_id": { "type": ["string", "null"] },
        "evidence_misconception_id": { "type": ["string", "null"], "description": "若命中 kp_misconceptions 中某条，填其 id" },
        "evidence_quote": { "type": ["string", "null"], "description": "材料原文中对应的那句话" },
        "kind": { "enum": ["prerequisite_gap", "misconception", "concept_confusion", "procedure_error", "insufficient_reading"] }
      }
    },
    "next_practice": { "type": "array", "minItems": 1, "maxItems": 3,
      "items": { "type": "object", "required": ["kp_id", "task"], "properties": {
        "kp_id": { "type": "string" }, "task": { "type": "string", "description": "可执行的具体练习动作，不是『多复习』这类空话" } } } },
    "confidence": { "type": "number" }
  }
}
```

**质量要求**

- `stuck_at.kind` 优先选 `prerequisite_gap`（如果卡点其实是因为前置没掌握）—— 这是本产品相对普通问答的**核心增值**：不只回答这一题，还诊断出"你该回头补哪一节"。
- `next_practice.task` 必须是**可执行动作**：✅「手写一次 Hoare 分区过程，标注每轮 i/j 指针位置」；❌「加强练习」「多复习快排」。
- `stuck_at.step` 若无法判定，填「暂未能定位具体卡点」并把 `confidence` 设为 < 0.5，不得编造。

---

## P10 · 前置依赖边抽取（v1.2 新增 · ★主创新点）

| 项 | 内容 |
|---|---|
| 用途 | 判定知识点之间的前置依赖关系，产出 `hard`/`soft` 语义 + `reason`（SPEC §5.2 Step 4b，见 `innovation.md` §5.1） |
| 调用 | `extract.prerequisite_edges` |
| Provider | DeepSeek |
| 输入 | ① 知识点清单（名称 + 一句话摘要 + 所属章/节 + `seq`）；② **只投喂【跨节 / 跨章】的候选对**，不投喂全文 |
| 输出 | 前置边数组 |

**为什么单独一个契约、而不是塞进 P4**

P4 只抽节点、不抽边（SPEC §5.2 Step 2 明确要求）。原因：一旦在同一次调用里既产出节点又产出边，模型会为了让边成立而把节点切得变形，节点粒度也会反过来污染边的判定。**分两次调用是保证节点质量的前提**，多花的 token 远小于返工成本。

**候选对裁剪（工程优化，避免 O(n²)）**

```
同节内        → 直接用 seq 顺序生成「弱结构边」，不调模型
相邻节之间    → 全量判定
跨章          → ★必须在两章节点【都已入库】后再跑一轮判定，候选集覆盖两章
```

> **v1.3 修正**：原写法是"章与章之间只判定节级聚合依赖，不下沉到知识点对"。**冒烟测试证明这个裁剪会丢真边** —— 例如"拥塞窗口 ← 依赖 → 第 5 章的流量控制/通告窗口"是一条明确的知识点级跨章硬依赖（原文：*the congestion window is congestion control's counterpart to flow control's advertised window*）。改为**跨章单独跑一轮**，代价可控且不丢边。

**输出 Schema**

```json
{
  "type": "object",
  "required": ["edges"],
  "properties": {
    "edges": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["prereq_name", "dependent_name", "relation_type", "reason", "confidence"],
        "properties": {
          "prereq_name": { "type": "string", "description": "前置知识点名称，必须逐字来自输入清单" },
          "dependent_name": { "type": "string", "description": "后置知识点（要学会的那个），同样逐字来自清单" },
          "relation_type": { "enum": ["hard", "soft"] },
          "reason": { "type": "string", "description": "必填。写清『不学懂前置会在哪里卡住』" },
          "evidence": { "type": ["string", "null"], "description": "材料原文中支持这条依赖的片段" },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
        }
      }
    },
    "no_edge_reason": { "type": ["string", "null"], "description": "本批候选对中未找到任何依赖时的说明" },
    "deferred_edges": {
      "type": "array",
      "description": "v1.3 新增。需要但【本次无法产出】的边 —— 典型场景是跨章依赖，而另一章的节点尚未入库（此时受『名称必须逐字来自输入清单』约束，本不该输出）。记录在此以便补跑，避免丢失线索。",
      "items": {
        "type": "object",
        "required": ["reason", "deferred_because"],
        "properties": {
          "prereq_name": { "type": ["string", "null"] },
          "dependent_name": { "type": ["string", "null"] },
          "relation_type": { "enum": ["hard", "soft", null] },
          "reason": { "type": "string" },
          "deferred_because": { "type": "string" },
          "action": { "type": ["string", "null"], "description": "补跑条件，如『待第 5 章节点入库后用覆盖两章的候选集重跑』" }
        }
      }
    }
  }
}
```

**关键约束（写进 Prompt）**

1. **名称必须逐字来自输入清单**：不得造新知识点名、不得改写名称。找不到对应节点就不输出这条边。
2. **`hard` / `soft` 的判定标准写死**：
   - `hard`：不掌握前置，后置**根本无法理解**（例：不懂「子网掩码的作用」→ 无法做「子网划分」）
   - `soft`：不掌握前置也能学，但会更吃力（例：熟悉「二进制换算」会让「CIDR 计算」更顺）
3. **`reason` 必须具体**：要写"不学懂 A 就看不懂 B 里的哪一步"。**反例**：写"二者相关""属于同一章"。
4. **数量约束**：每个知识点**最多 3 条入边、最多 4 条出边**。超出说明判定过松 —— 教学依赖关系应当是稀疏的，**一个知识点依赖七八个前置在教学上不成立**。
5. **宁可少，不可乱**：不确定是否构成前置时**不要输出**，而不是给一条 `soft` 兜底。**低质量的边比没有边更糟**，它会污染学习路径与卡点回溯。
6. **禁止双向冗余**：不要同时输出"A→B"和"B→A"。单向即可。

**负例（必须放在 Prompt 里）**

> ❌ 输入清单含「IP 数据报格式」与「ARP 协议」（同属网络层）。
> 错误输出：`{"prereq_name":"ARP 协议","dependent_name":"IP 数据报格式","relation_type":"soft","reason":"二者都属于网络层协议"}`
> 理由：① `reason` 写的是**相关性**不是**依赖性**；② 二者是并列关系，不存在前置依赖。**正确答案是：这条边不该输出。**

---

## 9. Prompt 与验收指标的对应

| 契约 | 支撑的验收项 |
|---|---|
| P1 | A1-2、A1-6（页码锚点靠调用侧拼装，但内容完整性靠 P1） |
| P2 | A1-3（关键字段抽取准确率）、A1-4（存疑处） |
| P3 | A2-1（三级结构完整） |
| P4 | A2-2、A2-3、A2-5、A2-7 |
| P5 | A3-1（检索命中率） |
| P6 | A3-2（越界拒答）、**A3-3（幻觉率 0）** |
| P7 | A3-4（首轮不给答案）、A3-5（连错降级） |
| P8 | A3-6（三件产出完整率） |
| P10 | **B1-1 / B1-4 / B1-5**（前置边抽检合理率、结构-语义冲突检出、`reason` 完备率）—— 本项目主创新点的核心举证 |
| 全部 | A4-1（`llm_calls` 日志支撑质量归因与单测 mock） |

---

## 10. 维护规则

1. 每个契约文件与一个 `*.schema.json`（JSON Schema，供代码层校验）配对，二者必须同步修改。
2. Prompt 变更必须跑「回归集」：`backend/tests/regression/` 下的 20 条固定输入，比对输出是否符合预期（无需完全一致，但关键字段必须一致）。
3. 每次变更把 `prompt_version` 写入 [SPEC.md §12](../SPEC.md#12-变更日志) 或本文件末尾的版本表。

### 版本表

| 契约 | 版本 | 日期 | 变更 |
|---|---|---|---|
| P1–P8 | v1 | 2026-09-16 | 初版建立 |
| P9 | v1 | 2026-09-16 | 新增：音频术语归一化（配合 SPEC v1.1 音频窄通道决策 D-08） |
| 全部 | v1.1 | 2026-09-16 | §0.0 新增「契约 → Provider」路由表；模板头部新增 `# provider` 声明 |
| **P10** | **v1** | **2026-09-17** | **新增：前置依赖边抽取（SPEC v1.2 主创新点 §1.5 / D-12）** |
| **P9** | — | **2026-09-17** | **删除：SPEC v1.2 决定完全不做音频链路，契约随之移除** |
| 全部 | v1.2 | 2026-09-17 | 路由表更新；P4 备注补充"只抽节点不抽边" |
| **全部** | **v1.3** | **2026-09-17** | Provider 列改为「保留不启用」，新增执行载体说明表（LearnBuddy 主 / 本地 3B 兜底 / PaddleOCR / 运行期不调用模型） |
| **P4** | **v1.3** | **2026-09-17** | **移除 `prerequisites` 字段** —— 与 SPEC §5.2「P4 只抽节点不抽边」对齐。**冒烟测试发现的规格漂移** |
| **P10** | **v1.3** | **2026-09-17** | **新增 `deferred_edges` 字段**；**候选对裁剪修正**：跨章改为「两章节点都入库后单独跑一轮」，原"只判定节级聚合"会丢真边（冒烟测试已实证） |

> 上述 P4 / P10 的改动均由 **2026-09-17 的抽取通道冒烟测试**发现并驱动，详见 [`extraction-channel.md`](extraction-channel.md) §6。**契约写在文档里不会出错，跑一遍真实材料才会。**
