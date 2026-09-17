# Multimodal Teaching Agent · 析知 XiZhi

> 多模态教学智能体 —— 图文素材智能解析 · 知识点结构化抽取 · 交互式答疑辅导
>
> 粤港澳大湾区 AI Coding 创新大赛参赛项目仓库。本仓库用于团队共同维护多模态教学智能体的代码、文档与可交付成果。

---

## 一句话说明

给一份《计算机网络》的真实教学材料，系统把它变成**可查询、可溯源、能引导学生自己学会**的结构化知识体。

**核心创新点**：AI 预抽取 + 人工校验的**知识点依赖图**构建，并首次把「**教学依赖图必须无环**」作为工程不变量强制保证；据此生成可解释的学习路径与卡点根因回溯。

---

## 协作入口

- 开始开发前，请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 每项工作从 Issue 开始，在独立分支完成，并通过 Pull Request 合并到 `main`。
- 密钥、密码、访问令牌和含个人隐私的数据不得提交到仓库。
- 大型模型、数据集、视频等大文件不要直接提交；确定存储方案后再纳入版本管理。

> **规格先行的补充约定**：本项目的产品与工程规格以 [`SPEC.md`](SPEC.md) 为**唯一权威源**，偏离即缺陷。任何范围 / 技术 / 交互上的调整，先走 `SPEC.md` §12 的变更流程，再改代码。

---

## 材料与许可

教材采用 ***Computer Networks: A Systems Approach***（Larry Peterson & Bruce Davie, 6th Edition），**CC BY 4.0**。

> Title: Computer Networks: A Systems Approach — Authors: Larry Peterson and Bruce Davie — Copyright: Elsevier, 2012 — Source: https://github.com/SystemsApproach/book — License: CC BY 4.0

其余第三方材料的名称、作者、许可与来源见 [`docs/materials-and-licenses.md`](docs/materials-and-licenses.md)。

---

## 目录结构

```
.
├── SPEC.md                      # ★ 产品与工程规格说明书（唯一权威源）
├── CONTRIBUTING.md              # Git 协作规范
├── docs/                        # 规格附件与调研文档
│   ├── data-model.md            #   数据模型（14 张表）
│   ├── api-spec.md              #   接口规格（27 个端点）
│   ├── prompt-contracts.md      #   Prompt 契约（P1~P10）
│   ├── innovation.md            #   创新点调研与改进方案
│   ├── extraction-channel.md    #   抽取通道规格与冒烟测试记录
│   ├── edge-review-consensus.md #   前置依赖边判定口径与共识材料
│   ├── materials-and-licenses.md#   材料来源与许可合规
│   ├── platform-capability-check.md # 平台能力边界验证报告
│   ├── delivery-form.md         #   作品形态决策分析
│   ├── tasks/                   #   逐人每日任务清单
│   └── buddy-logs/              #   LearnBuddy 使用记录（提交材料之一）
├── backend/                     # FastAPI 后端
├── frontend/                    # React 前端
├── pipeline/                    # 离线构建工具链（解析、抽取、建图）
├── scripts/                     # 运维与评测脚本
├── samples/                     # 测试夹具与实测输出
└── skills/                      # 挂载到 LearnBuddy 平台的自定义技能
```

---

## 团队分工

详见 [`SPEC.md`](SPEC.md) §9。

| 代号 | 角色 | 成员 | 负责范围 |
|---|---|---|---|
| **P1** | 解析工程 | [@DakerDack](https://github.com/DakerDack) | 素材解析、OCR 链路、部署、DAG 校验与剪枝算法 |
| **P2** | 数据与结构化 | [@Mikeys5s](https://github.com/Mikeys5s) | 数据模型、接口、知识点抽取、**依赖边判定（创新点主创）**、检索层 |
| **P3** | 前端与交互 | [@RyeYen](https://github.com/RyeYen) | 五页 UI、苏格拉底状态机与模板库、卡点根因回溯可视化、Demo 视频与 PPT |

> 每位成员首次提交前，请先按 [`SPEC.md`](SPEC.md) §9.1 的对应表配置自己的提交身份。

---

## 快速开始

> 待补：环境准备与一键启动步骤（D1–D2 完成后填写）
