# 抽取通道规格与操作规程

> 上游文档：[`../SPEC.md`](../SPEC.md) §4.8（无第三方 API 约束下的执行方案）
> 版本：v1.0 · 2026-09-17
> 状态：**主通道已冒烟验证通过**（见 §5）

---

## 1. 通道定位

赛事规则确认：**产品不得调用非 LearnBuddy 的模型**。因此抽取环节不在产品运行时发生，而是在**构建期**由三条路径完成，结果统一落库。

```
产物：SQLite 中的 chapters / sections / knowledge_points / kp_prerequisites
        ↑
   ┌────┴─────────────────────────────────────────────┐
   │ 主通道：LearnBuddy 平台（赛事指定，2500 Credits） │  ← 本次已冒烟验证
   │ 兜底通道：本地 3B 量化模型（Ollama）              │
   │ 兜底通道：人工校验工作台（needs_review 工作流）   │
   └──────────────────────────────────────────────────┘
```

**三者的关系不是"三选一"，而是"主 + 兜底 + 收口"**：主通道产出初稿 → 本地模型补充遗漏 → 人工在工作台上确认/修正。任何一条产出都必须通过同一套 schema 校验（P1~P10 契约不变）。

---

## 2. 主通道操作规程（LearnBuddy）

**核心原则：一次只跑一个"节"，不要试图一次抽完整章。**

| 步骤 | 动作 | 产出 | 校验 |
|---|---|---|---|
| 1 | 把材料按"节"切好，每节整理为带 `block_id` 的 Markdown 片段 | 节级输入片段 | 每节预期 3–12 个知识点 |
| 2 | 用 **P3 契约** 对整份材料的标题块跑一次，得到章/节骨架 | `P3-outline.json` | 章节号与标题保持材料原貌 |
| 3 | 用 **P4 契约** 逐节跑，得到该节的知识点（只抽节点、不抽边） | `P4-output.json` | 五要素齐全、`source_quote` 非空 |
| 4 | 全部节点入库后，用 **P10 契约** 对**跨节 / 跨章**候选对跑一轮，得到前置边 | `P10-output.json` | `reason` 非空、稀疏性约束 |
| 5 | schema 校验 + 归一 + 去重；不通过的进 `needs_review` | 待校验清单 | 校验失败率 < 20% |
| 6 | 写库 → DAG 拓扑校验（环数必须为 0）→ 生成 embedding → 更新 FTS5 | 可查询的知识库 | B1-2 / B1-5 |

**关键纪律**

- **P4 与 P10 必须分两次跑**（SPEC §5.2 Step 2）。同一次调用里既产出节点又产出边，会让模型为了"让边成立"而把节点切变形。
- **P3 的产出要人工确认一次**。"节"的粒度以"**能抽出 3–12 个知识点**"为准，而不是照搬标题层级（本次冒烟已验证这个规则的必要性，见 §6 问题 1）。
- **每跑完一节就把结果落盘**，不要攒着。LearnBuddy 的对话上下文会累积，攒着跑容易串味。

---

## 3. 结果校验与落库

```python
# 伪代码：抽取结果的入库流水线
def ingest(raw_json: dict, contract: str) -> IngestResult:
    schema = load_schema(contract)              # P4.schema.json / P10.schema.json
    if not validate(raw_json, schema):
        retry_once_with_error_feedback()        # 最多重试 1 次（构建期人工可介入）
        if still_invalid:
            return IngestResult(status="failed", raw=raw_json)   # ★ 绝不静默丢弃

    # P4：知识点
    for kp in raw_json["knowledge_points"]:
        if not kp.get("source_quote"):
            mark_needs_review(kp, reason="missing_grounding")    # A2-3 / B1-5
        upsert_knowledge_point(kp)

    # P10：前置边
    for edge in raw_json["edges"]:
        if not edge.get("reason"):
            mark_needs_review(edge, reason="missing_reason")     # B1-5
        if violates_sparsity(edge):                              # ≤3 入边 / ≤4 出边
            raise IngestError("sparsity_violation")
        upsert_prerequisite(edge)

    detect_cycles_and_prune()                   # B1-2：有环则按 confidence 升序剪边，软删除
```

**落库不变量（写库前后各校验一次）**

- `knowledge_points.source_quote` 非空（否则 `needs_review=1`）
- `kp_prerequisites.reason` 非空
- 每节点入边 ≤ 3、出边 ≤ 4
- 全图环数 = 0

---

## 4. 兜底通道：本地 3B

`Ollama + qwen2.5:3b-instruct`（Q4，约 2GB，8GB 内存可跑）。

| 用途 | 说明 |
|---|---|
| 调 Prompt 阶段的试验 | **不计 LearnBuddy Credits**，这是成本纪律 C1 |
| 补充遗漏 | 主通道漏抽的节点/边，用本地模型跑一遍对照 |
| 演示前临时补抽 | 时间紧时不必等人工搬运 |

