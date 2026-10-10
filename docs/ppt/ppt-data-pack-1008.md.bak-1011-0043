# 析知 XiZhi · PPT 数据素材包（可核对版）

> **给 P3（作品介绍 PPT 更新用）**
> 本文件**只放数字 + 出处**，不放叙述。每个数字都是 **2026-10-08 实测**得到的，
> 出处写在每张表的第三列 —— **评委追问时，顺着出处就能复现**。
>
> **纪律**：**不编数字**。跑不通 / 取不到的，写「未实测」并说明原因，绝不填一个看起来漂亮的数。
>
> **实测环境**：线上服务 `http://120.77.177.171:8000`（无需 token）；本地仓库 `D:\muti_tagent`。

---

## ① 项目规模

| 数字 | 值 | 出处（可核对） |
|---|---|---|
| 知识点总数 | **629** | `GET /api/knowledge-points?page_size=1` → `data.total`（实测） |
| 材料数 | **4** | `GET /api/materials` → `data.total`（实测） |
| 材料页数（合计） | **114** 页 | `GET /api/materials` → `data.items[].page_count`：24 + 31 + 57 + 2（实测） |
| 章节数（4 份材料求和） | **138** | `GET /api/materials/{id}/outline` → `data.chapters` 长度：31 + 35 + 71 + 1（实测） |
| 知识图谱节点数 | **629** | `GET /api/knowledge-graph?max_nodes=1000` → `nodes` 长度（实测） |
| 知识图谱边数 | **645** | 同上 → `edges` 长度（实测） |

**单份材料明细**（出处：`GET /api/materials` + `GET /api/materials/{id}/outline`）

| material_id | 类型 | 页数 | 章节数 | 首章 |
|---|---|---|---|---|
| `mat_cf6fcaa0` | pdf_text | 24 | 31 | 前言 |
| `mat_42b16cd4` | pdf_text | 31 | 35 | 前言 |
| `mat_ada1063f` | pdf_text | 57 | 71 | 前言 |
| `mat_9f2a1c40` | pdf_scan | 2 | 1 | 传输层 |

> ⚠️ 「138 章」是**4 份材料章节数直接相加**，材料之间可能有重叠，**不要写成「教材共 138 章」**。

---

## ② 知识依赖图（核心创新点）

| 数字 | 值 | 出处（可核对） |
|---|---|---|
| hard 边 | **23** | `GET /api/knowledge-graph` → `stats.hard_edge_count`（实测） |
| soft 边 | **622** | 同上 → `stats.soft_edge_count`（实测） |
| **环数** | **0** | ① 同上 → `stats.cycle_count`；② `python skills/xizhi-graph-infer/scripts/graph_infer.py verify --input <边文件>` → `cycle_count`（实测） |
| **边理由完备率** | **100%（24/24）** | 边文件每条 `reason` 非空：`docs/graph/hard-edge-candidates.json`（16/16）+ `docs/graph/hard-edges-ch06-1007.json`（8/8）；`graph_infer verify` 报 `reason_complete_rate = 1.0`（实测） |
| 每条 hard 边带原文摘录 | **24/24** | 同上两文件每条 `evidence_quote` 非空（实测） |
| Ch06 补边批次 | **8 条** | `docs/graph/hard-edges-ch06-1007.json` → `edges`（实测）；该文件 `_为什么补这一批` 说明「9/22 的 15 条只覆盖 Ch03(9)+Ch05(6)，Ch06 为 0，本批补 8 条」 |

**实测命令与结果**（出处：本机运行 `python skills/xizhi-graph-infer/scripts/graph_infer.py verify`）

```
input = 两份边文件合并（16 + 8 = 24 条 hard 边）
node_count = 34 | edge_count = 24 | hard_edge_count = 24
cycle_count = 0 | nodes_in_cycle = [] | self_loops = []
reason_complete_rate = 1.0 | missing_reason = 0
checks = {B1-2_cycle_zero: True, B1-5_reason_complete: True, no_self_loop: True,
          sparsity_within_limit: True, no_isolated_node: True}
```

> ⚠️ **两个必须如实说明的点**（别让评委先发现）：
> 1. **直接对边文件跑 `verify` 是「空跑」**：边文件字段是 `kp_id`/`prereq_kp_id`，而 `graph_infer.py` 认的是
>    `prereq_name`/`dependent_name`（P10 契约）。**不转字段名直接跑，输出 `edge_count = 0`、`cycle_count = 0`
>    —— 这个 0 是假 0，不能拿来当证据。** 上表结果是把字段名映射后重跑的（图拓扑不变）。
> 2. **文件里 24 条 hard 边，线上图只有 23 条** —— 差的是
>    `kp_42b16cd4_000_000_016 → kp_42b16cd4_000_000_011`（`hard-edge-candidates.json` 里那条，
>    线上未入库）。**PPT 写线上数字要用 23。**

