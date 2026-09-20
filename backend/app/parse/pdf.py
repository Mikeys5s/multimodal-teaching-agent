"""文本层 PDF 解析（归属：P1）。SPEC §5.1 / 验收项 A1-2 / A1-6 / F1.2。

为什么是 PyMuPDF 的文本 API，而不是"先渲染成图再 OCR"
------------------------------------------------------
验收项 **A1-2 要求文本层 PDF 原文抽取准确率 ≥ 98%**。OCR 再准也是"识别"，
会把 `l`/`1`、`rn`/`m` 认错，98% 是个很难长期守住的线；而文本层 PDF 里
**本来就存着准确的字符**，直接用 `get_text("dict")` 读出来就是 100%。
所以本模块对文本层 PDF **绝不调用 OCR**，一行都不会。

扫描版怎么办：识别出来、如实标注、交给后续的 OCR 通道
----------------------------------------------------
F1.2 要求把扫描版判出来（`source_type = pdf_scan`）。本批次只做判定：
**均匀抽样若干页**，只有当抽样页"**几乎没有文本层**"**且**"**确实有图像内容**"
两个条件同时成立时才判扫描版，产出**空块表** + 一条高优先级存疑说明。
这里刻意**不抛异常**（扫描版是合法材料，不是用户错误），也**不悄悄走 OCR**
（依赖几个 GB，且会污染 A1-2 的口径）。

⚠️ 判决口径（**误判与漏判的代价不对称，所以口径刻意偏向漏判**）：
  · **只要抽样页里存在可读文本（哪怕十几个字）→ 一律 `pdf_text`**，正常产块；
  · 只有"抽样页提取到的文本**几乎为 0**（真正的扫描件：不存在文本层）**且**
    确实含图像"两个条件同时成立，才判 `pdf_scan`。
为什么这么定：**误判的代价是整份材料零产物** —— 一份明明能读的讲义被判成
扫描件，用户看到"解析成功"却拿不到任何内容，还会拿着同一个文件反复重试，
这是本模块最坏的失败模式；而漏判（把扫描件当文本版）只是少几个块、少一条
扫描提示，产物为空/极少时人工一眼就能发现。所以取"**宁松勿紧**"：
宁可漏判扫描件，绝不误判。判据取"没文本层 **且** 有图"的合取，
方向是"**有文本层就不是扫描版**"，与 A1-2「文本层 PDF 绝不走 OCR」同向。

页眉 / 页脚 / 页码去噪、heading 否决、图注识别（第二批已落地）
-----------------------------------------------------------
**实测样本**（真实教材 `Computer Networks: A Systems Approach, Release Version 6.1`，
489 页 LaTeX 版，取前 30 页为样本）**改前 → 改后**：

| 指标 | 第一批（改前） | 本批（改后） |
|---|---|---|
| 页眉块 / 页码块 / 页脚带块 | 24 / 32 / 52（分类计数和 108，去重后 82） | 0 / 0 / 0 |
| 正文覆盖率（正文区口径） | 102.93% | 99.99%（≈1.000） |
| 章数 / 节数 | 34 / 63 | 2 / 21 |
| `image_caption` 块 | 0（13 块全判 `paragraph`） | 12（剩下 1 块是正文，见下） |
| 总块数 | 307 | 225 |

改后的 2 章 / 21 节里，**11 节是 Chapter 1 的真实结构**
（1.1 导语 + 1.1.1 + 1.2 导语 + 1.2.1–1.2.5 + 1.3 导语 + 1.3.1–1.3.2），
其余来自封面书名行与 PREFACE 等前置标题 —— 这些都是**真实的标题行**，
不是页码冒充出来的假章（第一批那 34 章才是）。封面书名行仍会被字号法判成
一级标题、因而多出一个"章"，属于字号法标题检测的已知代价，**不在本批范围**。

**四条去噪信号是"合取"，缺一不可**（单看任何一条都必然误删正文）：

  1. **页边距带**：块顶边落在页高外侧 9%（页眉带）/ 内侧 91%（页脚带）之外。
     这是一道**便宜的预筛**，用来给下一步的"版心"计算取种子；
  2. **版心外**：块在**本文档自己**的正文纵向范围之外 —— 正文范围由第 1 步的
     非候选块现算（`body_lo` / `body_hi`），不写死任何页尺寸常量。
     有了它，"页首/页脚长什么样"由**文档自身**决定，换一种版式也成立；
  3. **跨页重复**：同一垂直位置（±`RUNNING_BAND_TOLERANCE` pt）在
     **≥ 50% 的页面**上都出现同类短行 —— 页眉页脚是"每页都来一遍"的东西，
     而表格跨页的续表表头只在表格跨了几页就出现几页；
  4. **与相邻内容隔离**：它与同页最近的字块之间的空隙 ≥ 1.4 个行高。
     表格续表表头下面**紧接着**就是表格行（正常行距），因此被这条挡在门外。

另外单列一条**页码**规则（`page_number` / `toc_number`）：单行的纯数字/罗马数字
短块，且**通过了上面 1+2+4 三条**，或位于本页是**目录页**（含 ≥4 条前导点行）。
把"整行只有数字"当页码**必须**配位置信号 —— 正文里也有孤立成行的数字
（如"共 3 个节点"被排版成单独一行），只认内容一定误删，见 `tests/test_parse_denoise.py`。

**heading 否决规则**：`_classify` 里，**整行只有编号、没有标题文字的单级编号**
不作 `heading`（孤立的 `37` 不得成为一级标题）。这直接堵住了第一批
"页码被判 `heading_level = 1`"的成因 —— 它让 30 页里的 34 章塌回 3 章。

**图注识别**：`Figure 1.1.: xxx` / `Table 2.1: xxx` 这类**带编号分隔符**的块判
`image_caption`。分隔符（`:` / `：`，允许 `.:`）是**必需**信号，不能只看
"以 Figure 开头"：真实教材 p14 有一段**正文**开头就是
`Figure 1.3 shows a pair of shows a set of nodes, ...`（628 字符），
它不是图注；只看前缀会把它错判成图注并**切碎正文**。长度上限
（`CAPTION_MAX_CHARS`）是第二道同样的护栏。

> 去噪**不静默丢内容**：去掉了几个块、分别属于哪一类，会写进
> `uncertain_notes`（`kind="other"` / `severity="low"`），可核对、可追责。
> 方向取舍与 F1.2 扫描判定一致：**宁可漏删，不可误删**。

headings 的来源：只有两个信号
-----------------------------
PDF 没有"标题"这个语义，只有字号和文字。本模块只认两个信号，其余一律当正文：
  1. **章节号**：`3.1` / `第1章` / `一、` 这类能拆出编号的行（`blocks.split_heading_number`）；
  2. **字号**：显著大于正文字号（正文 = 按字符数加权的众数字号）。
刻意**不用"加粗"**：正文整段加粗的排版很常见，用它会把正文误判成标题，
凭空多出一节 —— 而"节"是抽取的投喂单位，多一节比少一节的代价大。
已知代价：字号与正文相同、且不带编号的标题会被漏掉（记为纯文字块），
需要靠人工/后续版面模型补，见交付说明里的"不确定事项"。

编排单位是"块"，不是"行"
------------------------
PyMuPDF 的一个 text block 基本就是一段（段落或一栏里的连续行），但它的切分
**比排版直觉粗**：两段挨得近的独立段落经常被塞进同一个 block。所以这里先把
block 拆成**逐行**、再按统一的段落切分规则（`_is_continuation` 的四条判据：
同页 / 行距 ≤ 1.6× 行高 / 无首行缩进 / 上一行不以句末标点收尾）合并成段 ——
块内与跨块一视同仁。合并后用 `_join_lines` 拼文本：中文行之间不加空格、
拉丁文之间加空格 —— 一条行末断开的英文句子如果原样保留换行，下游按句读
切分时会切错。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path
from typing import Any

import pymupdf

from app.core.errors import ApiError, ErrorCode
from app.parse.blocks import (
    BBox,
    HeadingNumber,
    ParsedBlock,
    ParsedDocument,
    UncertainNote,
    split_heading_number,
)

# ---- 边界（SPEC / F1.2）----

#: 单次解析页数上限。超过就报错提示分批，**不静默截断** —— 静默截断会让
#: "这份材料抽出来的知识点怎么这么少"变成一个查不出来的问题。
MAX_PAGES = 100

#: 扫描版判定：抽样的页数（含首页与末页，均匀取样，保证可复现）。
#: 抽样而不是只看第一页：封面页往往"少字"甚至无字，只看首页必然误判；
#: 均匀取样能同时覆盖封面、正文中段与尾页。
SCAN_SAMPLE_PAGES = 5
#: 扫描版判定：抽样页"几乎没有文本层"的**必要**阈值（每页非空白字符数）。
#: 取 **1** 的含义是「一个可读字符都没有」—— 真正的扫描件整页就是一张位图，
#: 文本层里连一个字都不存在，读出来必然是 0；留下 1 只是为了挡住 `0` 与
#: "几乎为 0"之间的浮点/空白把戏（`_page_char_count` 已经去掉了所有空白）。
#:
#: ⚠️ 为什么从 20 降到 1（这是一次**故意的口径修正**）：
#:   · 判据是"抽样页**全都**低于阈值 且 抽样页里确实有图"，用 20 时，
#:     "第 1 页整页图 + 第 2 页一行 10 字真正文"这种材料会被**整体判成扫描版**，
#:     `blocks == []` —— 一份明明能读的讲义被整份丢弃，这是本模块最坏的失败
#:     模式：用户看到"解析成功"却拿不到任何内容。
#:   · 阈值越大，误判（把文本版当扫描件）的概率越高，而误判的代价
#:     （整份材料零产物）**远大于**漏判（把扫描件当文本版：少几个块、
#:     没有扫描提示，但产物为空/极少时人工一眼能发现）。
#: 所以口径明确取"**只要抽样页里存在可读文本，就不是扫描版**"，
#: 与 A1-2「文本层 PDF 绝不走 OCR」同向，方向是**宁松勿紧**。
#: 这个阈值只是必要条件之一，绝不能单独用来判扫描版（见模块 docstring）。
SCAN_MIN_CHARS_PER_PAGE = 1
#: 扫描版判定：已绘制图像的合计面积占页面面积达到此比例，也算"这一页有图"。
SCAN_IMAGE_AREA_RATIO = 0.5

#: 字号法判定标题：块内最大字号 ≥ 正文字号 + 这个增量。
HEADING_SIZE_DELTA = 1.5
#: 标题长度上限（字符）。再长就不是标题了，是正文被误判。
HEADING_MAX_CHARS = 100
#: 字号法判定标题时，最多允许几行。标题一般不跨很多行。
HEADING_MAX_LINES = 3

# ---- 封面装饰行否决（第三批）----
#
# 封面书名 / 副标题 / 作者行用的是全书**最大**的字号，字号法因此把它们判成
# 一级标题；而"章 = 最浅一层的标题"的骨架规则就会把封面书名两行当成两章。
# 实测（真实教材前 30 页）：改前 2 章 / 21 节，这"2 章"正是封面书名
# （`Computer Networks: A Systems` / `Approach`），真实结构只有 Chapter 1 一章。
#
# 判据是**合取**，缺一不可 —— 单看任何一条都会误伤真章标题：
#   ① 位于文档**前 `COVER_PAGES` 页**（封面 / 版权页）；
#   ② **没有编号**（`split_heading_number` 认不出章节号）；
#   ③ 字号 ≥ 正文字号 + `COVER_SIZE_DELTA`（明显大于正文）；
#   ④ 所在页的"普通字号块"不超过 `COVER_MAX_BODY_BLOCKS` 个 ——
#      封面页是"一屏大字 + 一个日期行"，而**章扉页**（实测第 9 页）上
#      紧跟着整页正文段落（9 个普通块），第 ④ 条把章扉页挡在门外。
# 方向与去噪一致：**宁可漏判一个真章标题，也不凭空造章**。
COVER_PAGES = 2
#: 封面装饰行的字号门槛（相对正文的增量）。取 2×`HEADING_SIZE_DELTA`：
#: 实测封面书名 24.8pt、副标题 / 作者 17.2pt、正文 10.9pt（门槛 = 13.9），
#: 而版权页的日期行 12.0pt 落在门槛之下（它本来就该是正文）。
COVER_SIZE_DELTA = 2 * HEADING_SIZE_DELTA
#: 封面页允许出现的"普通字号块"数上限。超过它就说明这页是**正文页**，
#: 不是封面 —— 即使页码很小也一样，宁可漏判。
COVER_MAX_BODY_BLOCKS = 1

# ---- 页眉 / 页脚 / 页码去噪（第二批）----
#
# 四条信号是**合取**：任何一条单独用都会误删正文（见模块 docstring）。下面每个
# 常量都为"宁可漏删不可误删"服务 —— 判不出来就不删，代价只是多几个噪声块。

#: 页边距带：块顶边在页高外侧这个比例内的，才有资格被当成页眉 / 页脚。
#:
#: 实测（真实教材 612×792）：页眉顶边 36.23（4.6%）、页脚顶边 741.50–743.09
#: （93.6–93.8%）、正文纵向范围 75.36–724.13（9.5–91.4%）。
#: 取 9% / 91% 让三类都留有余量：正文最低的那一行（75.36 = 9.5%）仍在带外，
#: 而页脚最高的一行（741.50 = 93.6%）仍在带内。
#:
#: 这本教材的页眉页脚离版心只有 18–29pt，所以这个比例不能取大；但它只是
#: **预筛**，真正的判定交给下面"版心外 + 跨页重复 + 与相邻内容隔离"三条。
EDGE_ZONE_TOP_RATIO = 0.09
EDGE_ZONE_BOTTOM_RATIO = 0.91
#: 页眉 / 页脚行的长度上限（字符）。页眉页脚都是**短行**（书名、章节名、页码），
#: 而正文段落即使首行落在页边距带里也远比这长 —— 这条把长段落挡在外面。
EDGE_LINE_MAX_CHARS = 120
#: 判定"同一条带"时，两个块顶边的最大间距（pt）。实测页脚在 741.50 与 743.09
#: 两处（相差 1.59pt），取 4pt 能收进同一条带又不会把相邻的正文行拉进来。
RUNNING_BAND_TOLERANCE = 4.0
#: 形成"跨页重复带"所需覆盖的页面比例。页眉页脚是**每页都来一遍**的东西：
#: 实测页眉 24/30 = 80%、页脚带 30/30 = 100%。而表格跨页的**续表表头**只在
#: 表格跨的那几页出现（远低于一半），因此被这一条挡在门外 —— 这是本批最关键的
#: 一条防误删信号，取 0.5 是有意的"宁严勿松"：比例越大越难被判成页眉页脚。
RUNNING_BAND_MIN_PAGE_RATIO = 0.5
#: 跨页重复带的**绝对**页数下限。少于这个页数的重复不足以证明是"每页都有"，
#: 小文档（3 页）靠它避免把"碰巧重了两页"的正文短行当成页眉。
RUNNING_BAND_MIN_PAGES = 3
#: 与相邻内容的隔离：候选块与同页最近字块的空隙 ≥ 这个倍数的行高。
#: 实测页眉 29.1pt / 行高 10.9 ≈ 2.67 倍、页脚 19.0 / 10.9 ≈ 1.74 倍，
#: 而正文的**段间距**只有 0.86 倍 —— 1.4 卡在两者之间。
#: 表格续表表头下面紧跟着表格行（正常行距 ≈ 0.9–1.0 倍），因此不会被误判。
EDGE_ISOLATION_RATIO = 1.4
#: 纯数字 / 罗马数字页码的长度上限（字符）。`26`、`iv`、`xii` 都在范围内。
PAGE_NUMBER_MAX_CHARS = 8
#: 页码形态：1–4 个数字，或 1–4 个罗马数字字母（`i` / `ii` / `xiv`）。
_PAGE_NUMBER_RE = re.compile(r"^(?:\d{1,4}|[ivxlcdmIVXLCDM]{1,4})$")
#: 目录页判定：一页里含这么多个"前导点"行（`. . . . .`）就当目录页。
#: 取 4 是因为正文里不会连续出现 4 行前导点；少于它的排版（如只有 2 条目录行）
#: 会漏判 —— 漏判只是目录页码多留几个块，方向仍是"宁漏勿误"。
TOC_LEADER_MIN_LINES = 4
#: 前导点行：5 个及以上的点（允许点之间夹空格），用于识别目录行。
_TOC_LEADER_RE = re.compile(r"\.(?:\s*\.){4,}")

# ---- 图注识别（第二批）----
#
# ⚠️ 只认"带编号分隔符"的图注（`Figure 1.1.: xxx` / `Table 2.1: xxx`），
# **不能**只看"以 Figure/Table 开头"：真实教材 p14 有一段正文正好以
# `Figure 1.3 shows a pair of ...` 开头（628 字符），它**不是**图注。
# 只看前缀会把它错判成 image_caption 并把一段正文切碎 —— 不可逆的内容破坏。
CAPTION_LABEL_RE = re.compile(
    r"^\s*(?:Figure|Fig\.|Table)\s+\d+(?:[.\-]\d+)*\s*\.?\s*[:：]\s*(?=\S)"
)
#: 图注长度上限（字符）。超过它就不再是图注，而是"图注与正文粘连"或纯正文。
CAPTION_MAX_CHARS = 300
#: 图注最多允许几行。图注一般一到两行。
CAPTION_MAX_LINES = 3

# ---- 多栏版面的阅读顺序（第四批）----
#
# 为什么需要它：`page.get_text("dict", sort=True)` 的 `sort` 是**全页按 y 再按 x**
# 排序，落在两栏页上会把左右两栏**逐行交错**。实测两栏样本（左栏 x≈60、右栏
# x≈330，各 3 行）拿到的块序是 `L1,R1,L2,R2,L3,R3`，而人读顺序是"整栏读完再读
# 下一栏"（`L1,L2,L3,R1,R2,R3`）。不修的话下游按 `seq` 顺序投喂 / 切分会在句子
# 中间左右横跳，A1-6 的行号溯源也会指到另一栏去。
#
# 修法是**只对多栏页重排**：先看本页有没有一条"整页没有任何块覆盖的纵向缝隙"
# （中缝）—— 有且两侧都有足够多的块，才判多栏并按栏重排（栏内保持原有相对顺序
# ＝ y 升序，栏间按 x 升序）；否则**原样返回**。
# ⚠️ 单栏文档因此走的是与改动前**逐字节相同**的分支（根本走不到重排那段代码），
# 覆盖率 / 去噪 / 章级骨架都不受影响 —— 这是"保守优先"的核心保证。
#
# 为什么中缝判据用"整页零覆盖"而不是"块左边界聚类"：零覆盖意味着
# **没有任何块横跨这条缝**，因此天然挡住两类误判 ——
#   · 通栏标题（一块横跨两栏）会让中缝消失 → 本页不重排，保持现状；
#   · 单栏页里"表格 / 图旁边的窄块"仍被上下的通栏正文覆盖 → 也不会凭空多一条缝。
# 方向与去噪一致：**宁可漏判（继续交错），不可误判（把单栏顺序改错）**。

#: 判多栏所需的最少块数。块太少时"中缝"多半只是偶然的空档（一页只有两三个
#: 短块），样本不足不判多栏。
COLUMN_MIN_BLOCKS = 4
#: 每栏至少要有这么多块，才认两侧都是"真的一栏"而不是零碎空档。
COLUMN_MIN_BLOCKS_PER_SIDE = 2
#: 中缝（整页零覆盖的纵向缝隙）的宽度下限，占**本页内容横向跨度**的比例。
#: 实测两栏样本：内容跨度 60→445、中缝 175→330（≈35%）；真实两栏讲义的中缝
#: 一般也在 4% 以上。取 4% 是有意的"宁漏勿误"：漏判只是回到现在的交错顺序，
#: 误判则会把单栏页里的偶然空档当成中缝、把正确的顺序改错。
COLUMN_GUTTER_MIN_RATIO = 0.04

#: 同段折行合并：下一块首行与本块末行的"行距"上限，以本块行高为单位。
#: 单倍行距的折行约为行高的 1.0–1.35 倍（行高 ≈ 字号 × 1.2，行距 ≈ 字号 × 1.2–1.5），
#: 而段间距普遍 ≥ 1.5 个行高。1.6 落在两者之间：收得住折行，吃不掉段间距。
PARAGRAPH_MERGE_MAX_LINE_GAP_RATIO = 1.6
#: 首行缩进判定：下一块首行左边界比本块右移超过这个倍数的行高，视为
#: "新段落的首行缩进"，不再合并。（折行的续行与本段首行左边界对齐，
#: 不会右移；中文段落首行缩进两个字 ≈ 1.67 个行高。）
PARAGRAPH_INDENT_RATIO = 1.5
#: **块内**折行护栏：上一行右边界距离"本块的右边界"不超过这个倍数的行高，
#: 才算"这一行排满了"。排满的行**不会**被句末标点拆段 —— 中文排版里折行断在
#: 句末标点非常常见（一行正好排到句号处），把这种断行当段落边界，会把一段
#: 单倍行距的正文按行剁成十几个块（实测 20 页讲义 → 240 块），
#: 段落完整性直接没了。
#: 取 1.25 的依据：行高 ≈ 1.2 × 字号，1.25 个行高 ≈ 1.5 个汉字宽 ——
#: 真正排满的行不会差到一个半汉字（差一个汉字就该换行了），而**段落末行**
#: 通常短得多。方向仍然是"宁合勿分"：判不出"没排满"就按同一段处理，
#: 段落边界丢一个总比把一段话剁碎好。
PARAGRAPH_FULL_LINE_TOLERANCE_RATIO = 1.25
#: 句末标点（允许后面跟右引号 / 右括号）。上一块以此收尾说明这句话
#: 已经写完，下一块大概率是新段落 —— 属于"明显的段落起始特征"。
#: 只认**句末**标点，不认逗号/顿号：折行绝大多数时候断在逗号或词中间，
#: 认逗号等于把要合并的情形全部挡在门外。
_SENTENCE_END_RE = re.compile(r"[。．.！!？?；;][\"'”’」』）)]*$")

_CJK_RE = re.compile(
    r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
)


# ---------------------------------------------------------------------------
# 打开文件：加密 / 损坏都要给出能直接展示的中文
# ---------------------------------------------------------------------------


def _open_pdf(path: str | Path) -> pymupdf.Document:
    """打开 PDF。加密、损坏、空文件全部转成中文 `ApiError`。"""
    try:
        doc = pymupdf.open(path)
    except pymupdf.EmptyFileError as exc:
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            "这个 PDF 是空文件，里面没有内容，请重新导出后再上传",
        ) from exc
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            "这个 PDF 文件已损坏或不是有效的 PDF，无法打开，请重新导出后再上传",
        ) from exc
    except Exception as exc:  # noqa: BLE001 —— 兜底，见下
        # 前面没料到的情况（异常类型在 pymupdf 版本间不稳定）也要收口成中文
        # `ApiError`：漏出去的原生异常会绕过全局异常处理器，前端只看到英文 500。
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            "这个 PDF 打不开（文件可能已损坏或不是有效的 PDF），请重新导出后再上传",
        ) from exc

    # 加密：needs_pass=True 表示要密码才能读内容。我们不猜密码、不静默跳过。
    if doc.needs_pass:
        doc.close()
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            "这个 PDF 已加密，无法解析，请先解除密码保护后再上传",
        )
    return doc


# ---------------------------------------------------------------------------
# 原文抽取
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RawBlock:
    """PyMuPDF 的一个 text block，尚未判断是不是标题。

    除了文本，还留下**行级几何**（`first_top` / `last_top` / `left` /
    `line_height`）：判断两个块是不是同一段的折行，靠的就是这些量，
    不能只看文本 —— 文本里没有"这两行挨得有多近"这个信息。
    """

    page_no: int
    bbox: BBox | None
    text: str
    line_start: int | None
    line_end: int | None
    line_count: int
    max_size: float
    first_top: float | None = None
    last_top: float | None = None
    left: float | None = None
    line_height: float | None = None
    #: **末行**的右边界（`_merge_raw` 会更新它）。判断"这一行有没有排满"
    #: 必须看末行，不能用 bbox 的并集宽度 —— 并集会把组内更宽的那一行算进来。
    last_right: float | None = None


def _join_lines(lines: list[str]) -> str:
    """合并段落内的折行。

    中文之间不插空格（`网络` + `层` 拼成 `网络层`），其余情况插一个空格
    （`routing` + `basics` 拼成 `routing basics`）。只在**前一个字符是
    ASCII、后一个字符也是 ASCII** 时插空格，规则单一、可预测。
    """
    out = ""
    for raw in lines:
        piece = raw.strip()
        if not piece:
            continue
        if not out:
            out = piece
            continue
        out += (" " if not _CJK_RE.search(out[-1]) and not _CJK_RE.search(piece[0]) else "") + piece
    return out


def _line_raws(
    raw_blk: dict[str, Any], page_no: int
) -> tuple[list[_RawBlock], dict[float, int]]:
    """把一个 PyMuPDF text block 拆成**逐行**的 `_RawBlock`（行号按块内相对序号 1..n）。

    为什么要拆到行：PyMuPDF 对 text block 的切分比排版直觉粗 —— 两段挨得近的
    **独立段落**经常被塞进同一个 block。如果只对整块 `_join_lines`，段落切分
    规则（`_is_continuation` 的四条判据）就永远没机会执行：规则 4"上一块以
    句末标点收尾 → 下一块是新段落"只在**跨 block** 时生效，于是两段被无条件
    并成一段，`source_quote` 与段落边界一起丢。

    拆到行之后，块内与跨块走**同一套**判据（先逐行判"是不是上一行的续行"，
    再合并成段），折行仍然被合并 —— 三道折行护栏都还在：行距 ≤ 1.6× 行高、
    无首行缩进、以及"上一行排满了右边界时不以句末标点断段"（`_is_full_line`），
    真折行不会被拆散。

    同时回报该块的「字号 → 字符数」增量：字号直方图按字符数加权，汇总时
    直接累加即可（与逐块统计等价）。
    """
    raws: list[_RawBlock] = []
    size_chars: dict[float, int] = {}

    for line in raw_blk.get("lines", []):
        spans = line.get("spans", [])
        if not spans:
            continue
        # 逐行先 strip：`_SENTENCE_END_RE` 用 `$` 收尾，行尾的排版空格会让
        # "以句末标点收尾"这条判据失效（它只认标点，不认标点后面的空格）。
        text = "".join(span.get("text", "") for span in spans).strip()
        if not text:
            continue

        box = line.get("bbox")
        bbox: BBox | None = tuple(float(v) for v in box) if box and len(box) == 4 else None

        max_size = 0.0
        for span in spans:
            size = round(float(span.get("size", 0.0)), 1)
            size_chars[size] = size_chars.get(size, 0) + len(span.get("text", ""))
            max_size = max(max_size, size)

        index = len(raws) + 1  # 行号只数**真正产出的行**，与 line_cursor 的口径一致
        raws.append(
            _RawBlock(
                page_no=page_no,
                bbox=bbox,
                text=text,
                line_start=index,
                line_end=index,
                line_count=1,
                max_size=max_size,
                # 单行块的首行顶边 = 末行顶边 = 该行顶边；行高取该行 bbox 高度
                first_top=bbox[1] if bbox else None,
                last_top=bbox[1] if bbox else None,
                left=bbox[0] if bbox else None,
                line_height=(bbox[3] - bbox[1]) if bbox else None,
                last_right=bbox[2] if bbox else None,
            )
        )

    return raws, size_chars


def _split_caption_glue(lines: list[_RawBlock]) -> list[list[_RawBlock]]:
    """把"图注 + 紧随正文"粘连的一段行拆成两组，供 `_group_lines` 分别成段。

    为什么需要：图注以句末标点收尾时，`_is_continuation` 的第 4 条判据本来就会
    止住合并；但图注**不以标点收尾**时（`... (b) multiple-access` 这类），
    段判据只看版式、看不出"图注到此为止"，图注就会被并进后面那段正文，
    于是图注整块消失、变成正文的第一句。

    切点取**第一行之后**：本教材（以及绝大多数 LaTeX / Word 排版）的图注都是
    **单行**，粘连时第一行就是图注。切点是整行边界，不按字符切 —— 按字符切会让
    上下两块的 `line_start` / `line_end` 指向同一行，溯源直接错位。

    多行图注的粘连会切不干净（图注的续行留在正文里）：那只是"图注少了一行"，
    **正文一个字都不丢**。方向仍是"宁可漏切，不可错切"（错切是把一句话劈开）。
    """
    if len(lines) < 2 or not CAPTION_LABEL_RE.match(lines[0].text):
        return [lines]
    return [lines[:1], lines[1:]]


def _group_lines(lines: list[_RawBlock]) -> list[_RawBlock]:
    """把一个 text block 内的逐行块按 `_is_continuation` 组成段。

    与跨 block 的 `_merge_continuation_lines` 用**同一套**判据 —— 这正是
    "同一 text block 内的多行被无条件拼接"的修法：段落切分规则不再只在
    跨 block 时生效，块内也一视同仁。

    唯一的差别是这里多传入"本块的右边界"（`_is_continuation` 的 `block_right`）：
    块内才知道同一条排版行的邻居有多宽，"这一行有没有排满"这个折行护栏
    只有在块内才有参照物（跨 block 时参照物不同，护栏自动不生效）。

    行几何缺失时（没有 bbox）`_is_continuation` 一律返回 False，会把每行拆成
    独立的块；`_raw_blocks` 对这种情况有兜底（退回按块整块合并）。
    """
    rights = [line.last_right for line in lines if line.last_right is not None]
    block_right = max(rights) if rights else None

    merged: list[_RawBlock] = []
    for raw in lines:
        if merged and _is_continuation(merged[-1], raw, block_right=block_right):
            merged[-1] = _merge_raw(merged[-1], raw)
        else:
            merged.append(raw)
    return merged


def _column_gutter(boxes: list[tuple[float, float]]) -> float | None:
    """本页最宽的"中缝"横向中心；没有合格中缝时返回 None。

    `boxes` 是各块的 `(左边界, 右边界)`。中缝 = 一段**整页没有任何块覆盖**的 x
    区间（做法：把所有 x 区间投影到 x 轴上求并集，再取并集里的空洞）。
    取最宽的一条空洞，要求宽度 ≥ `COLUMN_GUTTER_MIN_RATIO` × 内容横向跨度。

    "整页零覆盖"是关键：它同时保证"没有块横跨这条缝"（否则缝里会有覆盖），
    于是跨越中缝的通栏标题 / 通栏图会让本页判不出多栏 —— 那种页**不重排**。
    """
    intervals = [(left, right) for left, right in boxes if right > left]
    if not intervals:
        return None
    lo = min(left for left, _ in intervals)
    hi = max(right for _, right in intervals)
    span = hi - lo
    if span <= 0:
        return None

    events: list[tuple[float, int]] = []
    for left, right in intervals:
        events.append((left, 1))
        events.append((right, -1))
    events.sort()

    # 扫出一段段"有覆盖"的区间；两段覆盖之间的空洞就是候选中缝。
    covered: list[tuple[float, float]] = []
    depth = 0
    start = lo
    for x, delta in events:
        if depth == 0:
            start = x
        depth += delta
        if depth == 0:
            covered.append((start, x))

    best = 0.0
    center: float | None = None
    for (_, prev_right), (next_left, _) in zip(covered, covered[1:]):
        width = next_left - prev_right
        if width > best:
            best = width
            center = (prev_right + next_left) / 2.0
    if center is None or best < COLUMN_GUTTER_MIN_RATIO * span:
        return None
    return center


def _reading_order_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把一个页面内的 text block 排成**阅读顺序**：多栏页按栏，单栏页原样。

    多栏页的重排规则：找到最宽的中缝 → 把块按"右边界 ≤ 缝心 / 左边界 ≥ 缝心"
    分成左右两组 → 左边整组在前、右边整组在后（组内保持原有相对顺序，而
    `sort=True` 的原顺序已是 y 升序，因此栏内自然就是 y 升序）。
    对左右两组**递归**处理，所以三栏及以上（相邻栏之间都有中缝）也成立。

    任一条件不满足就**原样返回**（顺序与改动前逐字节相同）：块数不足、
    有块缺 `bbox`、找不到合格中缝、或某一侧的块数少于
    `COLUMN_MIN_BLOCKS_PER_SIDE`。方向是"宁可漏判，不可误判"。
    """
    if len(blocks) < COLUMN_MIN_BLOCKS:
        return blocks

    boxes: list[tuple[float, float]] = []
    for block in blocks:
        box = block.get("bbox")
        if not box or len(box) != 4:
            return blocks  # 有块没有几何信息 → 判不了版面，别赌
        boxes.append((float(box[0]), float(box[2])))

    split = _column_gutter(boxes)
    if split is None:
        return blocks

    left = [block for block, (_, hi_x) in zip(blocks, boxes) if hi_x <= split]
    right = [block for block, (lo_x, _) in zip(blocks, boxes) if lo_x >= split]
    if len(left) < COLUMN_MIN_BLOCKS_PER_SIDE or len(right) < COLUMN_MIN_BLOCKS_PER_SIDE:
        return blocks
    if len(left) + len(right) != len(blocks):
        # 中缝零覆盖意味着不该有块落在缝心里 —— 真出现了就说明判据被绕过，不重排。
        return blocks

    return _reading_order_blocks(left) + _reading_order_blocks(right)