**已知短板**：结构化输出遵循率差 → 依赖"校验 + 重试 + 宽松解析兜底"（P10 契约已设计）。**不要用它做最终产出，只做对照与补充。**

---

## 5. 冒烟测试记录（2026-09-17）

### 5.1 输入

| 项 | 内容 |
|---|---|
| 材料 | **Computer Networks: A Systems Approach**（Peterson & Davie, 6th Ed.） |
| 出处 | `book.systemsapproach.org/congestion/tcpcc.html` |
| 许可 | **CC BY 4.0**（可改编、需署名）—— 见 `materials-and-licenses.md` |
| 范围 | Chapter 6 Congestion Control → 6.3 TCP Congestion Control（含 4 个子节） |

### 5.2 执行

| 契约 | 结果 | 明细 |
|---|---|---|
| **P3 章节目录识别** | ✅ 通过 | 识别出 1 章 + 3 节（6.3.1 / 6.3.2 / 6.3.3） |
| **P4 逐节知识点抽取** | ✅ 通过 | 抽出 **9 个知识点**，全部带 `source_quote`（逐字来自原文）、难度与难度理由 |
| **P10 前置依赖边抽取** | ✅ 通过 | 抽出 **10 条边**（8 hard + 2 soft），全部带 `reason`；稀疏性合规；**环数 = 0** |

产出文件见 [`../samples/channel-smoke-test/`](../samples/channel-smoke-test/)。

### 5.3 抽出的知识点（节 6.3.1 / 6.3.2 / 6.3.3）

| # | 知识点 | 类型 | 难度 | 所在节 | 原文溯源 |
|---|---|---|---|---|---|
| 1 | 拥塞窗口 CongestionWindow | concept | 2 | 6.3.1 | ✅ |
| 2 | 拥塞窗口与通告窗口取小 | method | 3 | 6.3.1 | ✅ |
| 3 | 加性增 Additive Increase | method | 3 | 6.3.1 | ✅ |
| 4 | 乘性减 Multiplicative Decrease | method | 2 | 6.3.1 | ✅ |
| 5 | AIMD 的不对称性与稳定性 | theorem | 4 | 6.3.1 | ✅ |
| 6 | 慢启动 Slow Start | method | 3 | 6.3.2 | ✅ |
| 7 | 慢启动为何"慢" | concept | 4 | 6.3.2 | ✅ |
| 8 | 快速重传 Fast Retransmit | method | 3 | 6.3.3 | ✅ |
| 9 | 快速恢复 Fast Recovery | method | 4 | 6.3.3 | ✅ |

### 5.4 抽出的前置依赖边

```
拥塞窗口 ──hard──> 乘性减 ──hard──> AIMD 不对称性
    │                  │                  ▲
    │                  └──soft──> 快速恢复 │
    │                                    │
    ├──hard──> 加性增 ──hard─────────────┘
    │            │
    │            ├──soft──> 慢启动 ──hard──> 慢启动为何"慢"
    │            │            │
    │            └──hard──> 快速恢复 ──hard─┘
    │
    └──hard──> 慢启动
```

- **环数 = 0** ✅（B1-2 达标）
- **`reason` 完备率 = 100%** ✅（B1-5 达标）
- 入边最大值 3（快速恢复），出边最大值 3（拥塞窗口 / 加性增）—— 均在稀疏性约束内 ✅

### 5.5 抽出的典型例题与常见误区（摘录）

**误区示例（有原文支撑，非臆造）**

| 知识点 | 误区 | 依据原文 |
|---|---|---|
| 慢启动 | 从字面理解"慢启动 = 增长很慢" | 原文本身写作 "ironically called *slow start*"，并明确 "its exponential growth is faster than linear growth" |
| 快速重传 | 认为快速重传取代了超时重传 | 原文明确 "does not replace regular timeouts; it just enhances that facility" |
| AIMD 不对称性 | 把方向搞反，以为"升得快、降得慢" | 原文 "willing to reduce ... at a much faster rate than it is willing to increase" |
| 拥塞窗口与通告窗口 | 把二者混为一谈 | 原文 "congestion control's counterpart to flow control's advertised window" |

---

## 6. 冒烟测试发现的 5 个问题（均已写入 SPEC）

### 问题 1 · "节"的粒度不能照搬标题层级

Peterson & Davie 的 6.3 下有 6.3.1 / 6.3.2 / 6.3.3 三级标题，而我们的三级结构只有「章—节—知识点」。若把 6.3 当"节"，则一节有 9 个知识点、跨 4 个子节，知识点归属会含糊。