**边分布参考**（出处：`docs/new_plan.md` 隐患④ + 上述文件）

| 批次 | 条数 | 覆盖 |
|---|---|---|
| 9/22 第一批 | 15 条（文件里 16 条，1 条未入库） | Ch03 9 条 / Ch05 6 条 |
| 10/07 Ch06 补批 | 8 条 | Ch06 |
| **线上合计** | **23** | — |

---

## ③ 重复数据（诚实展示）

| 数字 | 值 | 出处（可核对） |
|---|---|---|
| 知识点条目总数 | **629** | `docs/graph/dedup-grouping.json` → `total_entries`（实测） |
| **唯一（去重后）组数** | **167** | 同上 → `group_count`（实测） |
| **副本（重复）条数** | **462** | 629 − 167 = 462；亦等于 `groups[].dupe_count` 求和 = 462（实测） |
| 最大一组规模 | **35 成员**（34 副本 + 1 代表） | 同上 `max(dupe_count) = 34`；线上实测 `GET /api/knowledge-points/kp_42b16cd4_000_000_012` → `duplicate_group_size = 35` |

**副本数分布**（出处：`docs/graph/dedup-grouping.json` → `groups[].dupe_count`）

| dupe_count | 组数 |
|---|---|
| 34 | 1 |
| 32 | 1 |
| 20 | 1 |
| 12 | 1 |
| 10 | 2 |
| 4 | 1 |
| 3 | 72 |
| 2 | 49 |
| 1 | 26 |
| 0 | 13 |

> ⚠️ **处置方式必须如实说**：我们做的是 **「显式标注」**（同一组只返回一个代表 + 标注组大小），
> **不是「去重」** —— 462 条副本**仍在库里**。PPT 上**不能写「已去重」**。

---

## ④ 例题 / 误区

| 数字 | 值 | 出处（可核对） |
|---|---|---|
| Ch05 批 · 例题 | **9** | `docs/graph/examples-ch05-p2.json` → `counts.examples`（实测） |
| Ch05 批 · 误区 | **5** | 同上 → `counts.misconceptions` |
| Ch05 批 · 覆盖知识点 | **9** | 该文件 `items[].kp_id` 去重计数（实测） |
| Ch05 批 · 例题原文溯源 | **9 / 9** | 9 条 `example` 每条 `source_quote` 非空（实测） |
| Ch05 批 · 误区原文溯源 | **0 / 5** | 5 条 `misconception` 字段只有 `wrong_belief`/`cause`/`remedy`，**无 `source_quote`**（实测） |
| 早期批 · 例题 | **10** | `docs/graph/examples-misconceptions.json` → `counts.example` |
| 早期批 · 误区 | **7** | 同上 → `counts.misconception` |
| 早期批 · 覆盖知识点 | **10** | 同上 → `counts.knowledge_points_covered` |
| 早期批 · 原文溯源 | **17 / 17** | 该文件 17 条**全部**带 `source_quote`（实测） |
| **两批合计** | **例题 19 / 误区 12 = 31 条** | 9+10 / 5+7（实测） |

**线上抽查（`GET /api/knowledge-points/kp_42b16cd4_000_000_034`，实测）**

| 字段 | 值 |
|---|---|
| `example_count` | 1 |
| `misconception_count` | 1 |
| 例题 `analysis_md` 含「原文」二字 | ✅（`scripts/e2e-check.py` 第 4 层断言「例题带原文溯源」实测通过） |

> ⚠️ **不要说「629 个点都有例题」**：两批加起来只覆盖约 **19 个知识点**（9 + 10，去重前）。
> 出处：`docs/new_plan.md` 隐患③「只有 9 个点是人工写的；其余是派生的」+ 上述 `counts`。

---

## ⑤ 检索与答疑（今天的成果）

| 数字 | 值 | 出处（可核对） |
|---|---|---|
| 可读标题覆盖率 | **438 / 629 = 69.6%** | `docs/graph/kp-titles.json` → `_覆盖率 = "69.6%"`；`items` 非空计数 = 438（实测） |
| 标题来源分布 | `raw_name` **156** + `section_heading` **282** = 438 | 同上 → `_来源分布`（实测） |
| 检索排序（可读名占比） | **50% → 67% → 75%** | 见下方「变化前→变化后」 |
| 多轮答疑状态机序列 | **S1_PROBE → S2_HINT1 → S4_EXPLAIN → CONFIRM** | `python scripts/e2e-check.py` 第 3 层实测输出（实测） |

