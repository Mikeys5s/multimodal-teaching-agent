# 创新点调研与改进方案

> 上游文档：[`../SPEC.md`](../SPEC.md) §1.5
> 版本：v1.0 · 2026-09-17
> 调研范围：GitHub 开源项目 + 学术文献
> 结论一句话：**我们改进的不是"做一个 AI 家教"，而是"把知识图谱从检索用的实体关系图，改造成教学用的前置依赖图"**

---

## 1. 调研方法

1. 先找同赛题的头部项目（教学智能体 / AI 家教 / 教材解析），看它们已经做到了什么；
2. 再找"前置依赖图"这条线：开源侧有什么、学术侧有什么；
3. 定位两者之间的空白 —— 空白才叫创新点，重复已有的不叫。

> 说明：以下所有项目与数据均来自 2026-09-17 的实际检索，**未经验证的项目名与指标一律不写入本文档**。学术文献引用均标注出处。

---

## 2. 同类项目盘点

### 2.1 头部项目：DeepTutor（HKUDS，最直接的竞品）

| 项 | 内容 |
|---|---|
| 仓库 | `github.com/HKUDS/DeepTutor` |
| 规模 | 约 3.44 万 Stars / 4400 Forks（2026-08），Apache-2.0 |
| 技术栈 | Python 3.11+ / FastAPI / Next.js / React |
| 文档解析 | **Text-only、MinerU、Docling、Tika、markitdown、PyMuPDF4LLM、LiteParse** 七种引擎可选 |
| 知识组织 | **GraphRAG、LightRAG、PageIndex、LlamaIndex、Obsidian vault** —— 均为**检索导向**的图 |
| 溯源 | CitationManager 生成唯一 ID 并插入 `[N]` 行内引用，支持页码级引用、`rag` 引用可追溯 |
| 引导式教学 | v1.4.5 起 "Guided Learning **rebuilt on the chat agent loop**" + "hard per-type mastery gate" + loop-plugin framework |
| 记忆 | L1 traces / L2 摘要 / L3 综合，Memory Graph 可展示 L2 → L1 证据边 |

**它的关键能力缺口（逐条来自 README 原文核对）**

| 缺口 | 依据 |
|---|---|
| ❌ **无前置依赖 DAG** | README 全文未出现 `DAG` / `prerequisite` / `dependency graph` 任何措辞 |
| ❌ **无知识点难度分级** | 仅有 "mastery gate"（掌握度门控）与 "graded questions"，**无 difficulty level 概念** |
| ❌ **无教学三级结构** | 其 L1/L2/L3 是**记忆**的三层，**不是知识层级**；知识图谱只有 GraphRAG/LightRAG 的实体关系图 |
| ❌ 引导策略非显式状态机 | 是 "chat agent loop + mastery gate"，不是可验证的教学策略状态机（无降级规则、无策略可观测性） |
| ⚠️ 引用是"回答级" | 引用挂在**回答**上（CitationManager 插 `[N]`），不是挂在**知识点**上的强制约束 —— 知识点本身没有"无原文不入库"的门禁 |

**一句话总结**：DeepTutor 把"检索增强的问答"做到了工业级，但它的图是**为检索服务的**；它不回答"这个知识点必须先学什么"。

### 2.2 有教学依赖图的项目：Marble Skill Taxonomy

| 项 | 内容 |
|---|---|
| 仓库 | `github.com/withmarbleapp/os-taxonomy` |
| 规模 | 3849 Stars（2026-07 开源） |
| 数据 | **1590 个微知识点、3221 条有向前置依赖边**，纯 JSON |
| 边设计 | `strength: hard / soft`（强依赖 / 弱依赖）+ **`reason`（为什么有这条依赖）** |
| 节点设计 | `type`（概念/程序性/表征/语言/元认知）、`centrality`（图中重要性）、**`evidence`（判定已掌握的可观察证据）**、`assessmentPrompt`（检测题）、`standards`（对齐课标代码） |
| 许可 | ODbL 1.0（数据库）+ CC BY-SA 4.0（内容），可商用 |

**它的局限（来自项目自述，非我猜测）**

| 局限 | 说明 |
|---|---|
| ❌ **前置关系是人工标注的** | 不是从材料里抽出来的 |
| ❌ **只覆盖小学、只对齐英美课标** | Common Core / NGSS / 英国国家课程标准，**未对齐中国教材** |
| ❌ **静态数据集，不读材料** | 你给它一本讲义，它不会生成新的依赖图 |
| ❌ 无学生数据 | 是知识结构图，不是学习行为数据 |