**结论**：**"节"的粒度以"能抽出 3–12 个知识点"为准**，而非照搬标题层级。本例中 6.3.1 / 6.3.2 / 6.3.3 各作为一个"节"。已写入 §2 操作规程。

### 问题 2 · 开放教材的网页版**没有页码**

`source_page` 只能为 NULL。所幸我们的数据模型早已规定 `source_quote` 为 NOT NULL、`source_page` 可空 —— **溯源以原文片段为准，页码只是增强**。

**结论**：网页版材料用「章节号 + 块序号」作锚点，前端溯源卡片降级显示为「§6.3.2 · 第 4 段」。**如需页码，下载 PDF 版**（Peterson & Davie 提供 PDF/EPUB）。已加入材料清单要求。

### 问题 3 · 中英文教材的术语体系不一致 ⚠️

| 中文教材常见术语 | 本英文教材的对应表述 |
|---|---|
| 慢开始 / 慢启动 | Slow Start ✅ 一致 |
| **拥塞避免** | **无此独立概念**，原文用 "additive increase" 表述该阶段 |
| 快重传 / 快恢复 | Fast Retransmit / Fast Recovery ✅ 一致 |

**这直接影响 E-1 金标准评测集**：以中文教材为基准标注知识点，再去比对英文材料的抽取结果，会**凭空产生"漏抽"的假阴性**。

**结论**：**E-1 金标准必须以"实际使用的那份材料"为基准**，不能混用。若同时用中英文材料，须分别建立基准，或明确以一门为准。**已登记为待办（V-17）。**

### 问题 4 · 跨章边无法在单章输入内产出

原文有一句话：*"The congestion window is congestion control's counterpart to flow control's advertised window."* —— 这是一条清晰的**跨章硬依赖**（拥塞窗口 ← 依赖 → 第 5 章的流量控制/通告窗口）。

但 P10 契约硬性要求"名称必须逐字来自输入清单"，而第 5 章的知识点不在本次输入里，**所以这条边正确地没有被输出**。

**结论**：跨章边必须在**全章节点都抽完入库后**单独跑一轮判定，且候选输入要覆盖两章。已写入 §2 步骤 4 与 `prompt-contracts.md` P10 的候选对裁剪规则。

### 问题 5 · 本次未触发"结构-语义冲突"（符合预期）

结构线索（6.3.1 → 6.3.2 → 6.3.3）与语义判定的方向**完全一致**，`needs_review` 冲突标记未被触发。

**这不是缺陷，反而是一个发现**：**结构清晰的正式教材上，章节顺序是可靠的方向先验** —— 所以冲突本来就应当罕见。这也意味着 **B1-4「冲突检出率 100%」必须用构造的对抗性输入来验证**，不能指望在真实材料上自然出现。已按此调整 B1-4 的验证方式（原设计即为"构造 3 组对抗性输入"，现在有了明确依据）。

### 问题 6 · 冒烟测试暴露了 Prompt 契约与 SPEC 的一处**不一致**（已修正）

`prompt-contracts.md` 的 **P4 schema 里仍带着 `prerequisites` 字段**，但 SPEC §5.2 Step 2 已明确「P4 **只抽节点、不抽边**」，边的产出归 P10（§5.2 Step 4b，且 P10 章节里专门写了"为什么单独一个契约"）。

这是一处规格漂移 —— 若照旧 schema 实现，会出现"边有两个来源"的隐患。

**修正**：已从 P4 schema 移除 `prerequisites`；同时给 P10 schema **新增 `deferred_edges` 字段**（用于记录"需要但本次无法产出的边"，见问题 4 的跨章边场景）。

> **这正是"打通抽取通道"这件事的价值**：契约写在文档里不会出错，一旦拿真实材料跑一遍，不一致就露出来了。**这个环节省下的返工远大于它花掉的时间。**

---

## 7. 与验收指标的对应

| 指标 | 本次冒烟的贡献 |
|---|---|
| A2-1 三级结构完整率 100% | P3 + P4 产出可直接映射到 章/节/知识点 三级 |
| A2-3 溯源覆盖率 100% | 9/9 个知识点带逐字原文片段 |
| A2-5 知识点命名与归属正确率 | 本次 9 个均为人工可判定，可作抽检样本 |
| B1-2 DAG 环数量 = 0 | ✅ 实测 0 |
| B1-3 学习路径拓扑有序 | 10 条边构成清晰 DAG，可生成路径 |
| B1-5 边 `reason` 完备率 100% | ✅ 实测 100% |
| B1-4 结构-语义冲突检出 | 本次未触发 → 按 §6 问题 5 的结论改用构造输入验证 |

> **主通道已验证可用。** 下一步是把同一套流程在**中文材料**上跑一遍 —— 因为赛题场景与评委都是中文语境，最终 Demo 必须用中文材料。已登记为 D2 任务。
