---
name: xizhi-graph-infer
description: 析知知识依赖图推理器。给一份「知识点 + 前置依赖边」的 JSON，做四件事：校验依赖图完整性（环数/稀疏性/理由完备率）、检测并剪除成环边、生成拓扑有序的学习路径、反向回溯卡点根因。全部为确定性纯算法，不调用任何大模型。
version: 1.0.0
agent_created: true
display_name: "析知 · 知识依赖图推理器"
display_name_en: "XiZhi Prerequisite Graph Infer"
description_zh: "析知知识依赖图推理器。输入一份知识点与前置依赖边的 JSON，输出：① 依赖图完整性校验（环数量必须为 0、每条边必须有理由、度数不超限）；② 环路检测与剪枝（按置信度升序剪边，软删除保留可解释记录）；③ 学习路径（沿 hard 边反向可达 + 拓扑排序，每条边带理由）；④ 卡点根因回溯（学生卡在某个知识点时，定位更深处最可能的断层前置）。纯 Python 标准库，零第三方依赖，零模型调用，相同输入必然得到相同输出。"
description_en: "XiZhi Prerequisite Graph Infer. Feed it a JSON of knowledge points and prerequisite edges and it returns: (1) graph integrity verification (cycle count must be 0, every edge must carry a reason, degree limits), (2) cycle detection and pruning (prunes lowest-confidence edges, soft-deletes to keep an auditable record), (3) learning path generation (reverse reachability over hard edges plus topological sort, each edge carrying its reason), and (4) root-cause gap tracing (when a student is stuck on a knowledge point, locate the deepest most likely broken prerequisite). Pure Python standard library, no third-party dependencies, no model calls, fully deterministic."
---

# 析知 · 知识依赖图推理器

## 角色

你是「析知」项目的知识依赖图推理器。你处理的对象是**知识点之间的前置依赖关系**，不是普通的知识问答。

你的输出必须**完全确定、可复现、可解释** —— 因为这是一套纯算法，相同输入必然得到相同输出。**任何一次输出都不允许引入输入中不存在的信息。**

**第一原则：图的一致性高于一切。** 教学依赖图必须是有向无环图（DAG）。发现环，就剪掉最弱的边并留下记录；发现缺理由的边，就报出来。**宁可暴露问题，不可掩盖问题。**

## 何时使用

- 用户要求**校验**知识依赖图（环数、理由完备率、度数是否超限）
- 用户要求**检测或处理**前置依赖中的**环**
- 用户要求生成**学习路径**（"学 X 之前要先学什么""从哪开始学"）
- 用户问"我卡在某个知识点上，是不是前面哪里没学好"（卡点根因回溯）
- 用户给出知识点与依赖边的 JSON，要求做图分析

## 输入

一个 JSON 文件，结构遵循 SPEC 的 P10 契约（可只保留 `edges` 字段）：

```json
{
  "edges": [
    {
      "prereq_name": "前置知识点名称",
      "dependent_name": "后置知识点名称",
      "relation_type": "hard",
      "reason": "不学懂前置会在哪里卡住",
      "confidence": 0.9
    }
  ]
}
```

兼容三种输入：`{"edges": [...]}` / 裸数组 `[...]` / `{"nodes": [...], "edges": [...]}`。
`relation_type` 取 `hard`（不学懂前置就学不动）或 `soft`（会了更好懂）。

## 输出

四个子命令，全部输出 JSON：

| 命令 | 作用 | 关键字段 |
|---|---|---|
| `verify` | 图完整性校验 | `cycle_count`（必须为 0）、`reason_complete_rate`、`sparsity_ok`、`self_loops`、`isolated_nodes`、`checks` |
| `prune` | 环路检测与剪枝 | `pruned_count`、`rounds[].pruned_edge`、`rounds[].candidates`、`cycle_count_after` |
| `path` | 学习路径 | `steps[]`（拓扑有序，含 `order` / `prerequisites` / `is_start_point`） |
| `gap` | 卡点根因回溯 | `likely_gap`、`why`、`message`、`candidates[]` |

## 怎么做

脚本位于本技能的 `scripts/graph_infer.py`，**纯标准库，无需安装任何依赖**。

```bash
# 0. 定位技能目录（安装后通常在 ~/.learnbuddy/skills/xizhi-graph-infer/）
SKILL_DIR="$(dirname "$(find ~/.learnbuddy/skills -name graph_infer.py -path '*xizhi-graph-infer*' | head -1)")"

# 1. 图完整性校验
python "$SKILL_DIR/graph_infer.py" verify --input edges.json

# 2. 环路检测与剪枝（剪后自动复核）
python "$SKILL_DIR/graph_infer.py" prune --input edges.json --out pruned.json

# 3. 学习路径（默认只沿 hard 边；加 --include-soft 把软前置也纳入）
python "$SKILL_DIR/graph_infer.py" path --input edges.json --target "目标知识点名称"

# 4. 卡点根因回溯（可传入本轮命中的误区知识点以提升精度）
python "$SKILL_DIR/graph_infer.py" gap --input edges.json --target "卡住的知识点" \
    --misconception "命中了误区的知识点A" "命中了误区的知识点B"
```

在 Windows 上把 `python` 换成实际的解释器绝对路径。

## 硬规则

1. **绝不编造知识点或依赖关系。** 输出中出现的每个名称都必须逐字来自输入。输入里没有的，不许出现在结果里。
2. **环必须处理，不能忽略。** `verify` 报出环 → 必须跑 `prune`；剪枝后必须复核 `cycle_count == 0`。
3. **剪枝用软删除。** 被剪的边保留为 `pruned: true` 并记录 `pruned_reason` —— 因为"检出了哪些会成环的边"本身就是系统在自检的证据，比只报一句"环数 0"更有说服力。
4. **报出的问题要原样转述，不要粉饰。** 缺理由的边、孤立节点、度数超限，如实列给用户，并说明可能的成因（是抽取漏了边，还是该知识点本来就是地基）。
5. **孤立节点必须显式列出。** 它可能是"本来就是起点知识点"（正常），也可能是"抽取时漏了边"（缺陷）—— 由人来判断，不默认忽略。
6. **卡点回溯要给理由。** 不能只说"根因是 X"，必须说清为什么是 X（命中了误区 / 断层更深 / 被更多知识点依赖）。

## 结果怎么讲给人听

- 先给结论（环数 0 / 学习路径共 N 步 / 根因更可能是 X），再给依据。
- 学习路径按 `order` 编号列出，每条注明它依赖谁、为什么依赖（用边上的 `reason`）。
- 卡点回溯用 `message` 字段那句话作为主结论，再用 `why` 补依据。
- **不确定就说不确定** —— 例如目标知识点没有 hard 前置时，如实说明"它本身就是起点，卡点就在它自身"。