**它给我们最大的启发**是**边与节点的字段设计**：`hard`/`soft` 二分 + 每条边带 `reason` + 每个节点带 `evidence`。这套设计被 3849 人验证过，我们可以直接借鉴，不必重新发明字段。

### 2.3 其他相关项目

| 项目 | 定位 | 关键缺口 |
|---|---|---|
| `instavm/open-skills` | 技能图谱与学习路径引擎，边分 `depends_on` / `related_to` / `part_of` | 面向**职场技能**，靠人录入数据，不解析教学材料 |
| `Lum1104/Understand-Anything` | 代码库知识图谱 + "按依赖顺序的引导式学习路径" | 面向**代码仓库**（文件/函数/类），不是教学材料 |
| `Shivamkumar-DhammAI/pdf-course-indexer` | 从 PDF 抽课程与主题，建 `prerequisite_for` 关系 | 靠**正则匹配 "prerequisite" 关键词**，玩具级；无 LLM、无校验 |
| `chuongdlb/book-to-knowledge-base` | 把技术书转 Markdown 知识库，带 `depends_on` / `required_by` | 是 Agent Skill 不是系统；依赖是**章级（粗粒度）**，不是知识点级 |
| `jyanqa/NADE-prerequisite-prediction` | 教科书前置依赖预测框架 | **1 star，无 release，未工程化** |

### 2.4 学术侧现状（重要：这个问题不是新的，但没被工程化）

| 文献 | 方法 | 局限 |
|---|---|---|
| **Lu et al., AAAI 2019**《Concept Extraction and Prerequisite Relation Learning from Educational Data》 | 无监督框架：DsCE 图传播抽概念 + **iPRL 迭代式前置学习（特征法 + 依赖法协同）**。在 **18 本中文教材**（微积分/数据结构/物理）上评测，前置关系 F1 比 CPR-Recover 高 16.69% | **纯论文，无可运行实现**。依赖词向量特征工程，未用 LLM |
| **Auto-req, BEA 2023**《Automatic detection of pre-requisite dependencies between academic videos》 | 基于相似度特征的学术**视频**前置边预测；2797 条人工标注前置边数据集 | 对象是**视频**不是教材；核心是特征工程 + 分类器 |
| Miaschi et al. 2019 / Gasparetti 2022 / Li et al. 2019 | LSTM / 词向量 / 图深度学习方法 | 需大量训练数据，真实场景表现有限（原文自评） |

**关键结论**：
> **"从教学材料自动抽取前置依赖关系"是一个被学术界研究了近十年、方法论已经成熟、但几乎没有可用开源实现的问题。** 已有的开源项目要么靠人工标注（Marble），要么只建检索图不建依赖图（DeepTutor），要么是正则玩具（pdf-course-indexer）。

---

## 3. 空白定位

把"能否读任意教师材料"和"图是否带教学依赖语义"作为两个维度，现有项目的分布非常清楚：

| | **图无教学依赖语义**（只是检索图） | **图有教学依赖语义**（前后置关系） |
|---|---|---|
| **能读任意教师材料** | DeepTutor（3.4万★）、Understand Anything、LightRAG / GraphRAG 生态 | 🎯 **本项目的定位**（开源侧空白） |
| **不能读材料**（数据靠人工编） | Excel 知识点清单、传统课标大纲 | Marble Skill Taxonomy（3.8千★，人工标注）<br>open-skills（职场技能，人录） |

学术侧（AAAI 2019 / BEA 2023）证明了右上角这件事**做得到**，但都停留在论文与数据集，**没有做成能读你手上那本讲义的可用系统**。

---

## 4. 创新点陈述

> **创新点（主）：从任意教师教学材料自动构建「知识点级、带硬/软语义、带理由与溯源、且通过 DAG 环路校验」的前置依赖图，并据此生成可解释的学习路径与卡点根因回溯。**

拆开是四个可交付的子能力：

| # | 子能力 | 相对现有工作的位置 |
|---|---|---|
| 1 | **自动抽取**前置依赖边（不靠人工标注） | 相对 Marble：从人工标注 → 自动抽取 |
| 2 | 边上带 `hard`/`soft` 语义 + **`reason`** + **原文溯源** | 借鉴 Marble 的字段设计（被验证过），但**每条边都能回到材料原文** |
| 3 | **写库前做 DAG 环路校验与剪枝** | **开源侧没有人在做这件事**；学术论文基本不讨论图一致性约束 |
| 4 | 卡点诊断时**沿前置边反向回溯**，定位"你其实卡在三节之前" | 相对 DeepTutor：它追踪会话记忆里的薄弱点，**不知道知识点之间的依赖** |

