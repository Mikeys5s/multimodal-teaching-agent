# 抽取通道冒烟测试（2026-09-17）

> 目的：在正式开发前验证**主通道（LearnBuddy）能按契约产出合格 JSON**。
> 完整记录与结论见 [`../../docs/extraction-channel.md`](../../docs/extraction-channel.md) §5–§6。
> 状态：**P3 / P4 / P10 三个契约全部通过**。

---

## 材料来源与许可

| 项 | 内容 |
|---|---|
| 材料 | *Computer Networks: A Systems Approach*（Larry Peterson & Bruce Davie, 6th Edition） |
| 出处 | `https://book.systemsapproach.org/congestion/tcpcc.html` |
| 章节 | Chapter 6 Congestion Control → 6.3 TCP Congestion Control |
| 许可 | **CC BY 4.0** —— 可自由使用与改编，需署名（见 `docs/materials-and-licenses.md`） |

**署名格式**（引用本材料时必须原样附带）：

> Title: Computer Networks: A Systems Approach — Authors: Larry Peterson and Bruce Davie — Copyright: Elsevier, 2012 — Source: https://github.com/SystemsApproach/book — License: CC BY 4.0

---

## 文件说明

| 文件 | 契约 | 内容 |
|---|---|---|
| `P3-outline.json` | P3 章节目录识别 | 1 章 + 3 节的骨架 |
| `P4-output.json` | P4 逐节知识点抽取 | 9 个知识点，全部带逐字原文溯源 |
| `P10-output.json` | P10 前置依赖边抽取 | 10 条边（8 hard / 2 soft），全部带 reason |

## 输入块的 id 约定

`blk_c{章}-{节}-{子节}-{序号}`，例如 `blk_c6-3-2-04` = 第 6 章 6.3 节第 2 个子节第 4 块。

> 网页版材料**没有页码**，因此 `source_page` 一律为 `null`，溯源以 `source_quote`（逐字原文）为准 —— 这与数据模型的设计一致（`source_quote` NOT NULL、`source_page` 可空）。

## 怎么用这些夹具

1. **schema 校验**：拿 `P4.schema.json` / `P10.schema.json` 校验这两个 JSON，作为入库流水线的单测输入。
2. **入库测试**：走一遍 `ingest()`，检查是否全部通过、`needs_review` 是否为空、环数是否为 0。
3. **图算法测试**：用 `P10-output.json` 构造图，验证拓扑排序、学习路径生成、反向可达（卡点根因回溯）。
4. **前端联调**：直接灌进 SQLite，用来调知识图谱可视化与知识点详情页，不用等真实材料解析完。
5. **回归基线**：将来 Prompt 或契约改动后，可对比新旧产出（对应 A2-7 可复现性验证）。