**「50% → 67% → 75%」的来历** —— **⚠️ 更正**：这三个数字**不在** `docs/new_plan.md` 的隐患⑤ 那节
（那节只写了判据「命中首个是可读知识点名的比例 ≥ 80%」，**没有** 50/67/75 这三个数）。
它们真实出处如下：

| 阶段 | 数字 | 出处 |
|---|---|---|
| 改前 | **6 / 12 = 50%** | `.learnbuddy/memory/2026-10-07.md:713`（commit 2de2d61：标题参与打分，50% → 67%） |
| 改后（一） | **8 / 12 = 67%** | 同上 |
| 改后（二） | **9 / 12 = 75%** | `.learnbuddy/memory/2026-10-08.md:96`（修「缩写被误判不可读」，67% → 75%） |

> 同一处还记了**宽口径**：剩下 3 个 ❌ 里有 2 个「其实是正确答案、只是名字难读」，
> 按这个口径重算是 **11 / 12 ≈ 92%**。**两个口径都要标，不能只挑 92% 用**
> （出处：`.learnbuddy/memory/2026-10-08.md:100-114`）。

**状态机序列的出处更正**：`scripts/e2e-check.py` 第 3 层的注释里写的是**轮次标签**
（`probe / hint / escalate / oos`），**并没有写 `S1_PROBE → S2_HINT1 → S4_EXPLAIN → CONFIRM`**。
这条 S 序列的原始出处是 `.learnbuddy/memory/2026-10-08.md:240`；
**本次实测**（`e2e-check.py` 输出）复现了同一条：状态依次为
`['S1_PROBE', 'S2_HINT1', 'S4_EXPLAIN', 'CONFIRM']`（第 3 轮从 S2 直接跳 S4_EXPLAIN = 连续 2 次答不上 ⇒ 降级直讲）。

---

## ⑥ 验证与工程完整性

| 数字 | 值 | 出处（可核对） |
|---|---|---|
| 全链路复验断言 | **40 项，全过** | `python scripts/e2e-check.py` 实测输出：「✅ **全部通过**（40 项）」 |
| 部署自检 | **6 项，全过（❌ 0）** | `python scripts/check-deploy.py` 实测输出：「部署后自检：✅ 6 项 ❌ 0 项」 |
| 部署代码身份 | 本地哈希 = 容器哈希 = `54fa5391af1fda83`（61 个 .py） | 同上 ①（实测） |
| 容器健康 | `Up (healthy)` | 同上 ②（实测） |
| 交付物 | **5 项**：在线链接 / 源码仓库 / 视频 / PPT / LearnBuddy 对话记录 | `docs/new_plan.md:5` |
| 对话记录规模 | **185 轮 / 11 天** | `docs/conversation/主题索引.md:2-3`（正文实测） |
| 对话记录细节 | 助手输出 **1,681 段** · 工具调用 **3,992 次** · 模型思考留痕 **3,085 段** | `docs/conversation/主题索引.md:14-22` |

**e2e 断言的 4 层分布**（出处：`scripts/e2e-check.py` docstring + 实测输出）

| 层 | 验什么 | 实测结果 |
|---|---|---|
| 1 路由 | 6 个前端路由 | 全 200 |
| 2 API 契约 | 关键端点 + 字段校验 | 全过（含 404 / 400 负向用例） |
| 3 业务链路 | 多轮答疑（4 轮 SSE + 状态机） | 全过 |
| 4 近期改动 | 重复标注 / 例题溯源 / 学习路径（Ch06 路径 **4 步**） | 全过 |

---

## ⭐ 建议的 PPT 页面结构（给 P3，8–10 页）