**诚实边界（必须写进 PPT，不要假装是全新问题）**：我们**不是发明了这个问题**——AAAI 2019 就研究过。我们的贡献是**把已有学术方法用 LLM 重新实现，并补上工程侧缺失的一致性约束与可溯源要求**，让它从论文变成能打开就用的产品。这个定位比"我们首创了 XX"更经得起评委追问。

---

## 5. 改进方案（具体设计）

### 5.1 边抽取流程：结构线索 × 语义线索双通道融合

这是本方案的核心，思路直接来自 AAAI 2019 iPRL 的"结构化线索与语义线索协同"，但用 LLM 替代了词向量特征工程：

```
Step A  先抽节点，后抽边
        ── 知识点抽取（P4）先跑完并入库，拿到干净的节点集合
        ── 绝不在同一次调用里既抽节点又抽边（会让边污染节点粒度）

Step B  结构线索（免费，不用调模型）
        ── 材料本身的章节/小节顺序天然给出方向：先出现的章 → 后出现的章
        ── 同节内的知识点按 seq 顺序生成「弱结构边」
        ── 输出：结构边集合 + 一个方向先验分

Step C  语义线索（LLM 判定，P10）
        ── 只对【跨节 / 跨章】的知识点对做判定 → 把 O(n²) 压到可接受规模
        ── 输入：知识点清单（名称 + 一句话摘要 + 所属节），分批投喂
        ── 输出：{(A, B), hard|soft, reason, confidence}

Step D  融合与冲突标记   ←★ 关键
        ── 语义说 A 是 B 的前置，结构与之一致      → 直接采纳，confidence 提升
        ── 语义说后面出现的 A 是前面 B 的前置       → 结构冲突，降 confidence，
                                                     标记 needs_review（存疑），不静默采纳
        ── 只有结构边无语义支持                      → 标为 soft，confidence 下调
        ⚠️ 冲突不丢弃、也不盲信，而是显式暴露出来 —— 这与产品"显式不确定性"原则一致

Step E  写库前 DAG 校验（服务层强制）
        ── 拓扑排序；若有环 → 按 confidence 升序剪边，直到无环
        ── 每次剪边写 WARN 日志（哪条边、为什么被剪、剪后图状态）
        ── cycle_count 必须为 0，且作为质量报告页的展示指标
```

**Step D 与 Step E 是相对现有工作的两个实质改进点。** Marble 因为是人工标注所以天然无环；学术论文大多不讨论这个；GraphRAG/LightRAG 的图本来就不是 DAG，不涉及一致性。**把"教学依赖图必须无环"当成一条工程不变量来强制，是开源侧没有的东西。**

### 5.2 借鉴 Marble 的字段设计（不重新发明）

| 字段 | 来源 | 我们的实现 |
|---|---|---|
| `strength: hard / soft` | Marble | → `kp_prerequisites.relation_type = 'hard' \| 'soft'` |
| `reason`（为什么有这个依赖） | Marble | → `kp_prerequisites.reason`，**必填**，且要求写清"不学懂前置会卡在哪" |
| `evidence`（判定已掌握的可观察证据） | Marble | → 用于答疑时判断学生是否真的掌握了某前置，作为卡点回溯的依据 |
| `centrality`（图中重要性） | Marble | → 可选。用入度（被依赖次数）近似，用于识别"关键地基知识点"并在图谱里高亮 |
| `assessmentPrompt`（检测题） | Marble | → 复用我们已有的 `kp_examples`，不新增字段 |

> 直接借鉴被 3849 人验证过的字段设计，比自己拍脑袋设计字段更省时间也更不容易错 —— 这是"站在别人肩膀上"的正当用法。

### 5.3 反哺答疑：卡点根因回溯（相对 DeepTutor 的实质超越）

```
学生在知识点 K 上卡住
   ↓
沿 kp_prerequisites 反向可达（只走 hard 边）
   ↓
得到 K 的全部硬前置 {P1, P2, ...}
   ↓
结合本轮问答中学生暴露的误区（kp_misconceptions.trigger_pattern）
   ↓
定位到最可能的断层知识点 Pk
   ↓
输出：「你这一题卡在 K，但根因更可能是 Pk 没吃透 —— 材料第 X 页讲过」
      + 建议回头补 Pk，再回来学 K
```

DeepTutor 的 Mastery Path 是**基于会话记忆**的（记录你哪里做错过），本质是"薄弱点追踪"；我们的是**基于知识依赖结构**的（你错在这里，但缺的是那里），本质是"根因定位"。**在计算机网络这门课上，这个差异会非常明显**：学生算错子网划分，往往不是子网划分的问题，而是二进制/掩码换算没吃透。