def _raw_blocks(doc: pymupdf.Document) -> tuple[list[_RawBlock], dict[float, int], int]:
    """逐页抽块。

    返回 `(块列表, 字号→字符数, 图片块数)`。
    字号直方图按**字符数**加权而不是按出现次数 —— 一页里可能有大量零碎的
    小字号页码/页眉，按次数统计会把正文挤出众数。

    段落边界在**行级**判定（先把 block 拆成行、再按同一套判据合并成段），
    所以两段挨得近的独立段落不会被 PyMuPDF 的 block 边界连坐（见 `_line_raws`）。
    """
    raws: list[_RawBlock] = []
    size_chars: dict[float, int] = {}
    image_count = 0

    for page_index in range(doc.page_count):
        page = doc[page_index]
        page_no = page_index + 1  # 1-based（A1-6）
        data = page.get_text("dict", sort=True)  # sort=True：按阅读顺序，保证可复现
        line_cursor = 0

        page_blocks = data.get("blocks", [])
        # 图片块只计数、不产出内容；文本块交给 `_reading_order_blocks` 排阅读顺序
        # （单栏页原样返回，多栏页按栏重排 —— 见该函数与上方常量区的说明）。
        image_count += sum(1 for raw_blk in page_blocks if raw_blk.get("type") != 0)
        for raw_blk in _reading_order_blocks(
            [raw_blk for raw_blk in page_blocks if raw_blk.get("type") == 0]
        ):
            line_raws, block_sizes = _line_raws(raw_blk, page_no)
            for size, chars in block_sizes.items():
                size_chars[size] = size_chars.get(size, 0) + chars
            if not line_raws:
                continue

            if any(raw.first_top is None for raw in line_raws):
                # 行几何缺失 → 判不出段边界。这时**退回块级**：整块当一段。
                # 宁可少切一段，也不要因为没有几何信息就把一段话拆散。
                merged_blocks = [_merge_line_group(line_raws)]
            else:
                # 图注写完了就先切开，再让两半各自走同一套段落判据 —— 否则
                # "图注不以句末标点收尾"时它会被并进后面的正文段，整块消失。
                merged_blocks = [
                    group
                    for part in _split_caption_glue(line_raws)
                    for group in _group_lines(part)
                ]

            for group in merged_blocks:
                raws.append(
                    replace(
                        group,
                        line_start=(group.line_start or 1) + line_cursor,
                        line_end=(group.line_end or 1) + line_cursor,
                    )
                )
            line_cursor += len(line_raws)

    return raws, size_chars, image_count


