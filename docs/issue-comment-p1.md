# 【析知决赛 · P1】分工微调 + 一件想请教你的事

先给结论：**你原定三件里，两件我已先做（不用重做）；一件仍请你做；另有一件想向你请教。**

## 一、不用做了（已落地）

**1. 重复组映射表** —— 项目里早有 `docs/graph/dedup-grouping.json`（629 条按正文指纹归 167 组，字段 `keep_id` / `dupe_count` / `dupe_ids` / `dupe_batches`，保留组内 id 最小者）。它已从"决策材料"变成实际数据：我转成了 `backend/app/kp_dedup.json`，给 API 加了 `is_duplicate` / `duplicate_of` / `duplicate_group_size` 三个字段，**线上已生效**。⇒ 这件不用做。

**2. 小节标题映射表** —— 项目里有 `docs/graph/kp-name-quality.json`（`kind` / `needs_review` / `len`），但它只**分类**、没给可读标题。所以**可读标题这一件我已自己做了**：产出 `docs/graph/kp-titles.json`，629 条里 **438 条有可读标题（69.6%）**，来源分布 `raw_name` 156 + `section_heading` 282，走「小节标题 → 首句截断 → 原名可读」三级优先级，取不到写 `null`、不编造。⇒ 这件不用重做；但**你若愿意复核或改进，非常欢迎**。

## 二、仍请你做：例题出题（Ch03）

Ch05（端到端协议）我那半已出 14 条（9 例题 + 5 误区，见 `docs/graph/examples-ch05-p2.json`），已灌库验证。按原分工，你那半是 **Ch03（Internetworking）**：产出 `exports/examples-p1.json`，每条带 `source_quote`、`source='human'`，**约 2 小时**。除非你判断时间不够，说一声我们另议。

## 三、想请教你一个真问题

剩下 **191 条取不到可读标题**（`display_title: null`）。我判断大部分是 `summary_md` 本身即被截断的英文句片段（如 `Problem: Not All Networks are`），**从我这侧已经上不去了**。

**从解析侧有没有根因级的办法？** 比如利用 PDF 里的章节结构（标题层级 / 目录 / 字体排版信号）反推每个知识点所属小节。有路子的话，哪怕只覆盖一部分，也比我在 69.6% 上硬凑强。
