"""页眉 / 页脚 / 页码去噪 + heading 否决 + 图注识别（第二批 · 归属 P1）。

这个文件的重心**不是**"在真实教材上删得干净"（那很容易），而是**"不误删"**：
去噪是一条不可逆的内容丢失路径，删错一段正文比多留几个噪声块严重得多。
所以下面每一类"必须保留"的情形都有一条对抗性用例，且每条都写明**是哪一条信号
把它救下来的** —— 少任何一条信号，这些用例就会翻红：

  信号① 页边距带      便宜的预筛（页高外侧 9% / 内侧 91%）
  信号② 版心外        块在本文档**自己**的正文纵向范围之外
  信号③ 跨页重复      同一垂直位置覆盖 ≥ 50% 的页面且不少于 3 页
  信号④ 与相邻内容隔离  与同页最近字块的空隙 ≥ 1.4 个行高

四条是**合取**。真实教材（*Computer Networks: A Systems Approach* 前 30 页）的
实测对照见 `tests/test_qa_parse_real_material.py`，对抗样本现场生成、不依赖外部素材。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.parse import parse_pdf, split_outline

CJK_FONT = "china-s"

#: A4 默认页面（`pymupdf.open().new_page()` = 595 × 842）上的版式常量。
#: 口径与 `app/parse/pdf.py` 的 `EDGE_ZONE_*` 一致，但这里**不** import 实现常量：
#: 用例要钉的是"这些位置的块该不该留"，不是"实现里的比例是多少"。
PAGE_HEIGHT = 842.0
HEADER_Y = 40.0  # 页眉基线 → top ≈ 31（0.09 × 842 = 75.8 以内）
FOOTER_Y = 810.0  # 页脚基线 → top ≈ 801（0.91 × 842 = 766.2 以外）
BODY_Y = 200.0  # 正文基线 → top ≈ 190（在版心里）


def _w(page: pymupdf.Page, x: float, y: float, text: str, size: float = 10) -> None:
    page.insert_text((x, y), text, fontname=CJK_FONT, fontsize=size)


def _wl(page: pymupdf.Page, x: float, y: float, text: str, size: float = 10) -> None:
    """写**拉丁**文本用默认字体（Helvetica）。

    ⚠️ 不能拿 `china-s` 写英文：那套字体的拉丁字是**全角**的（1 个字符 = 1 em），
    一段 66 字符的英文会横跨 660pt 而被页面右边界**截断** —— 测试会莫名其妙地
    少半句话。中英混排的教材里没这个问题，是夹具自己的坑。
    """
    page.insert_text((x, y), text, fontsize=size)


def _paged(path: Path, pages: int, *, header: str = "网络原理讲义") -> pymupdf.Document:
    """每页：页眉 + 两行正文 + 页脚页码。返回**未保存**的 doc，调用方可继续加料。"""
    doc = pymupdf.open()
    for index in range(pages):
        page = doc.new_page()
        _w(page, 72, HEADER_Y, header, 9)
        _w(page, 72, BODY_Y, f"第{index + 1}页的正文内容，这一页讲了一些具体的东西。")
        _w(page, 72, BODY_Y + 16, f"这是第{index + 1}页的第二行正文，用来把版心撑起来。")
        _w(page, 300, FOOTER_Y, f"{index + 1}", 9)
    return doc


def _save(doc: pymupdf.Document, path: Path) -> Path:
    doc.save(str(path))
    doc.close()
    return path


def _contents(doc) -> list[str]:  # noqa: ANN001
    return [b.content_md for b in doc.blocks]


# ---------------------------------------------------------------------------
# 0. 去噪本身：页眉 / 页脚 / 页码被去掉，正文一个不少
# ---------------------------------------------------------------------------


def test_header_footer_and_page_numbers_are_removed(tmp_path: Path) -> None:
    """★ 3 页的重复页眉、页脚页码全部去掉，只剩正文（6 个正文块）。"""
    path = _save(_paged(tmp_path / "noise.pdf", 3), tmp_path / "noise.pdf")
    doc = parse_pdf(path)

    assert all("网络原理讲义" not in text for text in _contents(doc)), "页眉没去掉"
    assert [b for b in doc.blocks if b.content_md.strip().isdigit()] == [], "页码没去掉"
    assert len(doc.blocks) == 6
    assert [b.page_no for b in doc.blocks] == [1, 1, 2, 2, 3, 3]
    assert all(b.block_type == "paragraph" for b in doc.blocks)


def test_denoise_records_what_it_removed(tmp_path: Path) -> None:
    """★ 去掉的块数必须如实登记 —— 去噪**不许静默丢内容**。"""
    path = _save(_paged(tmp_path / "noise.pdf", 3), tmp_path / "noise.pdf")
    doc = parse_pdf(path)
    notes = [n for n in doc.uncertain_notes if "去噪" in n.message or "页眉" in n.message]

    assert len(notes) == 1, f"去噪没有留下可核对的说明：{doc.uncertain_notes}"
    message = notes[0].message
    assert notes[0].kind == "other"
    assert notes[0].severity == "low"
    assert "6 个" in message, f"删了 6 块（3 页眉 + 3 页码）却没报准数：{message!r}"
    assert "页眉 3 块" in message
    assert "页码 3 块" in message


def test_document_without_repeated_edge_lines_gets_no_note(tmp_path: Path) -> None:
    """★ 没删东西就**不许**乱报存疑 —— 无端的存疑会让用户以为材料有问题。"""
    doc = pymupdf.open()
    page = doc.new_page()
    _w(page, 72, BODY_Y, "这份材料只有一页正文，没有页眉页脚页码。")
    path = _save(doc, tmp_path / "plain.pdf")

    parsed = parse_pdf(path)
    assert len(parsed.blocks) == 1
    assert parsed.uncertain_notes == []


def test_two_page_repetition_is_not_enough_to_denoise(tmp_path: Path) -> None:
    """★ 信号③的绝对下限：**2 页的重复不足以证明"每页都来一遍"**，宁可漏删。

    这条钉住的是方向取舍：把"碰巧重了两页"的正文短行当成页眉删掉是不可逆的
    内容丢失，而漏删只是多留两个噪声块。
    """
    path = _save(_paged(tmp_path / "noise2.pdf", 2), tmp_path / "noise2.pdf")
    doc = parse_pdf(path)
    assert [b.content_md for b in doc.blocks if b.content_md.strip().isdigit()] == ["1", "2"]
    assert sum(1 for b in doc.blocks if b.content_md == "网络原理讲义") == 2


# ---------------------------------------------------------------------------
# 对抗 1 · 章节扉页的标题短行：本身很短，但必须保留、且判 heading
# ---------------------------------------------------------------------------


def test_chapter_title_page_short_line_survives_denoise(tmp_path: Path) -> None:
    """★ 对抗 1：章节扉页的标题短行**必须保留**，且判成 `heading`。

    构造刻意最像页眉：标题只有 6 个字、字号大、还排在**页边距带里**
    （top ≈ 64 < 0.09 × 842），并且**两页上出现在同一垂直位置** ——
    信号①（页边距带）②（版心外）④（与相邻内容隔离）它**全部**满足，
    真正把它救下来的是**信号③跨页重复**：6 页里只有 2 页有这个标题，
    2/6 = 33% < 50%，不构成"每页都来一遍"的页眉。
    （真实教材里章节扉页的标题也是每章才出现一次，正是这个道理。）
    """
    doc = _paged(tmp_path / "chapters.pdf", 6)
    _w(doc[0], 72, 80, "第2章 网络层", 16)
    _w(doc[3], 72, 80, "第3章 应用层", 16)
    path = _save(doc, tmp_path / "chapters.pdf")

    parsed = parse_pdf(path)
    titles = {b.content_md: b for b in parsed.blocks if "章" in b.content_md}

    assert "第2章 网络层" in titles, "章节扉页的标题被当成页眉删掉了（不可逆的内容丢失）"
    assert "第3章 应用层" in titles, "章节扉页的标题被当成页眉删掉了（不可逆的内容丢失）"
    assert titles["第2章 网络层"].block_type == "heading"
    assert titles["第2章 网络层"].heading_level == 1
    assert titles["第2章 网络层"].page_no == 1
    # 同一份材料里的真页眉照样被去掉 —— 说明去噪在跑，不是"整页没处理"
    assert all("网络原理讲义" not in text for text in _contents(parsed))


# ---------------------------------------------------------------------------
# 对抗 2 · 表格跨页的续表表头：跨页重复，但**不是**页眉
# ---------------------------------------------------------------------------


def test_repeated_table_header_line_is_not_a_page_header(tmp_path: Path) -> None:
    """★ 对抗 2：表格跨页的**续表表头**跨页重复，但不许当页眉删掉。

    构造：表头行排在页边距带里（top ≈ 60 < 75.8）且**三页都在同一位置** ——
    信号①②③它都满足，把它救下来的是**信号④"与相邻内容隔离"**：
    续表表头下面紧跟着表格行（空隙 3pt < 1.4 个行高），而真页眉页脚与版心之间
    有一道明显的空白。**只看"跨页重复 + 位置"必然误删这一条**，
    这正是本批最容易踩的坑（见 `app/parse/pdf.py` 的 `EDGE_ISOLATION_RATIO`）。
    """
    doc = pymupdf.open()
    for index in range(3):
        page = doc.new_page()
        _w(page, 72, HEADER_Y, "网络原理讲义", 9)  # 真页眉
        _w(page, 72, 70, "表 2.1 协议与作用。", 10)  # 续表表头（贴着自己的表格行）
        for row in range(8):
            _w(page, 72, 85 + row * 13, f"第{row + 1}行：协议{index + 1}-{row + 1}", 10)
        _w(page, 300, FOOTER_Y, f"{index + 1}", 9)
    path = _save(doc, tmp_path / "table.pdf")

    parsed = parse_pdf(path)
    joined = "\n".join(_contents(parsed))

    assert "表 2.1 协议与作用。" in joined, (
        "跨页重复的**续表表头**被当成页眉删掉了 —— 它是正文的一部分"
    )
    for row in range(8):
        assert f"第{row + 1}行：协议2-{row + 1}" in joined, f"第 {row + 1} 行表格内容丢了"
    # 真页眉与页码仍然被去掉（去噪在跑）
    assert all("网络原理讲义" not in text for text in _contents(parsed))


# ---------------------------------------------------------------------------
# 对抗 3 · 正文里孤立成行的数字
# ---------------------------------------------------------------------------


def test_isolated_number_line_in_body_is_kept(tmp_path: Path) -> None:
    """★ 对抗 3：正文里孤立成行的数字**必须保留**（"共 3 个节点"被排成单独一行）。

    它同时钉住两件事：
      · **去噪**：它在版心**里面**（top ≈ 390），信号①就不满足 → 不会被当页码
        （纯数字不再等于页码 —— 页码必须配位置信号）；
      · **heading 否决**：孤立的 `3` 是 depth=1、无标题文字的单级编号
        → 不作 heading，落成 `paragraph`（第一批这里会变成"某一章"）。
    """
    doc = _paged(tmp_path / "isolated.pdf", 3)
    for index in range(3):
        _w(doc[index], 72, 390, "3")  # 正文里孤立成行的数字
        _w(doc[index], 72, 430, "上面这个数字是正文的一部分，说的是节点个数。")
    path = _save(doc, tmp_path / "isolated.pdf")

    parsed = parse_pdf(path)
    numbers = [b for b in parsed.blocks if b.content_md == "3"]

    assert len(numbers) == 3, "正文里孤立成行的数字被当成页码删掉了"
    assert [b.page_no for b in numbers] == [1, 2, 3]
    for block in numbers:
        assert block.block_type == "paragraph", "孤立的数字不该成为 heading"
        assert block.heading_level is None


# ---------------------------------------------------------------------------
# 对抗 4 · 代码块 / 公式块里的数字行
# ---------------------------------------------------------------------------


def test_number_line_inside_a_code_block_is_kept(tmp_path: Path) -> None:
    """★ 对抗 4：代码块里的数字行**必须原样保留**。

    代码块的行距紧、行尾不带句末标点，因此会被合并成**一个多行块**；
    它既不在页边距带里，也不满足"单行短块"的形态 —— 两条都挡在门外。
    这里断言的是整段代码一字不差，包括那一行孤零零的 `37`。
    """
    code_lines = ["for i in range(3):", "37", "print(i)", "end"]
    doc = _paged(tmp_path / "code.pdf", 3)
    for index in range(3):
        for offset, line in enumerate(code_lines):
            _w(doc[index], 72, 300 + offset * 13, line, 10)
    path = _save(doc, tmp_path / "code.pdf")

    parsed = parse_pdf(path)
    joined = "\n".join(_contents(parsed))

    assert "37" in joined, "代码块里的数字行被删掉了"
    for line in code_lines:
        assert line in joined, f"代码行丢了：{line!r}"
    # 代码块被合并成一个多行块（不是被切成 4 块，更没有被删）
    code_blocks = [b for b in parsed.blocks if "for i in range(3):" in b.content_md]
    assert len(code_blocks) == 3
    # 合并规则是"拉丁字母之间插一个空格"（`_join_lines`），所以拼出来是带空格的
    assert code_blocks[0].content_md == "for i in range(3): 37 print(i) end"
    # 页内行号：页眉占第 1 行、两行正文占 2–3 行，代码块占 4–7 行（没有被拆开）
    assert (code_blocks[0].line_start, code_blocks[0].line_end) == (4, 7)


def test_formula_number_line_in_body_is_kept(tmp_path: Path) -> None:
    """公式块的编号行（`(3.1)` 这类）在版心里，同样不许动。"""
    doc = _paged(tmp_path / "formula.pdf", 3)
    for index in range(3):
        _w(doc[index], 72, 470, "E = mc2")
        _w(doc[index], 400, 470, "(3.1)")
    path = _save(doc, tmp_path / "formula.pdf")

    parsed = parse_pdf(path)
    joined = "\n".join(_contents(parsed))
    assert "E = mc2" in joined, "公式块被删了"
    assert "(3.1)" in joined, "公式编号行被删了"


# ---------------------------------------------------------------------------
# heading 否决规则
# ---------------------------------------------------------------------------


def test_bare_number_line_is_not_a_heading(tmp_path: Path) -> None:
    """★ 整行只有编号、没有标题文字的单级编号 → **不作 heading**。

    第一批的成因：`blocks.split_heading_number` 把纯数字（`37`）拆成 depth=1
    的编号，该行再通过字号闸 → 判成 `heading_level = 1`。真实教材前 30 页因此
    产出 34 章（真实结构只有 3 章）。这条否决规则直接堵住它。
    """
    doc = pymupdf.open()
    page = doc.new_page()
    _w(page, 72, 120, "37", 10)  # 孤立编号（页码形态）
    _w(page, 72, 200, "3.1 Routing basics", 13)  # 多级编号 → 仍是标题
    _w(page, 72, 260, "1 Introduction", 13)  # 单级编号但**有标题文字** → 仍是标题
    _w(page, 72, 320, "正文内容，用来定正文字号。")
    path = _save(doc, tmp_path / "veto.pdf")

    parsed = parse_pdf(path)
    by_text = {b.content_md: b for b in parsed.blocks}

    assert by_text["37"].block_type == "paragraph", "孤立的 37 不该成为 heading"
    assert by_text["37"].heading_level is None
    assert by_text["3.1 Routing basics"].block_type == "heading"
    assert by_text["3.1 Routing basics"].heading_level == 2
    assert by_text["1 Introduction"].block_type == "heading", (
        "带标题文字的单级编号被否决规则误伤了"
    )


def test_heading_veto_collapses_the_outline_to_real_structure(tmp_path: Path) -> None:
    """★ 页码不该造出"章"：一堆孤立数字的前 30 页式材料只该有真实的章。"""
    doc = pymupdf.open()
    page = doc.new_page()
    _w(page, 72, 90, "第1章 网络层", 18)
    _w(page, 72, 140, "1.1 路由基础", 13)
    _w(page, 72, 180, "正文。", 10)
    for index, number in enumerate(("5", "6", "7")):  # 像页码一样孤立成行
        _w(page, 300, 240 + index * 20, number, 10)
    _w(page, 72, 330, "第2章 应用层", 18)
    _w(page, 72, 380, "正文二。", 10)
    path = _save(doc, tmp_path / "outline.pdf")

    parsed = parse_pdf(path)
    chapters = split_outline(parsed)

    assert [c.number for c in chapters] == ["第1章", "第2章"], (
        f"页码行造出了假的章：{[(c.number, c.title) for c in chapters]}"
    )


# ---------------------------------------------------------------------------
# 图注识别（含"正文以 Figure 开头"的防误判）
# ---------------------------------------------------------------------------


def test_figure_and_table_captions_become_image_caption(tmp_path: Path) -> None:
    """★ `Figure x.y.: ...` / `Table x.y: ...` → `image_caption`（第一批零产出）。"""
    doc = pymupdf.open()
    page = doc.new_page()
    _wl(page, 116, 200, "Figure 1.1.: A multimedia application including videoconferencing.", 10)
    _wl(page, 116, 240, "Table 2.1: Comparison of protocols.", 10)
    _w(page, 72, 300, "正文段落，讲的是这张图想表达什么。", 10)
    path = _save(doc, tmp_path / "caption.pdf")

    parsed = parse_pdf(path)
    captions = [b for b in parsed.blocks if b.block_type == "image_caption"]

    assert [b.content_md for b in captions] == [
        "Figure 1.1.: A multimedia application including videoconferencing.",
        "Table 2.1: Comparison of protocols.",
    ]
    for block in captions:
        assert block.heading_level is None, "图注不该带 heading_level"


def test_body_sentence_starting_with_figure_is_not_a_caption(tmp_path: Path) -> None:
    """★ 防误判（真实教材实测）：以 `Figure` 开头的**正文**不是图注。

    真实教材 p14 有一段正文开头就是
    `Figure 1.3 shows a pair of shows a set of nodes, ...`（628 字符）。
    只看"以 Figure 开头"会把它判成图注**并把一段正文切碎** —— 这是本批最重要
    的一条防误判用例。拦住它的是**编号后的分隔符**（真图注是 `Figure 1.1.:`，
    这里 `1.3` 后面直接跟 `shows`），长度上限是第二道同样的护栏。
    """
    lines = (
        "Figure 1.3 shows a pair of shows a set of nodes, each of which is attached to one",
        "or more point-to-point links. Those nodes that are attached to at least two links",
        "run software that forwards data received on one link out on another. If organized",
        "in a systematic way, these forwarding nodes form a switched network.",
    )
    doc = pymupdf.open()
    page = doc.new_page()
    for offset, line in enumerate(lines):
        _wl(page, 72, 200 + offset * 14, line, 10)
    path = _save(doc, tmp_path / "figure_body.pdf")

    parsed = parse_pdf(path)
    assert all(b.block_type != "image_caption" for b in parsed.blocks), (
        "以 Figure 开头的正文被错判成了图注（会切碎正文）"
    )
    # 那 4 行正文必须原样合并成**一块**（没有被切碎、没有被删）
    body_blocks = [b for b in parsed.blocks if "Figure 1.3 shows a pair of" in b.content_md]
    assert len(body_blocks) == 1, f"那段正文被切碎或丢掉了：{[b.content_md for b in parsed.blocks]}"
    assert body_blocks[0].block_type == "paragraph"
    assert len(body_blocks[0].content_md) > 300, "正文被截断了"
    assert "form a switched network." in body_blocks[0].content_md


def test_glued_caption_is_split_from_the_following_body(tmp_path: Path) -> None:
    """★ 图注与紧随正文粘连时**拆成两块**（图注 + 正文）。

    构造的是最难的一种：图注**不以句末标点收尾**（`... (b) multiple-access`），
    于是段判据看不出"图注到此为止"，图注会被并进后面的正文。切点取**第一行之后**
    （本教材的图注都是单行），两块的 `line_start` / `line_end` 各自独立、不重叠。
    """
    caption = "Figure 3.1.: Direct links: (a) point-to-point; (b) multiple-access"
    doc = pymupdf.open()
    page = doc.new_page()
    _wl(page, 116, 200, caption, 10)
    _w(page, 72, 214, "物理链路可以是一对节点之间的专用连接", 10)
    _w(page, 72, 228, "也可以由多个节点共享。", 10)
    path = _save(doc, tmp_path / "glued.pdf")

    parsed = parse_pdf(path)
    blocks = parsed.blocks

    assert len(blocks) == 2, f"粘连的图注没有被拆开：{[b.content_md for b in blocks]}"
    caption_block, body_block = blocks
    assert caption_block.block_type == "image_caption"
    assert caption_block.content_md == caption
    assert body_block.block_type == "paragraph"
    assert body_block.content_md == "物理链路可以是一对节点之间的专用连接也可以由多个节点共享。"
    # 行号不重叠：图注占第 1 行，正文从第 2 行起
    assert caption_block.line_start == 1 and caption_block.line_end == 1
    assert body_block.line_start == 2 and body_block.line_end == 3


# ---------------------------------------------------------------------------
# 目录页里孤立成行的页码碎片
# ---------------------------------------------------------------------------


def test_toc_page_number_fragments_are_removed(tmp_path: Path) -> None:
    """★ 目录页里孤立成行的页码（`37` 这种）去掉；正文里的孤立数字仍然保留。

    目录页的页码碎片**不在页边距带里**（它在版心内、紧贴着自己的目录行），
    所以页眉页脚那套位置信号救不了它。这里靠的是**结构信号**：
    一页里含 ≥ 4 条"前导点行"就是目录页，目录页里的孤立数字是页码碎片。
    对照组（同文件下一页的正文 `3`）必须留着 —— 没有这条对照，
    这个用例就只是"凡是孤立数字都删"，那正是要避免的误删。
    """
    doc = pymupdf.open()
    toc = doc.new_page()  # 第 1 页：目录页
    _w(toc, 72, 100, "TABLE OF CONTENTS", 12)
    for index in range(5):
        _w(toc, 72, 140 + index * 18, f"1.{index + 1} 章节标题 . . . . . . . . . {index + 9}", 10)
    _w(toc, 300, 250, "37", 10)  # 目录行溢出的页码碎片

    body = doc.new_page()  # 第 2 页：普通正文页
    _w(body, 72, 100, "第1章 正文开始", 14)
    _w(body, 72, 140, "正文内容。", 10)
    _w(body, 72, 200, "3", 10)  # 正文里孤立成行的数字（**非**目录页）
    _w(body, 72, 240, "这里说的是节点个数。", 10)
    path = _save(doc, tmp_path / "toc.pdf")

    parsed = parse_pdf(path)
    contents = _contents(parsed)

    assert "37" not in contents, "目录页的页码碎片没去掉"
    assert "3" in contents, "正文里孤立成行的数字被误删了"
    assert sum(1 for text in contents if "章节标题" in text) == 5, "目录行本身被动了"
    assert "第1章 正文开始" in contents and "正文内容。" in contents