def _merge_line_group(lines: list[_RawBlock]) -> _RawBlock:
    """把一段行（几何信息缺失时的整块）无条件合并成一个块。"""
    merged = lines[0]
    for raw in lines[1:]:
        merged = _merge_raw(merged, raw)
    return merged


def _body_size(size_chars: dict[float, int]) -> float:
    """正文（正文字号）的估计值：按字符数加权的众数字号。

    并列时取**较小**的字号 —— 宁可把正文估小一点（那样只会有更多块被判成
    大字号块、即更多标题），也不要估大（那会把真标题漏成正文，节骨架直接塌掉）。
    """
    if not size_chars:
        return 0.0
    return max(size_chars.items(), key=lambda kv: (kv[1], -kv[0]))[0]


# ---------------------------------------------------------------------------
# 页眉 / 页脚 / 页码去噪（第二批）
# ---------------------------------------------------------------------------
#
# 判定是**四条信号的合取**（模块 docstring 有完整推理）：
#   ① 页边距带（便宜预筛）→ ② 版心外（由本文档现算）→ ③ 跨页重复 → ④ 与相邻内容隔离
# 少任何一条都会误删正文：只看 ① 会把"正文首行恰好排在版心上方"删掉；
# 只看 ③ 会把表格跨页的**续表表头**删掉（那是正文的一部分）。
# 方向与 F1.2 扫描判定一致：**宁可漏删，不可误删**。


