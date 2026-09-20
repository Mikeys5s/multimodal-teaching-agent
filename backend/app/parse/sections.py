"""章 / 节骨架推断（归属：P1）。SPEC §5.1、docs/extraction-channel.md §2。

只产出骨架，**不写 chapters / sections 表**
------------------------------------------
那两张表是 P2 的 outline 领域（`app/models/outline.py`），归属纪律见 SPEC §9.1。
本模块产出纯内存的 `ParsedSection` / `ParsedChapter`，P2 拿到后自己落库：

    source_block_id = block_id(mat_id, section.heading_seq)
    section_id      = section_id(mat_id, section.chapter_seq, section.seq)
    number / title  = section.number / section.title   ← 原貌，不要改写

`material_blocks` 本身**没有 section_id 列**（归属由 P2 的
`sections.source_block_id` 反向指），所以这里只给出 `[start_seq, end_seq]`
这个块区间 —— 下游按区间切 Markdown 就是"节级输入片段"。

⚠️ **区间边界语义的权威口径在 `ParsedSection` 的 docstring**（左闭右闭、
标题块归不归本节、相邻节是否重叠、空节怎么表示）—— 那几条是确定性契约，
落库与投喂一律照它实现，不要凭直觉补一个块。

"节"的粒度：不照搬标题层级
--------------------------
docs/extraction-channel.md 的硬规则是「**一节要能抽出 3–12 个知识点**」，
并给了反例（§6 问题 1）：6.3 底下有 6.3.1 / 6.3.2 / 6.3.3 时，把 6.3 当"节"
会跨 4 个子节、知识点归属含糊，应当让 6.3.x 各作一节。

解析阶段**还没有知识点**，数不出 3–12，所以用一条等效的结构代理 ——
"**有子标题的标题只是容器，叶子标题才是节**"：

  1. 先把标题块搭成一棵树（按 heading_level 压栈，见 `_build_tree`）；
  2. 章 = 最浅一层的标题（`roots`）；
  3. 从章往下递归：**没有子标题**的标题 → 自成一节（连同它的正文）；
  4. 有子标题的标题 → 它自己那段"标题与第一个子标题之间的正文"单独成一节
     （标题与编号沿用容器自身），然后对每个子标题重复第 3 步。

第 4 条是防"丢块"的关键：6.3 若在 6.3.1 之前写了导语，那段导语必须有个去处，
否则永远喂不到模型里。

为什么不选"某一个固定层级的标题当节"：真实材料里嵌套是不均匀的 ——
1.1 是叶子、1.2 带一个 1.2.1。固定层级要么把 1.2.1 塞进 1.2（回到被否掉的
粗粒度），要么把 1.1 的正文挤进一个巨大的"导语节"（更糟）。按分支递归
两种情况都能给出合理结果，且规则只有一句、无需阈值调参。

更深的标题不丢：它们要么成为节（叶子），要么作为容器留在节描述里。

本模块**只依赖文档自身结构**，无随机数、无抽样、不读时钟 —— 同输入必然
同输出（A2-7）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.parse.blocks import ParsedBlock, ParsedDocument, split_heading_number

#: 第一个章标题之前的块单独成章时的标题。
_PREAMBLE_TITLE = "前言"
#: 整份材料一个标题都没有时的占位标题。
_NO_HEADING_TITLE = "全文"


@dataclass(frozen=True)
class ParsedSection:
    """一节 —— 下游**按节投喂**的那个中间单位（抽取阶段的最小输入单元）。

    区间边界语义（确定性契约 —— 落库 / 投喂一律照此实现，勿凭直觉补一个块）
    ----------------------------------------------------------------------
    1. **左闭右闭**。本节的内容块就是 `blocks[start_seq : end_seq + 1]`。
       恒有 `start_seq <= end_seq`（区间**非空**），实现里**不存在**
       `end_seq < start_seq` 这种"空区间"写法 —— 所以切片结果**永远不会是
       `[]`**。`block_count = end_seq - start_seq + 1`，恒 >= 1。
    2. **标题块归属**：
       · **叶子标题**（自己下面没有子标题）→ 标题块**属于本节**，
         `start_seq == heading_seq`，切片的第一块就是那行标题本身；
       · **容器标题**（下面还有子标题）→ 它的"导语节"**不含容器标题块**，
         `start_seq == heading_seq + 1`；容器标题块**不属于任何节**
         （它是骨架节点，不是节内容）。容器的编号与标题由它的导语节继承
         （见本节的 `number` / `title`），所以信息没丢。
       · 两条合起来是一条不变量：**`heading_seq - start_seq ∈ {-1, 0}`**。
       · 占位节（`前言` / `全文`，整份材料推不出骨架时）**没有真实标题块**，
         `heading_seq` 一律为 0，而 `blocks[0]` **不保证是 heading 块**。
    3. **相邻节不重叠**。按文档顺序，恒有 `前一节.end_seq < 后一节.start_seq`；
       多数相邻节还满足 `后一节.start_seq == 前一节.end_seq + 1`（无缝相接）。
       唯一的**空洞是容器标题块**（见第 2 条）：骨架里它是容器节点，
       不进任何节的块区间。**空洞不等于丢块** —— 容器标题块在骨架里有唯一
       归属（容器 + 它的导语节/子节），只是不落在"节级输入片段"里。
    4. **"空节"怎么表示**：标题后紧跟同级标题（这个标题下一个字正文都没有）时，
       `start_seq == end_seq == heading_seq`、`block_count == 1` ——
       切片拿到的就是**那一行标题**，不是 `[]`。下游要判"这节没有正文"，
       判据是 `end_seq == heading_seq`（而不是 `block_count == 0`，它不会为 0）。
    5. **节内 `page_no` 单调不减**。区间是文档顺序上的连续切片，所以节内
       （非 None 的）`page_no` 必然单调不减 —— 一节不会来回跳页，
       节的页锚点才能被下游当成"这一节覆盖了第几页到第几页"。

    一行例子（`blocks` 按文档顺序排列）
    ---------------------------------
        idx:       0           1         2          3
        content:  "1 网络层"   "导语"    "1.1 路由"  "正文"
        → ch0 sec0 = 容器 1 的**导语节**：heading_seq=0，[start,end] = [1, 1]
        → ch0 sec1 = 叶子 1.1 的节：     heading_seq=2，[start,end] = [2, 3]
        · idx 0 是容器标题块 → 不属于任何节（空洞）
        · `blocks[1:2]` = ["导语"]，`blocks[2:4]` = ["1.1 路由", "正文"]
        若把 idx 1 的"导语"删掉，容器就不出节，只剩 sec0 = 叶子的 [2, 3]。
    """

    chapter_seq: int
    chapter_number: str | None
    chapter_title: str
    chapter_heading_seq: int
    seq: int
    number: str | None
    title: str
    heading_seq: int
    start_seq: int  # 闭区间左端（含）
    end_seq: int  # 闭区间右端（含）；恒 >= start_seq。切片用 blocks[start_seq : end_seq + 1]

    def __post_init__(self) -> None:
        """把上面的区间语义钉成**构造期不变量**（编程错误 → ValueError，不做兜底）。

        区间差一个块不会让任何下游报错，只会让知识点悄悄挂到相邻的节上 ——
        那正是最难查、且直接砸硬验收指标的一类 bug。所以在构造处就拦住。
        """
        if self.start_seq < 0 or self.end_seq < 0 or self.heading_seq < 0:
            raise ValueError(
                f"seq 必须非负，收到 start={self.start_seq} end={self.end_seq} "
                f"heading={self.heading_seq}"
            )
        if self.end_seq < self.start_seq:
            raise ValueError(
                f"区间必须非空（左闭右闭）：start_seq={self.start_seq} > "
                f"end_seq={self.end_seq}。空节用 start_seq == end_seq == heading_seq 表示，"
                "不存在 end_seq < start_seq 的写法。"
            )
        if self.heading_seq not in (self.start_seq, self.start_seq - 1):
            raise ValueError(
                f"heading_seq 与 start_seq 的关系不合法：heading_seq={self.heading_seq}，"
                f"start_seq={self.start_seq}（必须是 start_seq 本身 = 叶子，"
                "或 start_seq - 1 = 容器导语节）"
            )

    @property
    def block_count(self) -> int:
        return self.end_seq - self.start_seq + 1


@dataclass(frozen=True)
class ParsedChapter:
    """一章 —— 只做导航与统计，不承载知识点。"""

    seq: int
    number: str | None
    title: str
    heading_seq: int
    sections: tuple[ParsedSection, ...]


# ---------------------------------------------------------------------------
# 标题树
# ---------------------------------------------------------------------------


@dataclass
class _Node:
    """标题树的一个节点。势力范围是 `[seq, end_seq]`（闭区间，含标题自身）。"""

    seq: int
    level: int
    block: ParsedBlock
    end_seq: int = 0
    children: list[_Node] = field(default_factory=list)


def _has_direct_content(node: _Node) -> bool:
    """标题之后、第一个子标题之前有没有正文。

    没有子标题时 = 标题到势力范围末尾之间有没有块。
    （中间不可能夹着别的标题 —— 有的话就会成为子节点或兄弟节点。）
    判断方式与 `_flatten_sections` 里那段"容器导语节"的条件**必须一致**，
    否则会出现"这里算得出一段导语、那边却切不出节"的块丢失。
    """
    if node.children:
        return node.children[0].seq > node.seq + 1
    return node.end_seq > node.seq


def _build_tree(blocks: list[ParsedBlock]) -> list[_Node]:
    """把所有标题块搭成一棵树，返回最浅一层的根节点（= 章）。

    用单调栈：《按文档顺序》遇到层级 ≤ 栈顶的标题就弹栈（被弹出的节点在此刻
    确定了自身的 `end_seq`），再挂到新栈顶下面。这样每个节点的势力范围天然
    是"到下一个同级或更浅标题之前"，与"章/节"的直觉一致。
    """
    roots: list[_Node] = []
    stack: list[_Node] = []

    for idx, block in enumerate(blocks):
        if not block.is_heading:
            continue
        level = block.heading_level or 1
        while stack and stack[-1].level >= level:
            stack.pop().end_seq = idx - 1

        node = _Node(seq=idx, level=level, block=block)
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    for node in stack:  # 还没被弹掉的，势力范围一直到文末
        node.end_seq = len(blocks) - 1
    return roots


def _number_and_title(block: ParsedBlock) -> tuple[str | None, str]:
    """标题块 → (章节号原貌, 标题原貌)。

    拆不出编号时（纯字号判出来的标题）编号留 None、整行当标题 —— 不编造编号。
    """
    parsed = split_heading_number(block.content_md)
    if parsed is None:
        return None, block.content_md.strip()
    return parsed.number, parsed.title or parsed.number


# ---------------------------------------------------------------------------
# 树 → 节
# ---------------------------------------------------------------------------


def _flatten_sections(nodes: list[_Node]) -> list[tuple[int, str | None, str, int, int]]:
    """递归展开成 `(heading_seq, number, title, start_seq, end_seq)`，文档顺序。

    叶子 → 一节；容器 → 自己那段导语（若有）一节 + 每个子节点递归。
    """
    out: list[tuple[int, str | None, str, int, int]] = []
    for node in nodes:
        number, title = _number_and_title(node.block)
        if not node.children:
            # 叶子标题自成一节。end_seq == seq 时**只有标题、没有正文**
            # （标题后紧跟同级标题）：区间仍含标题自身，故 block_count == 1、
            # 切片得到那一行标题 —— 不是空列表，判据见 ParsedSection docstring 第 4 条。
            out.append((node.seq, number, title, node.seq, node.end_seq))
            continue

        if _has_direct_content(node):
            out.append((node.seq, number, title, node.seq + 1, node.children[0].seq - 1))
        out.extend(_flatten_sections(node.children))
    return out


def _assert_range_contract(blocks: list[ParsedBlock], sections: list[ParsedSection]) -> None:
    """校验 `ParsedSection` docstring 里写死的**跨节区间不变量**。

    `ParsedSection.__post_init__` 只能看到一节自己，管不了节与节之间的关系，
    所以"相邻节不重叠 / 按文档顺序 / 节内页码单调不减"这三条在这里post-check。

    这些性质都由 `_build_tree` 的单调栈 + `_flatten_sections` 的递归方式保证，
    **正常输入下永远不会触发** —— 放在这里是为了以后有人动了压栈/递归逻辑时
    **立刻炸掉**。理由：区间差一个块不会让任何下游报错，只会让知识点挂到相邻的
    节上，而那是不报错的硬验收翻车（悬挂错误）。按本包约定，契约被违反
    （编程错误）→ `ValueError`，不做兜底。

    检查的条目：
      · 区间落在 `blocks` 范围内，且 `start_seq <= end_seq`；
      · 按文档顺序严格递增，且 `前一节.end_seq < 后一节.start_seq`（不重叠）；
      · 节内非 None 的 `page_no` 单调不减。
    """
    prev: ParsedSection | None = None
    for section in sections:
        if section.end_seq >= len(blocks):
            raise ValueError(
                f"节区间越界：[{section.start_seq}, {section.end_seq}] 超出块数 {len(blocks)}"
            )
        if prev is not None:
            if section.start_seq <= prev.start_seq:
                raise ValueError(
                    f"节没有按文档顺序排列：上一节 start_seq={prev.start_seq}，"
                    f"本节 start_seq={section.start_seq}"
                )
            if section.start_seq <= prev.end_seq:
                raise ValueError(
                    f"相邻节区间重叠：上一节 [{prev.start_seq}, {prev.end_seq}] 与"
                    f"本节 [{section.start_seq}, {section.end_seq}] 有交集"
                    "（同一个块会被投喂给两个节，知识点会挂错节）"
                )

        pages = [
            b.page_no for b in blocks[section.start_seq : section.end_seq + 1] if b.page_no is not None
        ]
        if pages != sorted(pages):
            raise ValueError(
                f"节内 page_no 不是单调不减：sec{section.seq} "
                f"[{section.start_seq}, {section.end_seq}] → {pages}"
            )
        prev = section


def _build_chapters(blocks: list[ParsedBlock]) -> list[ParsedChapter]:
    """把块流切成章 → 节的骨架。全程只依赖文档自身，无随机、无时间。"""
    # ---- 没有任何标题：整份材料作为一节（占位标题，不编造章节号）----
    if not any(b.is_heading for b in blocks):
        if not blocks:
            return []
        section = ParsedSection(
            chapter_seq=0,
            chapter_number=None,
            chapter_title=_NO_HEADING_TITLE,
            chapter_heading_seq=0,
            seq=0,
            number=None,
            title=_NO_HEADING_TITLE,
            heading_seq=0,
            start_seq=0,
            end_seq=len(blocks) - 1,
        )
        return [
            ParsedChapter(
                seq=0, number=None, title=_NO_HEADING_TITLE, heading_seq=0, sections=(section,)
            )
        ]

    roots = _build_tree(blocks)
    chapters: list[ParsedChapter] = []

    # ---- 第一个章标题之前的块：单独成"前言"章，不硬塞进第一章 ----
    if roots and roots[0].seq > 0:
        section = ParsedSection(
            chapter_seq=0,
            chapter_number=None,
            chapter_title=_PREAMBLE_TITLE,
            chapter_heading_seq=0,
            seq=0,
            number=None,
            title=_PREAMBLE_TITLE,
            heading_seq=0,
            start_seq=0,
            end_seq=roots[0].seq - 1,
        )
        chapters.append(
            ParsedChapter(
                seq=0, number=None, title=_PREAMBLE_TITLE, heading_seq=0, sections=(section,)
            )
        )

    for root in roots:
        number, title = _number_and_title(root.block)
        chapter_seq = len(chapters)
        sections = tuple(
            ParsedSection(
                chapter_seq=chapter_seq,
                chapter_number=number,
                chapter_title=title,
                chapter_heading_seq=root.seq,
                seq=sec_seq,
                number=sec_number,
                title=sec_title,
                heading_seq=heading_seq,
                start_seq=start,
                end_seq=end,
            )
            for sec_seq, (heading_seq, sec_number, sec_title, start, end) in enumerate(
                _flatten_sections([root])
            )
        )
        chapters.append(
            ParsedChapter(
                seq=chapter_seq,
                number=number,
                title=title,
                heading_seq=root.seq,
                sections=sections,
            )
        )

    return chapters


def _build(blocks: list[ParsedBlock]) -> list[ParsedChapter]:
    """`_build_chapters` + 跨节区间不变量自检 —— 对外唯一入口见 `split_outline`。"""
    chapters = _build_chapters(blocks)
    _assert_range_contract(blocks, [s for c in chapters for s in c.sections])
    return chapters


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


def split_outline(doc: ParsedDocument) -> list[ParsedChapter]:
    """章 → 节骨架。P2 用它落 `chapters` / `sections` 两张表。"""
    return _build(doc.blocks)


def split_sections(doc: ParsedDocument) -> list[ParsedSection]:
    """按文档顺序展开的节列表 —— **下游按节投喂的入口**。

    每一节自带所属章的信息（`chapter_seq` / `chapter_number` / `chapter_title`），
    拿到这个平铺列表就足以重建整棵骨架，不必先调 `split_outline`。
    """
    out: list[ParsedSection] = []
    for chapter in _build(doc.blocks):
        out.extend(chapter.sections)
    return out


def section_markdown(doc: ParsedDocument, section: ParsedSection, mat_id: str) -> str:
    """切出一节的带锚点 Markdown —— 就是"节级输入片段"。

    锚点由 `markdown.to_markdown` 生成，并用 `start_seq` 把序号偏移到**全局
    位置**：切片后重新从 0 编号会让锚点指向别的块，那比没有锚点更糟。
    """
    from app.parse.markdown import to_markdown

    return to_markdown(
        doc.blocks[section.start_seq : section.end_seq + 1],
        mat_id,
        start_seq=section.start_seq,
    )
