"""QA 独立验证 · A1-4 / A1-6：**多栏（两栏）版式**的解析行为。

为什么单独开一份文件
--------------------
现有 PDF 用例（`tests/test_parse_pdf.py`、`test_parse_denoise.py`、
`test_qa_parse_real_material.py`）用的都是**单栏**素材。两栏是教材/论文最常见的
版式之一，而它在解析链路里有一个绕不开的问题：**阅读顺序**。

人读两栏是「先把左栏读完，再读右栏」；而按坐标排序（先 y 后 x）得到的是
「左右栏逐行交错」。两种顺序在**单栏**下完全一样，所以单栏用例永远测不出来。

本文件只做黑盒验证：一律走稳定入口 `parse_material()`，不直接调私有函数。

实测结论（本次跑出来的，数字是真的）
----------------------------------
1. 块序列 **是逐行交错的**：`L1, R1, L2, R2, L3, R3`
   —— 不是人读顺序。期望的 `L1, L2, L3, R1, R2, R3` 用 `xfail(strict=False)`
   钉住（见 `test_two_column_reads_left_column_before_right`）。
2. **成因已定位**：`app/parse/pdf.py::_raw_blocks` 调的是
   `page.get_text("dict", sort=True)`。PyMuPDF **不加 `sort`** 时的 block 顺序
   本来就是**按栏**的（实测：`L1,L2,L3,R1,R2,R3`）；是 `sort=True` 把它按
   坐标重排成了逐行交错。诊断用例见 `test_root_cause_is_pymupdf_sort_true`。
3. 文本**没有丢**：6 行原文一行不少，且每个块的内容都是该页文本层原文的
   **连续子串**（逐字校验，见 `test_two_column_text_is_not_lost`）。
4. `line_start` / `line_end` 在两栏下**仍然自洽但语义变弱**：每个块都是单行
   （`line_start == line_end`），页内行号按**当前块顺序**从 1 连续排到 6，
   即 `L1→1, R1→2, L2→3, R2→4, L3→5, R3→6`。它记录的是"块在**输出序列**里的
   位置"，**不是**"这一行在页面上的第几行"（左栏第 2 行是 `line=3`）。
   两栏下拿 `page_no + line_start/line_end` 去框原文会框到**右栏的同一行**，
   所以 A1-6 的"可定位"在两栏材料上会指错位置 —— 这一条**没有**单独写 xfail
   （它需要的是"行号按列重新定义"这种更深的设计决定），只在这里如实记录。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.parse import parse_material

CJK_FONT = "china-s"

#: 左栏 / 右栏的**明确分栏坐标**（pt）。左栏 x=60、右栏 x=330，栏间留 190pt 空隙，
#: 远大于一个行高 —— 任何"按 x 分栏"的实现都能清楚地把两栏分开。
LEFT_X = 60.0
RIGHT_X = 330.0
FIRST_Y = 100.0
LINE_STEP = 30.0

LEFT_LINES = ["L1 左栏第一行", "L2 左栏第二行", "L3 左栏第三行"]
RIGHT_LINES = ["R1 右栏第一行", "R2 右栏第二行", "R3 右栏第三行"]

#: 人读顺序：**先把左栏读完，再读右栏**。
EXPECTED_HUMAN_ORDER = LEFT_LINES + RIGHT_LINES
#: 当前实测顺序：按坐标（先 y 后 x）排序 → 左右栏逐行交错。
OBSERVED_ROW_MAJOR_ORDER = [line for pair in zip(LEFT_LINES, RIGHT_LINES, strict=True) for line in pair]


def make_two_column_pdf(path: Path) -> Path:
    """一页两栏 PDF：左右各 3 行，行首坐标固定，便于断言分栏。"""
    doc = pymupdf.open()
    page = doc.new_page()
    for index, text in enumerate(LEFT_LINES):
        page.insert_text(
            (LEFT_X, FIRST_Y + index * LINE_STEP), text, fontname=CJK_FONT, fontsize=10
        )
    for index, text in enumerate(RIGHT_LINES):
        page.insert_text(
            (RIGHT_X, FIRST_Y + index * LINE_STEP), text, fontname=CJK_FONT, fontsize=10
        )
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def two_column_pdf(tmp_path: Path) -> Path:
    return make_two_column_pdf(tmp_path / "two_column.pdf")


def _page_text(path: Path) -> str:
    """该页的文本层原文（pymupdf 的**自然** block 顺序，不加 sort）。"""
    with pymupdf.open(path) as doc:
        return doc[0].get_text("text")


def _contents(path: Path) -> list[str]:
    return [block.content_md for block in parse_material(path).blocks]


def _column_of(text: str) -> str:
    """这一块属于哪一栏（按内容前缀判定，不看坐标）。"""
    return "L" if text.startswith("L") else "R"


# ---------------------------------------------------------------------------
# 文本不丢（与阅读顺序无关，永远该成立）
# ---------------------------------------------------------------------------


def test_two_column_text_is_not_lost(two_column_pdf: Path) -> None:
    """★ 两栏文字一行都不能丢，且每块内容必须是**该页原文的连续子串**。

    逐字校验：把块内容与页原文都先去掉空白再比 —— 空白是排版产物，
    去掉它不影响"哪几个字"这个判断，但能避免行距/字距带来的假失败。
    """
    contents = _contents(two_column_pdf)
    page_chars = "".join(_page_text(two_column_pdf).split())

    assert len(contents) == len(LEFT_LINES) + len(RIGHT_LINES), (
        f"两栏 6 行应当是 6 个块，实际 {len(contents)}：{contents}"
    )
    for content in contents:
        assert "".join(content.split()) in page_chars, f"{content!r} 不是页原文的连续子串"

    joined = "\n".join(contents)
    for line in EXPECTED_HUMAN_ORDER:
        assert line in joined, f"原文行丢了：{line!r}"


def test_two_column_blocks_never_mix_columns(two_column_pdf: Path) -> None:
    """一个块里不能同时出现左右栏的内容 —— 那说明两栏被错误地并成了一段。"""
    for content in _contents(two_column_pdf):
        assert "左栏" in content or "右栏" in content
        assert not ("左栏" in content and "右栏" in content), f"两栏被并进同一个块：{content!r}"


# ---------------------------------------------------------------------------
# seq / page_no / 行号
# ---------------------------------------------------------------------------


def test_two_column_seq_is_global_and_continuous(two_column_pdf: Path) -> None:
    """`seq` 全局连续从 0 开始，与块列表顺序一致。"""
    doc = parse_material(two_column_pdf)
    assert [seq for seq, _ in doc.numbered()] == list(range(len(doc.blocks)))


def test_two_column_page_no_is_one_and_every_block_has_it(two_column_pdf: Path) -> None:
    doc = parse_material(two_column_pdf)
    assert doc.page_count == 1
    for block in doc.blocks:
        assert block.page_no == 1
        assert block.bbox is not None and len(block.bbox) == 4


def test_two_column_line_numbers_are_single_line_and_contiguous(two_column_pdf: Path) -> None:
    """实测记录：两栏下 `line_start / line_end` 仍是**单行、连续**的整数。

    实测值（本次）：`L1→1, R1→2, L2→3, R2→4, L3→5, R3→6`。

    ⚠️ 它记录的是"块在**输出序列**里的位置"，**不是**"这行在页面上是第几行"：
    左栏第二行拿到的是 `line=3`。因此两栏材料的溯源会指到右栏的同一行
    （见模块 docstring 第 4 条），这里只钉住"字段本身仍然自洽"。
    """
    blocks = parse_material(two_column_pdf).blocks
    line_numbers = []
    for block in blocks:
        assert block.line_start is not None and block.line_end is not None
        assert block.line_start == block.line_end, "两栏单行素材不该出现多行块"
        assert block.line_start >= 1
        line_numbers.append(block.line_start)

    assert line_numbers == list(range(1, len(blocks) + 1)), (
        f"页内行号应当按输出顺序从 1 连续：实测 {line_numbers}"
    )


# ---------------------------------------------------------------------------
# 阅读顺序
# ---------------------------------------------------------------------------


def test_two_column_order_is_one_of_the_two_plausible_layouts(two_column_pdf: Path) -> None:
    """弱不变式：块顺序只能是"按栏"或"逐行交错"两种之一，不能是乱的。

    这条在**当前**（逐行交错）与**修好之后**（按栏）都成立，所以它不阻挡修复。
    """
    contents = _contents(two_column_pdf)
    assert contents in (EXPECTED_HUMAN_ORDER, OBSERVED_ROW_MAJOR_ORDER), (
        f"块顺序既不是按栏也不是逐行交错：{contents}"
    )


def test_two_column_within_column_relative_order_is_preserved(two_column_pdf: Path) -> None:
    """硬用例：**栏内**的相对顺序必须是原文顺序（这条现在就成立，修复后也成立）。

    左栏的 L1→L2→L3、右栏的 R1→R2→R3 无论整体顺序怎么排都不该被打乱 ——
    栏内乱序才是真正的"内容错位"。
    """
    contents = _contents(two_column_pdf)
    left = [c for c in contents if _column_of(c) == "L"]
    right = [c for c in contents if _column_of(c) == "R"]
    assert left == LEFT_LINES
    assert right == RIGHT_LINES


@pytest.mark.xfail(
    strict=False,
    reason=(
        "当前实现按坐标排序（先 y 后 x），两栏是**逐行交错**的"
        "（L1,R1,L2,R2,L3,R3），不是人读顺序。"
        "需要的改动：在 app/parse/pdf.py::parse_pdf 里加一步**按栏聚块**"
        "（用 bbox 的 x 区间把同一页的块分栏，栏内按 y、栏间按 x 排序），"
        "或者在 _raw_blocks 里改用 pymupdf 不加 sort 的 block 顺序"
        "（实测它本来就是按栏的）。"
        "这属于版式模型层面的决定，**不在本次只写测试的范围内**，所以只钉住不修。"
        "strict=False：实现改成按栏读之后本条就会 XPASS，不算失败。"
    ),
)
def test_two_column_reads_left_column_before_right(two_column_pdf: Path) -> None:
    """期望（当前**未满足**）：先把左栏读完，再读右栏 —— 人读顺序。"""
    contents = _contents(two_column_pdf)
    assert contents == EXPECTED_HUMAN_ORDER, f"两栏逐行交错了：{contents}"


# ---------------------------------------------------------------------------
# 诊断：交错是从哪来的
# ---------------------------------------------------------------------------


def test_root_cause_is_pymupdf_sort_true(two_column_pdf: Path) -> None:
    """诊断（不测 app，只测 pymupdf）：`sort=True` 才是交错顺序的成因。

    · 不加 sort：PyMuPDF 给的 block 顺序本来就是**按栏**的（列优先）；
    · 加 sort：按坐标重排 → 左右栏逐行交错。

    而 `app/parse/pdf.py::_raw_blocks` 用的正是 `get_text("dict", sort=True)`。
    留着这条是为了让"改哪一行"有据可查 —— 修阅读顺序时先看这里。
    """
    with pymupdf.open(two_column_pdf) as doc:
        page = doc[0]
        natural = [entry[4].strip() for entry in page.get_text("blocks")]
        assert natural == EXPECTED_HUMAN_ORDER, (
            "pymupdf 的自然 block 顺序变了 —— 这条诊断用例的前提需要重新确认"
        )
        # sort=True 的文本里，同一 y 上的左右栏内容会挨在一起（逐行交错）
        sorted_text = page.get_text("text", sort=True)
    rows = [line for line in sorted_text.splitlines() if line.strip()]
    assert len(rows) == len(LEFT_LINES), f"预期 3 个排版行，实际 {rows!r}"
    assert "L1" in rows[0] and "R1" in rows[0], f"预期左右栏第一行被排到同一行：{rows[0]!r}"
    assert "L2" in rows[1] and "R2" in rows[1], f"预期第二行是左栏/右栏第二行：{rows[1]!r}"