@dataclass(frozen=True)
class _DenoiseReport:
    """去噪去掉了什么 —— 让"删了东西"这件事可解释、可核对，不静默丢内容。

    四个字段是**互不相交的划分**（合计 = 被删块数）。注意任务书里的
    "页眉 24 + 页码 32 + 页脚 52 = 108"是**分类计数之和**，其中页码有 26 块
    本来就在页脚带里，所以 108 > 实际块数 82 —— 本报告不重复计数。
    """

    header: int = 0
    footer: int = 0
    page_number: int = 0
    toc_number: int = 0

    @property
    def total(self) -> int:
        return self.header + self.footer + self.page_number + self.toc_number

    def describe(self) -> str:
        return (
            f"页眉 {self.header} 块、页脚 running head {self.footer} 块、"
            f"页边距带页码 {self.page_number} 块、目录页页码 {self.toc_number} 块"
        )


@dataclass(frozen=True)
class _EdgeBands:
    """本文档**自己**的页眉 / 页脚位置与版心范围（由版式现算，不写死页尺寸）。"""

    positions: tuple[float, ...]
    body_lo: float
    body_hi: float

    def covers(self, top: float) -> bool:
        """`top` 是否落在某条已检出的页眉 / 页脚带上。"""
        return any(abs(top - position) <= RUNNING_BAND_TOLERANCE for position in self.positions)