### 5.4 辅助差异化（不作为主创新点，但成本低、收益明确）

| # | 做法 | 相对现有工作的位置 |
|---|---|---|
| A1 | **知识点级溯源门禁**：`source_quote` 为空的知识点不允许入库（DB 层 NOT NULL + 入库校验） | DeepTutor 的引用是回答级；我们做成知识点级强制约束 |
| A2 | **教学策略状态机可观测**：暴露 `/api/qa/sessions/{id}/state`，UI 显示三轮进度、"连错 2 次降级"规则可见 | DeepTutor 有 mastery gate 但没有策略可观测性；我们把"教学策略"变成评委看得见的东西 |
| A3 | **解析存疑处显式标注**：OCR 置信度低 / 字段缺失一律进 `uncertain_notes` 并在素材清单展示 | 各解析引擎（MinerU/Docling）都只输出结果，不输出"我哪里不确定" |

---

## 6. 可验证指标（已并入 SPEC §7.5）

| 编号 | 指标 | 目标 | 验证方式 |
|---|---|---|---|
| B1-1 | 前置依赖边人工抽检合理率 | ≥ 80% | 从抽出的边中随机抽 50 条，人工判定"这条前置关系在教学上是否成立" |
| B1-2 | **DAG 环数量** | **0** | 图算法校验（拓扑排序） |
| B1-3 | 学习路径拓扑有序率 | 100% | 抽样 10 个目标知识点，检查路径中任一节点都不依赖其后面的节点 |
| B1-4 | **结构-语义冲突检出率** | 100% | 构造 3 组"故意让语义判定与章节顺序矛盾"的测试输入，检查是否全部被标记为 `needs_review` 而非静默采纳 |
| B1-5 | 边理由完备率 | 100% | SQL 校验 `reason` 非空 |
| B1-6 | 卡点根因回溯可用率 | ≥ 70% | 抽 20 个"停在中后段知识点"的卡点场景，人工判定回溯出的前置根因是否合理 |

> **B1-4 是这套设计里最能体现工程深度的一项** —— 它验证的不是"模型抽得准不准"，而是"系统在模型不确定时是否诚实"。构造对抗性测试输入、并让评分者看到你的系统会显式暴露矛盾，这比单纯报一个准确率更有说服力。

---

## 7. 风险与降级方案

| 风险 | 触发条件 | 降级方案 |
|---|---|---|
| LLM 抽出的前置边质量差 | B1-1 抽检合理率 < 60% | 退化为**仅结构边**（按章节顺序生成依赖），放弃语义判定。学习路径仍可生成且必然无环，只是颗粒度变粗 —— **这仍比 DeepTutor 强，因为它连结构依赖都没有** |
| 跨节判定调用量过大 | 知识点 > 150 个时 | 只判定"章间 + 相邻节间"，节内用 seq 隐式边，把候选对从 O(n²) 降到 O(n·k) |
| 冲突边过多，`needs_review` 堆积 | 冲突率 > 30% | 说明材料结构混乱或抽取不稳，此时**优先信结构线索**（教材的章节顺序是作者编排过的，可信度高），并在质量报告里如实呈现 |
| 时间不够 | D7 未达 M4 | 砍掉 §5.4 的 A2/A3 辅助项，保住主创新点（§5.1~5.3） |

---

## 8. 参考文献与项目

| 类型 | 名称 | 地址 |
|---|---|---|
| 项目 | DeepTutor (HKUDS) | github.com/HKUDS/DeepTutor |
| 项目 | Marble Skill Taxonomy | github.com/withmarbleapp/os-taxonomy |
| 项目 | open-skills | github.com/instavm/open-skills |
| 项目 | Understand Anything | github.com/Lum1104/Understand-Anything |
| 项目 | NADE-prerequisite-prediction | github.com/jyanqa/prerequisite-text-extracttion |
| 文献 | Lu et al., *Concept Extraction and Prerequisite Relation Learning from Educational Data*, AAAI 2019 | — |
| 文献 | *Auto-req: Automatic detection of pre-requisite dependencies between academic videos*, BEA 2023 | aclanthology.org/2023.bea-1.45.pdf |
| 文献 | Miaschi et al. 2019 / Gasparetti 2022 / Li et al. 2019（前置关系检测的既有方法） | — |

---

## 9. 版本记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-09-17 | 建立：同类项目盘点、学术侧现状、空白定位、创新点陈述、改进方案、可验证指标 |
