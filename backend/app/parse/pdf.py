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

⚠️ 已知限制：页眉 / 页脚 / 页码 / 图注**均未被识别**（本节为真实教材实测，非推测）
--------------------------------------------------------------------------------
**实测样本**：真实教材 `Computer Networks: A Systems Approach, Release Version 6.1`
（489 页 LaTeX 版，取前 30 页为样本）：
  · **页眉**（每页重复的书名短行，跨页完全一致）：**24 块（占 7.8%）**，判为 `paragraph`；
  · **纯数字块（页码）**：**32 块，全部被判成 `heading` 且 `heading_level = 1`**；
  · **页脚 running head**（如 `Chapter 1. Foundation`、`1.2. Requirements`）：
    **52 块（占 16.9%）**，其中 **6 块**（如 `1.2. Requirements`）被判成
    `heading level 2` —— 与**正文真实节标题同名同层级**；
  · **图注**（以 `Figure x.y` 开头）：13 块**全部判为 `paragraph`**，
    `image_caption` **零产出**；其中一页的图注与紧随其后的正文段**粘连**成
    **628 字符**的单块；
  · **目录页**：p3 / p6 / p7 / p8 分别产出 27 / 25 / 19 / 3 块（碎块）。

成因（页码为何变成一级标题）：`app/parse/blocks.py` 的编号识别正则把**纯数字**
（如 `37`）识别成 **depth=1 的编号**，该行再通过本模块的字号闸，就被判成一级标题 ——
即"编号"这一信号对页码行是**假阳性**。

⚠️ **最要命的后果**：对上述真实教材的这 30 页跑 `split_outline`，产出
**34 章 / 63 节** —— **节骨架基本报废**。而 P1→P2 的接口 **I-1 恰好承诺
"含 section 归属"**，P2 会把这些页眉/页码/页脚冒充出来的"节"当作真实结构消费。

下游影响：噪声块会同时污染两件事 ——
  （a）**`source_quote` 溯源**：引文可能指到页码行或页眉行，而非正文；
  （b）**节归属**：页脚 running head 冒充节标题（与真节同名同级），正文被归错节。

本批次刻意**不顺手做一个半成品过滤**：页眉/页脚识别要同时看"跨页重复"
"页边距区域""纯数字"等多个信号，草率过滤会把正文短行（章节扉页的标题、
表格里的小标题）一起误删，那是不可逆的内容丢失。

**下一批计划（页眉 / 页脚 / 页码识别与去噪）**：
  1. 跨页重复短行 + 页边距带 + 纯数字行三类信号**联合判定并去噪**；
  2. 新增**否决规则**：**整行只有编号、无标题文字的单级编号不作 `heading`**
     （如孤立的 `37` 不得成为一级标题）—— 直接堵住上面"页码被判 heading"的成因。

> **红线：在去噪落地之前，PDF 的 section 骨架（章/节）不可信，P2 不得据此定型章节结构。**

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

        for raw_blk in data.get("blocks", []):
            if raw_blk.get("type") != 0:
                image_count += 1
                continue

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
                merged_blocks = _group_lines(line_raws)

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
    """判断一个块是 heading 还是 paragraph，并给出 heading_level。"""
    number: HeadingNumber | None = None
    if len(raw.text) <= HEADING_MAX_CHARS and raw.line_count == 1:
        number = split_heading_number(raw.text)
        if number is not None:
            # 单级编号（`1 引言`）在 PDF 里也可能是编号列表项，加一道字号闸：
            # 标题的字号不会比正文小。多级编号（`3.1`）本身就是强信号，直接放行。
            if number.depth >= 2 or raw.max_size >= body_size:
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

    **heading 不参与合并**，有两个理由：
      · 标题与正文是两个语义单位，合起来等于把"节标题"抹掉，骨架直接塌；
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
    classified: list[tuple[_RawBlock, str, int | None]] = []
    for raw in raws:
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