def _toc_pages(doc: pymupdf.Document) -> frozenset[int]:
    """目录页（1-based）：含 ≥ `TOC_LEADER_MIN_LINES` 条"前导点行"的页。

    目录行的版式特征是 `1.5 Performance . . . . . . 37` —— 点之间带空格。
    前导点是**结构信号**，正文里不会连续出现 4 行以上；用它认目录页，
    比"行尾跟页码"可靠（本教材的目录页码在**行首**，用行尾判会数出 0 行）。
    """
    pages: set[int] = set()
    for index in range(doc.page_count):
        leaders = sum(
            1
            for line in doc[index].get_text("text").splitlines()
            if _TOC_LEADER_RE.search(line)
        )
        if leaders >= TOC_LEADER_MIN_LINES:
            pages.add(index + 1)
    return frozenset(pages)


def _median_line_height(raws: list[_RawBlock]) -> float:
    """行高的中位数 —— "与相邻内容隔离"这条信号的尺子，用中位数不用均值，
    免得少数大字号标题把尺子拉长。"""
    heights = sorted(h for h in (raw.line_height for raw in raws) if h and h > 0)
    if not heights:
        return 0.0
    return heights[len(heights) // 2]


def _same_line(a: _RawBlock, b: _RawBlock) -> bool:
    """两个块是不是排在同一行上（纵向区间显著重叠）。

    这一条是为页脚准备的：PyMuPDF 把页脚切成 `6` 与 `Chapter 1. Foundation`
    两个块，它们**同顶边**、横向并排。算"隔离距离"时必须把它们视作同一行，
    否则两者之间的空隙是 0，页脚会被自己的另一半判成"不隔离"。
    """
    if a.bbox is None or b.bbox is None:
        return False
    overlap = min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1])
    shorter = min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1])
    return shorter > 0 and overlap / shorter >= 0.5


def _isolation_gap(raw: _RawBlock, page_blocks: list[_RawBlock]) -> float:
    """`raw` 与同页最近字块之间的垂直空隙（pt）；没有邻居时返回正无穷。

    "页眉 / 页脚"与"表格跨页的续表表头"在文本与位置上可能一模一样，区别在
    **隔离度**：页眉页脚与版心之间有一道明显的空白，表格表头下面紧跟着表格行
    （正常行距）。这是防"把续表表头删掉"的那条信号。
    """
    gap = float("inf")
    for other in page_blocks:
        if other is raw or _same_line(raw, other) or other.bbox is None or raw.bbox is None:
            continue
        if other.bbox[3] <= raw.bbox[1]:  # 在 raw 上方
            gap = min(gap, raw.bbox[1] - other.bbox[3])
        elif other.bbox[1] >= raw.bbox[3]:  # 在 raw 下方
            gap = min(gap, other.bbox[1] - raw.bbox[3])
    return gap