| # | 标题 | 放哪些数字 | 一句话论点 |
|---|---|---|---|
| 1 | **封面** | 项目名 + 一句话定位 | 「把知识图谱从**检索图**改造成**教学依赖图**」 |
| 2 | **空白定位** | DeepTutor 3.4万★（检索图，无 DAG）、Marble 3849★（有依赖但**人工标注**） | 既有工作要么不建依赖图，要么靠人标 —— 我们做**从材料自动抽** |
| 3 | **核心创新** | **629 点 / 645 边 / 23 hard 边 / 环数 0** | 知识点级、带 hard/soft 语义的**前置依赖图**，且**通过 DAG 校验** |
| 4 | **技术深度** | 结构线索 × 语义线索双通道；每条 hard 边 **reason 完备率 100%（24/24）+ 原文摘录** | 每条依赖都能回到**材料原文**，不是模型猜的 |
| 5 | **教学闭环** | 学习路径（Ch06 实例 **4 步**）+ 卡点根因回溯（沿 hard 边反查） | 从「你错在这」升级到「你其实缺在那」 |
| 6 | **数据诚实页** | **629 → 167 组，462 副本；显式标注（非去重）** | 主动把「数据里有重复」摊开讲，并说明处置边界 |
| 7 | **检索与答疑** | 排序 **50%→67%→75%**；状态机 **S1_PROBE→S2_HINT1→S4_EXPLAIN→CONFIRM** | 首轮不给答案、连错 2 次才降级 —— 教学策略**可观测** |
| 8 | **工程完整性** | **40 项 e2e 全过 + 部署自检 6 项 + 代码哈希一致** | 「部署完了」是被**断言验证过**的事实，不是口号 |
| 9 | **AI 工具使用（25% 分值）** | **185 轮 / 11 天 / 3,992 次工具调用**；**刻意不用 AI 的地方**（图算法纯确定性） | 「知道哪里**不该**用 AI」也是使用深度 |
| 10 | **交付物 + 下一步** | 交付物 **5 项**；未达标项如实列（69.6%、75%） | 诚实比漂亮重要 |

### 🔍 最该放大的 3 个数字（我的判断）

1. **环数 0** —— 技术创新性（30%）的核心证据，且是**可被评委当场复跑验证**的工程不变量。
2. **40 项 e2e 断言全过** —— 工程完整性（25%）最硬的证据；还有「抓到一个 HTTP 200 但 SSE 零字节的静默 bug」的故事可讲。
3. **185 轮 / 11 天 / 3,992 次工具调用** —— AI 工具使用占 25%，且是**美佳指定重點**，规模数字最直观。

### ⚠️ 不要用 / 要谨慎用的数字

| 数字 | 为什么 |
|---|---|
| **标题覆盖率 69.6%** | **不能说「已全部修复」**。仍有 **191 个点无可读标题**（629−438）。说成「已覆盖近七成，剩余标为待核实」 |
| **重复数据 462 条** | **不能说「已去重」**。只做了**显式标注**，副本仍在库里。原话应是「462 条重复**已标注**，同组只显示一个代表」 |
| **检索 75%** | **未达 80% 判据**，不能说「达标」。要用就**同时标**宽口径 92%（并解释口径差异） |
| **例题/误区 31 条** | 只覆盖约 **19 个知识点**，不能说「每个知识点都有题」。且 Ch05 批的 **5 条误区 0 条带原文溯源** |
| **hard 边 24 条** | 那是**文件**数；**线上是 23 条**（1 条未入库）。说线上必须用 23 |
| **soft 边 622 / conflict 644** | `stats.conflict_count = 644` 说明绝大多数边被标为「结构-语义冲突待复核」，**别把它当成「冲突已处理」**；这条建议**不单独上 PPT**，被问再答 |
| **138 章** | 是 4 份材料章节数**相加**，材料间可能重叠，不能当「教材章数」 |
| **「各知识点标题可读率 ≥ 90%」** | 那是 `new_plan.md` 的**目标判据**，**不是**当前实测值（当前 69.6%）。别把目标当结果 |
| **「环数 0」的伪证据** | 别用「直接跑 `graph_infer verify` 输出 cycle_count=0」当证据 —— 不转字段名时它 `edge_count=0`，那个 0 是空跑 |

---

## 附：本文件所有数字的一次性复现命令

```bash
# ① 规模
curl "http://120.77.177.171:8000/api/knowledge-points?page_size=1"   # total=629
curl "http://120.77.177.171:8000/api/materials"                       # total=4, 页数 24/31/57/2
curl "http://120.77.177.171:8000/api/knowledge-graph?max_nodes=1000"  # nodes=629 edges=645
# ② 图（字段名映射后）
python skills/xizhi-graph-infer/scripts/graph_infer.py verify --input <转好字段的边文件>
# ③④ 数据文件
python -c "import json;d=json.load(open('docs/graph/dedup-grouping.json',encoding='utf-8'));print(d['total_entries'],d['group_count'])"
# ⑤ 检索/标题
python -c "import json;print(json.load(open('docs/graph/kp-titles.json',encoding='utf-8'))['_覆盖率'])"
# ⑥ 验证
python scripts/e2e-check.py        # 全部通过（40 项）
python scripts/check-deploy.py     # ✅ 6 项 ❌ 0 项
```

> **实测时间**：2026-10-08　**实测人**：与 P3 协作的队友（本文件由其生成）
