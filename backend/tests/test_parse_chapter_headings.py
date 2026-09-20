"""章级标题去封面行污染（第三批 · 归属 P1）。

字号法（`parse.pdf`）只认"这一行比正文大"，给不出"章"这个语义。真实教材上
因此有**两类**污染，它们互相独立、要分别堵：

  污染① **封面装饰行**：封面 / 版权页的书名、副标题、作者行用的是全书**最大**
     字号，必然被判成一级标题；而"章 = 最浅一层的标题"就把它们当成了章。
     实测（*Computer Networks: A Systems Approach* 前 30 页，第 2 批的代码）：
     2 章 / 21 节，这"2 章"正是封面上的
     `Computer Networks: A Systems` 与 `Approach` —— 真实结构只有 Chapter 1。

  污染② **章标题没有编号**：章标题常常只在**章扉页**上以"大字 + 居中 + 无编号"
     出现（本教材第 9 页：`CHAPTER` / `ONE` / `FOUNDATION`，而 `1.1` 到第 10 页
     才开始）。它和前置部分（封面、目录、`PREFACE`）的标题**在字号法眼里完全
     同级**，谁也不比谁更像章 —— "章 = 最浅一层标题"于是把封面、目录、前言、
     章扉页各拆成一章，章数凭空多出来且**不报错**。

三道闸门，各管一段
------------------
  ① `pdf._cover_decorations`（四条**合取**）：前 `COVER_PAGES` 页 ∧ 无编号 ∧
     字号 ≥ 正文 + `COVER_SIZE_DELTA` ∧ **该页"普通字号块"≤ `COVER_MAX_BODY_BLOCKS`**
     → 不判 `heading`。第 ④ 条是把"封面"与"章扉页"分开的**唯一**信号：
     封面整页只有大字与一个日期行，章扉页后面紧跟着整页正文。
  ② `blocks._EN_CHAPTER_RE`：`Chapter 1. Foundation` 这种**带编号分隔符**的
     英文章标题能拆出章号（depth=1）—— 与图注识别同一套取舍，分隔符是必需信号，
     否则正文里 `Chapter 1 describes the ...` 这种完整句子会被当成标题。
     少了它，这类章标题就没有编号，只能落到污染②那条路上。
  ③ `sections` 的**编号结构定章**：文档里存在编号标题、且最浅的编号是 depth ≥ 2
     时，章由**编号前缀**决定（`1.1`/`1.2` → 同一章 `1`），无编号的 `heading`
     一律不当章根。这一条让"跨页重复的书名行"即使躲过去噪、还留在块表里，
     也**不会**变成章。

真值基准（本批验收）
--------------------
*Computer Networks: A Systems Approach* Release 6.1 前 30 页真实只有 **1 章**
（`Chapter 1. Foundation`）+ 该章的 **11 个叶子节**
（1.1 / 1.1.1 / 1.2 / 1.2.1–1.2.5 / 1.3 / 1.3.1 / 1.3.2）。
封面 / 目录 / `PREFACE` 属于前置部分，不应成为章（它们由「前言」占位章收着，
不静默丢内容）。

这个文件里有什么
----------------
6 条用例 = 5 类对抗 + 1 条**反向护栏**。全部夹具**程序化生成**（不依赖仓库外的
素材），断言**是硬的**（枚举具体的章号 / 节号 / `block_type`，不用"不为空"）。
每条用例都先用基线代码（`9950373`）跑过、确认它会**翻红** —— 不是"碰巧也通过"
的装饰性用例。真实教材的实测对照见 `tests/test_qa_parse_real_material.py`。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.parse import parse_pdf, split_outline, split_sections
from app.parse.blocks import ParsedBlock, ParsedDocument

#: A4 默认页面（595 × 842）上的版式常量。取值只影响夹具自己，
#: **不** import 实现里的阈值 —— 用例要钉的是"这类行算不算章"，不是"阈值是多少"。
LINE_GAP = 14.0  # 段内行距（≈ 1.2 个行高 → 会被并成一段）
PARA_GAP = 30.0  # 段间距（> 1.6 个行高 → 两段不会被并成一段）

#: 三组正文。刻意写成"上一行不以句末标点收尾、下一行收尾"的多行段，
#: 让同一段的两行被并成一个块（否则每一行都会独立成块，用例就测不到合并后的形态）。
BODY_A = (
    "The network is a set of nodes that are connected by links and",
    "which forward data from one link out on another.",
)
BODY_B = (
    "A protocol is a set of rules that governs how the nodes exchange",
    "messages with each other over the shared communication medium.",
)
BODY_C = (
    "Performance is measured in terms of bandwidth and latency, and it",
    "depends on how the resources are shared among the competing users.",
)


def _wl(page: pymupdf.Page, x: float, y: float, text: str, size: float = 10) -> None:
    """写**拉丁**文本用默认字体（Helvetica）。

    ⚠️ 夹具里的文本全是英文，理由与 `test_parse_denoise.py` 里那段一样：
    `china-s` 的拉丁字是全角的，一段英文会横跨整个页面宽度并被右边界截断。
    """
    page.insert_text((x, y), text, fontsize=size)


def _body(page: pymupdf.Page, x: float, y: float, lines: tuple[str, ...], size: float = 10) -> float:
    """写一个正文段（段内行距 `LINE_GAP`），返回下一段的 y。"""
    for offset, line in enumerate(lines):
        _wl(page, x, y + offset * LINE_GAP, line, size)
    return y + (len(lines) - 1) * LINE_GAP + PARA_GAP


def _save(doc: pymupdf.Document, path: Path) -> Path:
    doc.save(str(path))
    doc.close()
    return path


def _by_text(doc: ParsedDocument) -> dict[str, ParsedBlock]:
    """按文本索引块。重复出现的文本（跨页重复的书名）会在下面用 `_all_text` 数。"""
    return {b.content_md: b for b in doc.blocks}


def _all_text(doc: ParsedDocument) -> list[str]:
    return [b.content_md for b in doc.blocks]


def _page_text(doc: ParsedDocument, page_no: int) -> str:
    return "\n".join(b.content_md for b in doc.blocks if b.page_no == page_no)


def _real_section_numbers(doc: ParsedDocument) -> list[str | None]:
    """**真章**（`number` 非 None）的节编号，按文档顺序。

    ⚠️ 不能直接断言 `split_sections()` 的全量结果：第一个编号标题之前若还有块
    （封面 / 目录 / 章扉页），`sections` 会先给一个「前言」**占位章**，它的那一节
    `number` 是 None。占位章是"不静默丢内容"的机制（第一批就有），不属于本批要钉的
    「真章有几个节」，所以这里把它排除掉 —— 用例要钉的是真章的节编号，不是占位机制。
    """
    return [s.number for c in split_outline(doc) if c.number is not None for s in c.sections]


# ---------------------------------------------------------------------------
# 对抗 1 · 真章标题的两种风格：必须都是「章」（depth=1）
# ---------------------------------------------------------------------------


def _numbered_chapter_pdf(path: Path, first_line: str) -> Path:
    """一本两页的小书：`first_line` 是章标题（20pt），下面挂 1.1 / 1.2。"""
    doc = pymupdf.open()
    page1 = doc.new_page()
    _wl(page1, 72, 100, first_line, 20)
    _wl(page1, 72, 160, "1.1 Applications", 13)
    _body(page1, 72, 200, BODY_A)
    _body(page1, 72, 280, BODY_B)

    page2 = doc.new_page()
    _wl(page2, 72, 100, "1.2 Requirements", 13)
    _body(page2, 72, 140, BODY_A)
    _body(page2, 72, 220, BODY_C)
    return _save(doc, path)


def test_numbered_chapter_title_is_a_chapter_in_both_styles(tmp_path: Path) -> None:
    """★ 对抗 1：`Chapter 1. Foundation` 与 `1. Foundation` 都必须判成 `heading`（章级）。

    两种风格走的是**两条不同的代码路径**，所以必须分别钉住：

      · `Chapter 1. Foundation` → `blocks._EN_CHAPTER_RE`（本批新增）。少了它这一行
        拆不出章节号，章号会退化成 None（基线代码就是 `number=None`、
        `title='Chapter 1. Foundation'` 整行不切分）；
      · `1. Foundation` → 第一批就有的 `_NUM_RE`，本批**不许改坏**。

    夹具刻意把章标题放在**第 1 页**：`pdf._cover_decorations` 的第 ① 条（前 2 页）
    本来是满足的，把它救下来的是第 ② 条「**没有编号**」——有编号的行永远不是封面
    装饰行。这条断言同时钉住了"封面否决不会误伤有编号的真章标题"。
    """
    cases = {
        "Chapter 1. Foundation": ("Chapter 1", "Foundation"),
        "1. Foundation": ("1", "Foundation"),
    }
    for first_line, (number, title) in cases.items():
        parsed = parse_pdf(_numbered_chapter_pdf(tmp_path / f"{number}.pdf", first_line))
        heading = _by_text(parsed)[first_line]

        assert heading.block_type == "heading", f"{first_line!r} 没有判成标题"
        assert heading.heading_level == 1, (
            f"{first_line!r} 不是章级（heading_level={heading.heading_level}）"
        )
        assert heading.page_no == 1, (
            "夹具把章标题放在第 1 页：封面否决的第 ② 条（有编号）必须把它救下来"
        )

        chapters = split_outline(parsed)
        assert [(c.number, c.title) for c in chapters] == [(number, title)], (
            f"{first_line!r} 的章号/标题拆错了：{[(c.number, c.title) for c in chapters]}"
        )
        assert [s.number for s in chapters[0].sections] == ["1.1", "1.2"]


# ---------------------------------------------------------------------------
# 对抗 2 · 无编号但合法的章标题：能被认出来，但只在严格的条件下
# ---------------------------------------------------------------------------


def _title_page_pdf(path: Path, title_x: float) -> Path:
    """章扉页（第 1 页）+ 整页正文 + 第 2、3 页的 1.1 / 1.2。"""
    doc = pymupdf.open()
    page1 = doc.new_page()
    _wl(page1, title_x, 100, "FOUNDATION", 20)  # 无编号的章扉页标题
    _body(page1, 72, 160, BODY_A)
    _body(page1, 72, 240, BODY_B)
    _body(page1, 72, 320, BODY_C)

    page2 = doc.new_page()
    _wl(page2, 72, 100, "1.1 Applications", 13)
    _body(page2, 72, 140, BODY_A)
    _body(page2, 72, 220, BODY_B)

    page3 = doc.new_page()
    _wl(page3, 72, 100, "1.2 Requirements", 13)
    _body(page3, 72, 140, BODY_A)
    _body(page3, 72, 220, BODY_C)
    return _save(doc, path)


def test_unnumbered_chapter_title_is_recognized_only_on_a_title_page(tmp_path: Path) -> None:
    """★ 对抗 2：**无编号**的章标题（章扉页）能被认出来 —— 条件与边界都钉死在这里。

    规则（`sections._front_title`，实现在 `sections.py`）：只有当文档里**存在编号
    标题**、且最浅的编号是 depth ≥ 2（即没有带编号的章标题）时，才去给每一章找
    扉页标题行，候选必须**同时**满足：

      (a) 已被判成 `heading`（字号法认了它）；
      (b) **不齐左**（`x0 - 版心左边界 ≥ 1 个行高`）—— 章扉页标题居中/居右，
          章内正文与无编号小节标题都齐左；
      (c) 落在该章**第一个编号标题所在页或其前一页**（章扉页紧邻本章第一个编号节）;
      (d) 无编号、且长度 ≤ 100 字符；多个候选取**最长**的一行（`CHAPTER` /
          序号词 `ONE` 都很短，标题才是信息量最大的那行）。

    找不到就**不编**：章的标题退化成章号本身。下面两个夹具的差别**只有** `title_x`，
    钉的就是第 (b) 条这条边界：

      · `title_x=200`（居中/居右）→ 标题 = `FOUNDATION`，且 `heading_seq` 指向
        扉页那一行；
      · `title_x=72`（与正文同一起排线，齐左）→ 判不出是扉页标题 → 标题 = 章号 `1`。

    ⚠️ 已知代价：两者的**章数都是 2**（「前言」占位章 + 真章 `1`）—— 章号从编号
    前缀来，与找不找得到标题行无关。标题退化只是少了一个好看的章名，**不会**多造章。
    """
    # ---- (b) 满足：标题不齐左 → 认成章扉页标题 ----
    parsed = parse_pdf(_title_page_pdf(tmp_path / "centered.pdf", 200.0))
    chapters = split_outline(parsed)
    assert [(c.number, c.title) for c in chapters] == [(None, "前言"), ("1", "FOUNDATION")], (
        f"居中的无编号章标题没被认出来：{[(c.number, c.title) for c in chapters]}"
    )
    title_seq = next(i for i, b in enumerate(parsed.blocks) if b.content_md == "FOUNDATION")
    assert chapters[1].heading_seq == title_seq, "章的锚点应当指向扉页标题行"
    assert [s.chapter_title for s in chapters[1].sections] == ["FOUNDATION"] * 2
    assert _real_section_numbers(parsed) == ["1.1", "1.2"]

    # ---- (b) 不满足：与正文同一起排线（齐左）→ 判不出来，标题退回章号 ----
    parsed = parse_pdf(_title_page_pdf(tmp_path / "flush.pdf", 72.0))
    chapters = split_outline(parsed)
    assert [(c.number, c.title) for c in chapters] == [(None, "前言"), ("1", "1")], (
        f"齐左的无编号大标题不该被当成章扉页标题：{[(c.number, c.title) for c in chapters]}"
    )
    # 判不出来时**不编标题**：章的标题退化成章号原貌，没有凭空造一个名字；
    # 节标题仍然是材料里的真标题（`1.1 Applications` → `Applications`）
    assert [s.chapter_title for s in chapters[1].sections] == ["1", "1"]
    assert [s.title for s in chapters[1].sections] == ["Applications", "Requirements"]
    assert _real_section_numbers(parsed) == ["1.1", "1.2"]


# ---------------------------------------------------------------------------
# 对抗 3 · 封面装饰行：字号最大，但一个字都不许变成章
# ---------------------------------------------------------------------------


def test_cover_decoration_lines_do_not_become_chapters(tmp_path: Path) -> None:
    """★ 对抗 3：封面的书名 / 副标题 / 作者行**不得**判成 `heading`，更不得成为章。

    夹具按真实封面的实测字号复刻（书名 24pt、副标题与作者 17pt、日期行 11pt、
    正文 10pt），关键在**该页只有 1 个"普通字号块"**（那个日期行）—— 这正是
    真实封面的形态，也是第 ④ 条判据的立足点。四条合取全部满足，封面整页被否决。

    基线代码（`9950373`）在这里给的是 **2 章**：`Computer Networks: A Systems`
    与 `Approach`（书名被排版成两行，各自成章）。修好之后：真实结构 1 章。

    最后一条断言同样是硬要求：封面行**也不能被借去当章标题**。真章的 `1.1` 在第 2 页，
    候选窗口是第 1–2 页，封面行虽然落在窗口里，但它在**分类阶段就已经被降级成
    `paragraph`** 了，而 `_front_title` 只收 `heading` → 天然出局。于是章标题退回
    章号 `1`，不会出现"封面书名成了某一章的标题"这种半对半错的结果。
    """
    doc = pymupdf.open()
    page1 = doc.new_page()
    _wl(page1, 72, 100, "Computer Networks: A Systems", 24)
    _wl(page1, 72, 140, "Approach", 24)
    _wl(page1, 72, 200, "Release Version 6.1", 17)
    _wl(page1, 72, 240, "Peterson and Davie", 17)
    _wl(page1, 72, 600, "Nov 26, 2019", 11)  # 封面页唯一的"普通字号块"

    page2 = doc.new_page()
    _wl(page2, 72, 100, "1.1 Applications", 13)
    _body(page2, 72, 140, BODY_A)
    _body(page2, 72, 220, BODY_B)

    page3 = doc.new_page()
    _wl(page3, 72, 100, "1.2 Requirements", 13)
    _body(page3, 72, 140, BODY_A)
    _body(page3, 72, 220, BODY_C)
    path = _save(doc, tmp_path / "cover.pdf")

    parsed = parse_pdf(path)
    cover = [b for b in parsed.blocks if b.page_no == 1]

    assert len(cover) == 4, f"封面页的块数变了，夹具需要复核：{_page_text(parsed, 1)!r}"
    assert all(b.block_type == "paragraph" for b in cover), (
        f"封面装饰行被当成了标题：{[(b.block_type, b.content_md) for b in cover]}"
    )
    assert all(b.heading_level is None for b in cover), (
        f"封面装饰行不该带 heading_level：{[(b.heading_level, b.content_md) for b in cover]}"
    )
    # 否决是"降级成正文"，不是"删掉" —— 内容一个字都不能少
    text = _page_text(parsed, 1)
    for line in ("Computer Networks: A Systems", "Approach", "Release Version 6.1",
                 "Peterson and Davie", "Nov 26, 2019"):
        assert line in text, f"封面行被删掉了：{line!r}"

    chapters = split_outline(parsed)
    assert [c.number for c in chapters if c.number is not None] == ["1"], (
        f"封面书名造出了假的章：{[(c.number, c.title) for c in chapters]}"
    )
    assert all("Computer Networks" not in c.title for c in chapters), (
        f"封面书名被借去当章标题了：{[(c.number, c.title) for c in chapters]}"
    )
    assert _real_section_numbers(parsed) == ["1.1", "1.2"]


# ---------------------------------------------------------------------------
# 对抗 4 · 页眉里重复的书名行：跨页重复、字号很大，仍然不许成为章
# ---------------------------------------------------------------------------


def test_repeated_running_head_book_title_never_becomes_a_chapter(tmp_path: Path) -> None:
    """★ 对抗 4：跨页重复的书名行**不得**成为章 —— 两道独立的闸门各挡一种形态。

    形态 (a) **在页眉带里**（顶边落在页高外侧 9% 内）、6 页全都有：由**第 2 批**
    的去噪（信号①页边距带 ∧ ②版心外 ∧ ③跨页重复 ≥ 50% 且 ≥ 3 页 ∧ ④与相邻内容
    隔离）删掉，它压根进不了块表。

    形态 (b) **在版心内**、齐左、与上一行正文行距正常：去噪**删不掉它**（信号①
    不满足），它仍然是 `heading`（16pt ≥ 正文 + 1.5，字号法认它）—— 这一形态才是
    本批要挡的：靠的是闸门③「编号结构定章」。文档里有 `1.1` / `1.2` / `1.3`
    这样的编号节，最浅编号是 depth=2，于是**章由编号前缀定**，三个无编号的书名
    标题一个都不当章根，只是被并进相邻节的块区间（内容一个字不丢）。

    三条断言缺一不可，否则用例会假装通过：
      · 先确认书名行**确实还在块表里**（(b) 的 3 条）—— 否则"没成章"只是因为
        它被删了，测不到本批的规则；
      · 再确认它**确实还是 heading**（`heading_level=1`）—— 否则只是因为被降级
        成正文才没成章，同样测不到；
      · 最后才是"章里没有它"。
    """
    head = "Computer Networks: A Systems"

    # ---- (a) 页眉带里的重复书名：去噪删掉 ----
    doc = pymupdf.open()
    for index in range(6):
        page = doc.new_page()
        _wl(page, 72, 40, head, 16)  # 页眉带（顶边 ≈ 31 < 0.09 × 842）
        _wl(page, 72, 200, f"1.{index + 1} Section", 13)
        _body(page, 72, 240, BODY_A)
    header_path = _save(doc, tmp_path / "running_head.pdf")

    header_parsed = parse_pdf(header_path)
    assert not any(head in text for text in _all_text(header_parsed)), (
        "页眉带里的重复书名没被去噪删掉 —— 那样下面'没成章'就测不到本批的规则了"
    )
    header_chapters = split_outline(header_parsed)
    assert [(c.number, c.title) for c in header_chapters] == [("1", "1")], (
        f"页眉里的书名造出了假的章：{[(c.number, c.title) for c in header_chapters]}"
    )
    assert len(split_sections(header_parsed)) == 6

    # ---- (b) 版心内、跨页重复的书名：去噪删不掉，靠"编号结构定章"挡住 ----
    doc = pymupdf.open()
    for index in range(3):
        page = doc.new_page()
        _wl(page, 72, 200, head, 16)  # 版心内、齐左 → 去噪的信号①不满足
        _body(page, 72, 240, BODY_A)
        _wl(page, 72, 400, f"1.{index + 1} Section", 13)
        _body(page, 72, 440, BODY_B)
    inbody_path = _save(doc, tmp_path / "in_body_head.pdf")

    inbody_parsed = parse_pdf(inbody_path)
    survivors = [b for b in inbody_parsed.blocks if b.content_md == head]
    assert len(survivors) == 3, (
        f"前提不成立：版心内的书名行应当留在块表里 3 条，实际 {len(survivors)} 条"
    )
    assert all(b.block_type == "heading" and b.heading_level == 1 for b in survivors), (
        "前提不成立：版心内的书名行应当仍是 heading（lvl=1），"
        f"实际 {[(b.block_type, b.heading_level) for b in survivors]}"
    )
    inbody_chapters = split_outline(inbody_parsed)
    assert [c.number for c in inbody_chapters] == [None, "1"], (
        f"版心内的重复书名造出了假的章：{[(c.number, c.title) for c in inbody_chapters]}"
    )
    assert all(c.title != head for c in inbody_chapters), "书名行被当成了章标题"
    assert _real_section_numbers(inbody_parsed) == ["1.1", "1.2", "1.3"]


# ---------------------------------------------------------------------------
# 对抗 5 · 正文里被排版成单独一行的短句：普通字号、靠左，不许成为章
# ---------------------------------------------------------------------------


def test_isolated_short_body_sentence_is_not_a_chapter(tmp_path: Path) -> None:
    """★ 对抗 5：正文里孤立成行的一句短话（普通字号、靠左）不许成为章，且不许被删。

    `A network is built from nodes.` 与 `Routing is hard.` 都是正文，只是恰好被
    排版成单独一行。它们同时受两条规则的保护：

      · **字号法**：与正文同为 10pt，不满足"≥ 正文 + 1.5" → 不作 `heading`；
      · **编号结构定章**：即使字号再大一点（本用例的对照组是 `1.1` / `1.2`，
        它们才是有编号的节标题），无编号的行也不会被当成章根。

    基线代码（`9950373`）在这里给的是 **2 章**：`1.1 Applications` 与
    `1.2 Requirements` 各自成章（"章 = 最浅一层标题"在没有 depth=1 编号时的退化），
    而正确结果是 1 章 `1`。
    """
    doc = pymupdf.open()
    page1 = doc.new_page()
    _wl(page1, 72, 100, "1.1 Applications", 13)
    _wl(page1, 72, 150, "A network is built from nodes.", 10)  # 孤立成行的短句
    _body(page1, 72, 200, BODY_A)
    _body(page1, 72, 280, BODY_B)

    page2 = doc.new_page()
    _wl(page2, 72, 100, "1.2 Requirements", 13)
    _wl(page2, 72, 150, "Routing is hard.", 10)  # 另一句孤立短行
    _body(page2, 72, 200, BODY_A)
    _body(page2, 72, 280, BODY_C)
    path = _save(doc, tmp_path / "short_lines.pdf")

    parsed = parse_pdf(path)
    by_text = _by_text(parsed)

    for sentence in ("A network is built from nodes.", "Routing is hard."):
        assert sentence in by_text, f"孤立成行的正文短句被删掉了：{sentence!r}"
        assert by_text[sentence].block_type == "paragraph", f"{sentence!r} 被判成了标题"
        assert by_text[sentence].heading_level is None

    chapters = split_outline(parsed)
    assert [(c.number, c.title) for c in chapters] == [("1", "1")], (
        f"孤立成行的短句造出了假的章：{[(c.number, c.title) for c in chapters]}"
    )
    assert [s.number for s in chapters[0].sections] == ["1.1", "1.2"]
    # 两句都在某一节的块区间里（不静默丢内容）
    covered = {i for s in split_sections(parsed) for i in range(s.start_seq, s.end_seq + 1)}
    for sentence in ("A network is built from nodes.", "Routing is hard."):
        index = next(i for i, b in enumerate(parsed.blocks) if b.content_md == sentence)
        assert index in covered, f"{sentence!r} 落在所有节的块区间之外"


# ---------------------------------------------------------------------------
# 反向护栏 · 章扉页的大字标题：第 ④ 条不许误伤它
# ---------------------------------------------------------------------------


def test_chapter_title_page_large_title_stays_a_heading(tmp_path: Path) -> None:
    """★ 反向护栏：**章扉页**的大字标题必须**仍然**判成 `heading`（封面否决不许误伤）。

    这是第 ④ 条判据（"该页普通字号块 ≤ 1"）的护栏：章扉页与封面在①②③三条上
    **完全一样**（都在前 2 页、都无编号、字号都最大），把它们分开的只有第 ④ 条 ——
    封面整页只有大字 + 一个日期行，而章扉页（本教材第 9 页实测 9 个普通字号块）
    后面紧跟着整页正文。本夹具给扉页配了 3 个正文段：

      · 若第 ④ 条不存在或阈值放宽 → `FOUNDATION` 被否决成 `paragraph`，
        这一条立刻翻红；
      · 第 ④ 条在 → 它保住 `heading lvl=1`，并且**顺带**被闸门③认成章标题，
        于是真章的 `title` 是 `FOUNDATION` 而不是退化的章号 `1`。

    同时钉住一个可核对的实现细节：章扉页标题块既被「前言」占位章的块区间
    （0–3）收着，也是这一章的 `heading_seq`（锚点）—— 扉页属于前置内容的排版，
    但它确实是这一章的标题行，两处指向它是**故意**的（`source_block_id` 没有唯一
    约束，见 `app/models/outline.py`）。
    """
    doc = pymupdf.open()
    page1 = doc.new_page()
    _wl(page1, 200, 100, "FOUNDATION", 20)  # 章扉页标题：大字 + 居中
    _body(page1, 72, 160, BODY_A)
    _body(page1, 72, 240, BODY_B)
    _body(page1, 72, 320, BODY_C)

    page2 = doc.new_page()
    _wl(page2, 72, 100, "1.1 Applications", 13)
    _body(page2, 72, 140, BODY_A)
    _body(page2, 72, 220, BODY_B)

    page3 = doc.new_page()
    _wl(page3, 72, 100, "1.2 Requirements", 13)
    _body(page3, 72, 140, BODY_A)
    _body(page3, 72, 220, BODY_C)
    path = _save(doc, tmp_path / "title_page.pdf")

    parsed = parse_pdf(path)
    title_block = _by_text(parsed)["FOUNDATION"]

    assert title_block.block_type == "heading", (
        "章扉页的大字标题被封面装饰行否决规则误伤了（第 ④ 条失效）"
    )
    assert title_block.heading_level == 1, (
        f"章扉页标题的层级不是 1：{title_block.heading_level}"
    )
    # 第 ④ 条的立足点：这一页有 ≥ 2 个普通字号块 → 它是"正文页"，不是封面
    page1_body = [b for b in parsed.blocks if b.page_no == 1 and b.block_type == "paragraph"]
    assert len(page1_body) == 3, (
        f"夹具的扉页正文段数变了（第 ④ 条靠它把扉页与封面分开）：{len(page1_body)}"
    )

    chapters = split_outline(parsed)
    assert [(c.number, c.title) for c in chapters] == [(None, "前言"), ("1", "FOUNDATION")], (
        f"章扉页标题没有被认成章：{[(c.number, c.title) for c in chapters]}"
    )
    title_seq = next(i for i, b in enumerate(parsed.blocks) if b.content_md == "FOUNDATION")
    assert chapters[1].heading_seq == title_seq
    assert _real_section_numbers(parsed) == ["1.1", "1.2"]