def _is_edge_candidate(raw: _RawBlock, top_limit: float, bottom_limit: float) -> bool:
    """信号①：落在页边距带里的**单行短块**（页眉 / 页脚 / 页码的形态）。

    "单行 + 短"这一条不能省：正文段落的首行也可能排在版心上方，
    但它不会是"一行、120 字符以内"。
    """
    if raw.first_top is None or raw.line_count != 1:
        return False
    if not raw.text.strip() or len(raw.text) > EDGE_LINE_MAX_CHARS:
        return False
    return raw.first_top < top_limit or raw.first_top > bottom_limit


def _detect_edge_bands(
    raws: list[_RawBlock], page_height: float, page_count: int
) -> _EdgeBands | None:
    """找出本文档的页眉 / 页脚带（信号 ①②③ 的落点）。判不出返回 None。

    步骤：
      1. 用**页边距带**（信号①）挑出候选短行 —— 这是一道便宜的预筛；
      2. 用**非候选块**的纵向范围现算版心 `[body_lo, body_hi]` —— 这样"页眉页脚
         长什么样"由文档自身决定，换版式（A4 / 教材 / 讲义）都成立；
      3. 候选块里，落在版心外的，按顶边聚类（±`RUNNING_BAND_TOLERANCE`）；
      4. 覆盖 **≥ `RUNNING_BAND_MIN_PAGE_RATIO` 的页面**（且不少于
         `RUNNING_BAND_MIN_PAGES` 页）的簇才成"带"—— 页眉页脚每页都来一遍，
         表格的续表表头只跟表格跨的那几页，靠这条区分开。
    """
    if page_height <= 0 or page_count <= 0:
        return None

    top_limit = EDGE_ZONE_TOP_RATIO * page_height
    bottom_limit = EDGE_ZONE_BOTTOM_RATIO * page_height
    indices = {
        index
        for index, raw in enumerate(raws)
        if _is_edge_candidate(raw, top_limit, bottom_limit)
    }
    if not indices:
        return None

    body_tops = [
        raw.first_top
        for index, raw in enumerate(raws)
        if index not in indices and raw.first_top is not None
    ]
    if not body_tops:
        return None
    body_lo, body_hi = min(body_tops), max(body_tops)

    outside = [
        (raws[index].first_top, raws[index].page_no)
        for index in indices
        if raws[index].first_top < body_lo or raws[index].first_top > body_hi
    ]
    if not outside:
        return None

    clusters: list[list[tuple[float, int]]] = []
    for top, page_no in sorted(outside):
        # ⚠️ 与簇的**首个**顶边比，不跟"上一个成员"比 —— 后者会像链条一样一路
        # 漂移过去（743 → 747 → 751 → …），把整页的行都串进同一条"带"里。
        if clusters and top - clusters[-1][0][0] <= RUNNING_BAND_TOLERANCE:
            clusters[-1].append((top, page_no))
        else:
            clusters.append([(top, page_no)])

    needed = max(RUNNING_BAND_MIN_PAGES, ceil(RUNNING_BAND_MIN_PAGE_RATIO * page_count))
    positions = tuple(
        sum(top for top, _ in cluster) / len(cluster)
        for cluster in clusters
        if len({page_no for _, page_no in cluster}) >= needed
    )
    if not positions:
        return None
    return _EdgeBands(positions=positions, body_lo=body_lo, body_hi=body_hi)


def _denoise(
    raws: list[_RawBlock], doc: pymupdf.Document
) -> tuple[list[_RawBlock], _DenoiseReport]:
    """去掉页眉 / 页脚 / 页码，返回 `(保留的块, 去噪报告)`。

    规则有两条，都要求**多信号同时成立**：

      A. **页眉 / 页脚 / 页脚页码**：单行短块 ∧ 在页边距带 ∧ 在版心外
         ∧ 落在跨页重复带上 ∧ 与相邻内容隔离 ≥ `EDGE_ISOLATION_RATIO` 个行高；
      B. **目录页页码**：所在页是目录页（≥ `TOC_LEADER_MIN_LINES` 条前导点行）
         ∧ 单行 ∧ 内容是纯数字/罗马数字。

    规则 B 不要求位置信号（目录页码就排在版心里、紧贴着自己的目录行），
    因此**必须**用"目录页"这个结构信号兜住，否则会把正文里孤立成行的数字一起删掉。
    """
    page_count = doc.page_count
    page_height = max((doc[index].rect.height for index in range(page_count)), default=0.0)
    toc_pages = _toc_pages(doc)
    bands = _detect_edge_bands(raws, page_height, page_count)
    line_height = _median_line_height(raws)
    isolation_limit = EDGE_ISOLATION_RATIO * line_height

    by_page: dict[int, list[_RawBlock]] = {}
    for raw in raws:
        by_page.setdefault(raw.page_no, []).append(raw)

    kept: list[_RawBlock] = []
    counts = {"header": 0, "footer": 0, "page_number": 0, "toc_number": 0}
    for raw in raws:
        stripped = raw.text.strip()
        is_number = bool(_PAGE_NUMBER_RE.match(stripped))
        short_single = (
            raw.first_top is not None
            and raw.line_count == 1
            and 0 < len(raw.text) <= EDGE_LINE_MAX_CHARS
        )

        if bands is not None and short_single and bands.covers(raw.first_top):
            outside_body = raw.first_top < bands.body_lo or raw.first_top > bands.body_hi
            isolated = _isolation_gap(raw, by_page.get(raw.page_no, [])) >= isolation_limit
            if outside_body and isolated:
                if raw.first_top < bands.body_lo:
                    counts["header"] += 1
                else:
                    counts["page_number" if is_number else "footer"] += 1
                continue

        if short_single and is_number and raw.page_no in toc_pages:
            counts["toc_number"] += 1
            continue

        kept.append(raw)

    return kept, _DenoiseReport(**counts)


def _cover_decorations(raws: list[_RawBlock], body_size: float) -> frozenset[int]:
    """挑出"封面装饰行"的下标 —— 这些块**不判 heading**（判据见上方常量区）。

    为什么必须在这里（分类前）否决，而不是在骨架阶段"合并"：字号法一旦把它们
    判成一级标题，"章 = 最浅一层标题"的规则就会一路错下去（骨架错位不报错）。
    在分类这一层否决最省事，也最容易用单块级别的用例钉住。

    第 ④ 条（"这一页普通字号块很少"）是**唯一**能把封面与章扉页分开的信号：
    两者都是"大字 + 无编号 + 靠页首"，区别在于封面整页只有大字与一个日期行，
    章扉页后面紧跟着整页正文。没有它就会把每一章的扉页标题一起否决掉 ——
    那属于"漏判真章"，虽然方向可接受，但没有必要付这个代价。
    """
    if body_size <= 0:
        return frozenset()

    threshold = body_size + COVER_SIZE_DELTA
    bodyish: dict[int, int] = {}
    for raw in raws:
        if raw.max_size < threshold:
            bodyish[raw.page_no] = bodyish.get(raw.page_no, 0) + 1

    out: set[int] = set()
    for index, raw in enumerate(raws):
        if raw.page_no > COVER_PAGES:
            continue
        if raw.max_size < threshold:
            continue
        if split_heading_number(raw.text) is not None:
            continue
        if bodyish.get(raw.page_no, 0) > COVER_MAX_BODY_BLOCKS:
            continue
        out.add(index)
    return frozenset(out)


def _sample_page_indices(page_count: int, limit: int) -> list[int]:
    """均匀取样页下标（0-based），含首页与末页，结果可复现。"""
    if page_count <= 0:
        return []
    if page_count <= limit:
        return list(range(page_count))
    step = (page_count - 1) / (limit - 1)
    return sorted({int(round(i * step)) for i in range(limit)})


def _page_char_count(page: pymupdf.Page) -> int:
    """一页的文本层字符数（去掉所有空白，避免排版空格把扫描版"救活"）。"""
    return len("".join(page.get_text("text").split()))


def _page_has_image_content(page: pymupdf.Page) -> bool:
    """这一页**确实有图像内容**吗？两个信号任一成立即算有。

    判定方向是"有没有图"，所以宁松勿紧（漏判会导致真扫描件走到文本分支，
    抽出 0 个块却什么都不说）：
      1. 页面引用了图像 XObject（`get_images()` 非空）—— 扫描件的一整页
         就是一张图，必然命中；这也是唯一能覆盖"小图 + 大片白底"的信号。
      2. 实际绘制出来的图像矩形合计面积 ≥ 页面的 `SCAN_IMAGE_AREA_RATIO`
         —— 兜住"图只在资源里、或只画了一小块"以外的整页插图情形。
    """
    if page.get_images():
        return True

    drawn = 0.0
    for info in page.get_image_info():
        box = info.get("bbox")
        if not box or len(box) != 4:
            continue
        x0, y0, x1, y1 = (float(v) for v in box)
        drawn += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    page_area = abs(float(page.rect.width) * float(page.rect.height))
    return page_area > 0 and drawn / page_area >= SCAN_IMAGE_AREA_RATIO


def _looks_like_scan(doc: pymupdf.Document) -> tuple[bool, list[int], int]:
    """抽样做**多信号**判定。返回 `(是否扫描版, 抽样页码(1-based), 抽样总字符数)`。

    判据是**合取**，两个条件同时成立才判扫描版：

      1. 抽样页的文本**几乎为 0**（每页字符数 < `SCAN_MIN_CHARS_PER_PAGE`，
         该阈值为 1，即"一个可读字符都没有"）—— 真正的扫描件不存在文本层；
      2. 抽样页里**确实有图像内容**（`_page_has_image_content`）。

    ❗**只要抽样页里存在可读文本（哪怕十几个字），一律判 `pdf_text`**，
    正常产块。这条取舍是刻意写死的，理由是不对称的代价：

      · **误判**（把能读的文本层 PDF 判成扫描版）：整份材料 `blocks == []`，
        用户看到"解析成功"却拿到零内容，还会拿着同一个文件反复重试 ——
        这是本模块最坏的失败模式，**绝不允许**。
      · **漏判**（把扫描件判成文本版）：少几个块、少一条扫描提示，
        而且产物为空时人工一眼就能发现并回报。

    所以阈值取到最小（1），方向是**宁松勿紧**：宁可漏判扫描件，绝不误判。
    这也是"有文本层就不是扫描版"的正向表达，与 A1-2「文本层 PDF 绝不走 OCR」
    完全同向。

    为什么不能反过来只看第 1 条（字符数）配一个大阈值：封面页、章节扉页、
    以图为主的排版页、多页少字的讲义，字符数也会很低，但它们是**能正常抽取
    的文本层 PDF**；第 2 条把这类"稀疏文本页"挡在外面（它们没有图）。
    抽样覆盖多页（`_sample_page_indices` 均匀取 `SCAN_SAMPLE_PAGES` 页，
    含首页与末页）：只看第一页会被"无字封面"骗到，只看最后一页会被空白尾页骗到。
    """
    indices = _sample_page_indices(doc.page_count, SCAN_SAMPLE_PAGES)
    if not indices:
        return False, [], 0

    pages = [doc[i] for i in indices]
    chars = [_page_char_count(page) for page in pages]
    has_text_layer = any(count >= SCAN_MIN_CHARS_PER_PAGE for count in chars)
    has_image_content = any(_page_has_image_content(page) for page in pages)
    return (not has_text_layer) and has_image_content, [i + 1 for i in indices], sum(chars)


def _classify(
    raw: _RawBlock,
    body_size: float,
    size_levels: dict[float, int],
) -> tuple[str, int | None]:
    """判断一个块是 heading / paragraph / image_caption，并给出 heading_level。"""
    # ---- 图注：先于标题判，图注永远不该变成 heading ----
    # 只看"以 Figure/Table 开头"是不够的：真实教材有一段**正文**正好以
    # `Figure 1.3 shows a pair of ...` 开头。所以要求编号后面必须跟分隔符
    # （`:` / `：`，允许 LaTeX 的 `.:`），再加一道长度上限。
    if (
        raw.line_count <= CAPTION_MAX_LINES
        and len(raw.text) <= CAPTION_MAX_CHARS
        and CAPTION_LABEL_RE.match(raw.text)
    ):
        return "image_caption", None

    number: HeadingNumber | None = None
    if len(raw.text) <= HEADING_MAX_CHARS and raw.line_count == 1:
        number = split_heading_number(raw.text)
        if number is not None:
            # ★ 否决规则（第二批）：**整行只有编号、没有标题文字的单级编号**
            # 不作 heading。孤立的 `37` 就是页码，不是"第 37 章" —— 第一批正是
            # 被它把节骨架打成了 34 章（真实结构只有 3 章）。
            # 只否决 depth==1：多级编号（`3.1`）本身就是强信号，且页码不会长成
            # 那个样子，误否决真标题的代价（骨架少一节）比放过一个噪声大。
            if number.depth == 1 and not number.title:
                number = None
            elif number.depth >= 2 or raw.max_size >= body_size:
                # 单级编号（`1 引言`）在 PDF 里也可能是编号列表项，加一道字号闸：
                # 标题的字号不会比正文小。多级编号（`3.1`）本身就是强信号，直接放行。
                return "heading", min(number.depth, 6)

    is_large = raw.max_size >= body_size + HEADING_SIZE_DELTA
    if is_large and len(raw.text) <= HEADING_MAX_CHARS and raw.line_count <= HEADING_MAX_LINES:
        return "heading", size_levels.get(raw.max_size, 1)

    return "paragraph", None


# ---------------------------------------------------------------------------
# 同段折行合并
# ---------------------------------------------------------------------------


def _is_full_line(prev: _RawBlock, block_right: float | None) -> bool:
    """`prev` 的**末行**是否"排满了"本块的右边界。

    只有块内合并才传得出 `block_right`（同一 text block 的最右边界）；
    跨 block 时返回 False —— 参照物不同，这道护栏不适用，
    跨块一律按原来的规则 4 处理。

    为什么需要这道护栏：中文排版里折行断在句末标点极其常见（一行正好排到
    句号处），仅凭"上一行以句末标点收尾"就拆段，会把一段单倍行距的正文
    按行剁碎（实测：20 页讲义 → 240 块）。而**排满的行**不可能是段落末行 ——
    段落末行后面没有后续内容要与它同段，排版不会把它顶到右边界。
    """
    if block_right is None or prev.last_right is None or not prev.line_height:
        return False
    return block_right - prev.last_right <= PARAGRAPH_FULL_LINE_TOLERANCE_RATIO * prev.line_height


def _is_continuation(prev: _RawBlock, cur: _RawBlock, block_right: float | None = None) -> bool:
    """`cur` 是不是 `prev` 那一句的**续行**（即两块其实属于同一段）。

    折行会被 PyMuPDF 切成两个 text block —— 它对"段"的切分比排版直觉粗。
    如果就这么产出，下游按句切分时会切到半句话，`source_quote` 也就断了。
    判据（全部满足才算续行）：

      1. **同一页** —— 跨页连不上（跨页的是新段落/新页面版心）；
      2. **行距接近行高**：`cur` 首行顶边 - `prev` 末行顶边 ≤
         `PARAGRAPH_MERGE_MAX_LINE_GAP_RATIO`（1.6）× `prev` 的行高。
         单倍折行约 1.0–1.35 倍，段间距普遍 ≥ 1.5 倍，1.6 卡在中间；
      3. **没有首行缩进**：`cur` 首行左边界相对 `prev` 右移超过
         `PARAGRAPH_INDENT_RATIO`（1.5）个行高 → 那是新段落的首行缩进；
      4. **上一块没有以句末标点收尾** → 否则上一句已经说完，下一块是新段落；
         但上一行**排满了本块右边界**时豁免（`_is_full_line`）——
         那种断行是折行，不是段落边界。

    第 2 条是主判据，第 3、4 条是"明显的段落起始特征"，用来防止把两个挨得紧
    的独立段落误合成一段（误合的代价：段落边界丢失，知识点归属跟着含糊）。
    第 4 条的豁免（`block_right`）只在**块内**生效，见 `_is_full_line`。
    """
    if prev.page_no != cur.page_no:
        return False
    if prev.last_top is None or cur.first_top is None or not prev.line_height:
        return False

    if cur.first_top - prev.last_top > PARAGRAPH_MERGE_MAX_LINE_GAP_RATIO * prev.line_height:
        return False

    if prev.left is not None and cur.left is not None:
        if cur.left - prev.left > PARAGRAPH_INDENT_RATIO * prev.line_height:
            return False

    return not (
        _SENTENCE_END_RE.search(prev.text) and not _is_full_line(prev, block_right)
    )


def _merge_raw(prev: _RawBlock, cur: _RawBlock) -> _RawBlock:
    """把续行并进上一块：文本按中英规则拼接，版面取并集。"""
    boxes = [box for box in (prev.bbox, cur.bbox) if box is not None]
    bbox: BBox | None = None
    if boxes:
        bbox = (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )
    return _RawBlock(
        page_no=prev.page_no,
        bbox=bbox,
        # 拼接规则与块内合并同一套：中文之间不插空格，拉丁字母/单词之间插一个空格
        text=_join_lines([prev.text, cur.text]),
        line_start=prev.line_start,
        line_end=cur.line_end,
        line_count=prev.line_count + cur.line_count,
        max_size=max(prev.max_size, cur.max_size),
        first_top=prev.first_top,
        last_top=cur.last_top,
        left=prev.left,
        line_height=max(prev.line_height or 0.0, cur.line_height or 0.0) or None,
        # 末行的右边界取 `cur` 的；`cur` 没有几何信息时退回 `prev` 的
        last_right=cur.last_right if cur.last_right is not None else prev.last_right,
    )


def _merge_continuation_lines(
    classified: list[tuple[_RawBlock, str, int | None]],
) -> list[tuple[_RawBlock, str, int | None]]:
    """把相邻的续行合成一块。

    **heading 与 image_caption 都不参与合并**，理由：
      · 标题 / 图注与正文是三个语义单位，合起来等于把"节标题""图注"一起抹掉 ——
        图注被并进下一段正文后，`image_caption` 就永远不会产出；
      · 标题与正文的字号/行距本来就不同，合出来的块字号信息是脏的
        （`_classify` 依赖 `max_size`，脏了会连带影响后续判断）。
    只把 `paragraph` 接在 `paragraph` 后面。
    """
    merged: list[tuple[_RawBlock, str, int | None]] = []
    for raw, block_type, heading_level in classified:
        if merged and block_type == "paragraph":
            prev_raw, prev_type, _ = merged[-1]
            if prev_type == "paragraph" and _is_continuation(prev_raw, raw):
                merged[-1] = (_merge_raw(prev_raw, raw), "paragraph", None)
                continue
        merged.append((raw, block_type, heading_level))
    return merged


def parse_pdf(path: str | Path) -> ParsedDocument:
    """解析文本层 PDF，产出带页码 / 页内行号 / 版面坐标的块。

    失败一律抛 `ApiError`（中文文案）：加密、损坏、空文件、超过 `MAX_PAGES`，
    以及**页级/文档级解析中途**出的任何异常（`_open_pdf` 与解析主体各有一道
    兜底 except）—— `__init__.parse_material` 对外承诺"失败一律是 ApiError"，
    这里必须自己守住；单文件失败不影响批次里的其他文件（A1-7）。
    扫描版不抛错，返回 `source_type="pdf_scan"` 的空块表 + 一条 high 级存疑说明。
    """
    doc = _open_pdf(path)
    try:
        page_count = doc.page_count
        if page_count <= 0:
            raise ApiError(
                ErrorCode.INVALID_PARAM,
                "这个 PDF 里没有页面，无法解析，请确认文件是否完整",
            )
        if page_count > MAX_PAGES:
            raise ApiError(
                ErrorCode.INVALID_PARAM,
                f"这份 PDF 有 {page_count} 页，超过单次解析上限 {MAX_PAGES} 页，请拆分后分批上传",
            )

        is_scan, sampled_pages, sampled_chars = _looks_like_scan(doc)
        if is_scan:
            return ParsedDocument(
                source_type="pdf_scan",
                blocks=[],
                page_count=page_count,
                # 还没解析，所以没有 parse_method。**不要**在这里写 "ocr"：
                # 本批次一行 OCR 都没跑，写了就是假账。
                parse_method=None,
                uncertain_notes=[
                    UncertainNote(
                        kind="missing_field",
                        severity="high",
                        page=sampled_pages[0] if sampled_pages else None,
                        message=(
                            f"抽样 {len(sampled_pages)} 页（第 "
                            f"{'、'.join(str(p) for p in sampled_pages)} 页）"
                            f"共只提取到 {sampled_chars} 个字符"
                            f"（判定阈值：每页 {SCAN_MIN_CHARS_PER_PAGE} 个字符），"
                            "且这些页面里只有图像、没有可提取的文本层，"
                            "判断这是一份扫描版 PDF。本批次尚未接入 OCR，"
                            "暂时无法提取文字，请上传文字版 PDF，"
                            "或等待 OCR 通道上线后重新解析。"
                        ),
                    )
                ],
            )

        raws, size_chars, image_count = _raw_blocks(doc)
        # 去噪必须在**分类之前**：页脚 running head（`1.2. Requirements`）与正文
        # 真节标题同名同层级，先分类再删等于让噪声先决定骨架。
        raws, denoise = _denoise(raws, doc)
    except ApiError:
        # 自己抛的业务异常原样往外传（文案已经是中文、错误码已经合理）
        raise
    except Exception as exc:  # noqa: BLE001 —— 见下：pymupdf 的异常类型不稳定
        # 页级 / 文档级解析中途出的问题（坏页、异常字体编码、损坏的对象流……）
        # 也必须收口成 `ApiError`：`__init__.parse_material` 对外承诺
        # "失败一律是 ApiError"，漏出去的原生异常会绕过全局异常处理器，
        # 前端只会收到 500 与英文堆栈。单文件失败不影响批次里的其他文件（A1-7）。
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            "这个 PDF 的内容读不出来（文件可能有损坏的页或异常的字体编码），"
            "请重新导出后再上传",
        ) from exc
    finally:
        doc.close()

    body_size = _body_size(size_chars)
    large_sizes = sorted(
        {size for size in size_chars if size >= body_size + HEADING_SIZE_DELTA}, reverse=True
    )
    # 字号降序 → 1..6 级；超出 6 种字号的挤到第 6 级（DB 有 1–6 的 CHECK）
    size_levels = {size: min(idx + 1, 6) for idx, size in enumerate(large_sizes)}

    # 先判块类型（heading/paragraph），**再**合并续行：反过来的话标题会被
    # 当成上一段的续行吞掉，或者合并后的块字号信息变脏导致标题判错。
    # 封面装饰行在**最前面**否决：它用的是全书最大字号，字号法必然把它判成
    # 一级标题，而一级标题就是"章"—— 不在这里拦住，封面书名就会成为章。
    cover = _cover_decorations(raws, body_size)
    classified: list[tuple[_RawBlock, str, int | None]] = []
    for index, raw in enumerate(raws):
        if index in cover:
            classified.append((raw, "paragraph", None))
            continue
        block_type, heading_level = _classify(raw, body_size, size_levels)
        classified.append((raw, block_type, heading_level))

    blocks: list[ParsedBlock] = []
    for raw, block_type, heading_level in _merge_continuation_lines(classified):
        blocks.append(
            ParsedBlock(
                block_type=block_type,
                content_md=raw.text,
                page_no=raw.page_no,
                line_start=raw.line_start,
                line_end=raw.line_end,
                heading_level=heading_level,
                bbox=raw.bbox,
            )
        )

    notes: list[UncertainNote] = []
    if denoise.total:
        # 去噪**不静默丢内容**：删了几个块、分别属于哪一类，如实登记。
        # 方向仍是"宁可漏删不可误删"（模块 docstring），所以只报数、不辩解。
        notes.append(
            UncertainNote(
                kind="other",
                severity="low",
                message=(
                    f"已识别并去除 {denoise.total} 个页眉 / 页脚 / 页码噪声块"
                    f"（{denoise.describe()}）。这些块是书名、running head 与页码，"
                    "不属于正文，因此没有写入块表与 Markdown；判定只依据版式"
                    "（页边距带 / 版心外 / 跨页重复 / 与相邻内容隔离），"
                    "不依据文本内容，如需核对可按页码人工复核。"
                ),
            )
        )
    if image_count:
        # 图片块不产出内容（本批次没有图注识别能力，编一个标题就是造假）。
        # 但不能不吭声：材料里有多少图，评审和用户都该看得见。
        notes.append(
            UncertainNote(
                kind="other",
                severity="low",
                message=(
                    f"这份 PDF 里有 {image_count} 张图片，本批次只解析文本层，"
                    "图片内的文字（含图注）尚未纳入，请人工核对图文对照的内容。"
                ),
            )
        )

    return ParsedDocument(
        source_type="pdf_text",
        blocks=blocks,
        page_count=page_count,
        parse_method="text_extract",
        uncertain_notes=notes,
    )
