"""`_section_ranges` 的区间推导测试（归属：P2）。

## 为什么单独给这个函数写测试

它是**结构线索抽取里最容易静默出错**的一步。

`#2` 的评审里我追问过队友：`ParsedSection` 的块区间是左闭右闭还是半开？
差一个块会怎样？——答案是：**不会报错，只会让知识点悄悄挂到相邻的节上**，
而"三级结构完整率 100%"这个硬指标**照样通过**，内容却是错的。

`ParsedSection.__post_init__` 用构造期不变量挡住了那一类问题。
**但那个不变量没有跟着落库** —— `sections` 表里只有 `source_block_id`（标题块），
没有 start/end。所以在读侧要**再推一次**，而推导逻辑没有任何保护。

**这个文件就是那个保护。** 它测的不是"能不能跑"，是边界对不对：

| 场景 | 期望 |
|---|---|
| 两个节 | 前一节到"下一节标题块 - 1"为止（**不吞掉下一节的标题**） |
| 最后一个节 | 一直延伸到最后一个块 |
| 只有一个节 | 从它的标题块覆盖到文件末尾 |
| 标题块缺失（`source_block_id` 为空） | **退化但不崩**（start=0），且仍不重叠 |

**"不吞掉下一节的标题"是这里最关键的一条** ——
它错了不会报错，只会让下一节的标题块被算进上一节，
于是那一节少了一个块、上一节多了一个块。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extract.structural import _section_ranges  # noqa: E402
from app.models import MaterialBlock, Section  # noqa: E402


def _block(seq: int, btype: str = "paragraph") -> MaterialBlock:
    return MaterialBlock(
        id=f"blk_test_{seq:05d}",
        material_id="mat_test",
        seq=seq,
        page_no=1,
        line_start=seq + 1,
        line_end=seq + 1,
        block_type=btype,
        heading_level=1 if btype == "heading" else None,
        content_md=f"块 {seq}",
        image_path=None,
        ocr_confidence=None,
    )


def _section(seq: int, heading_block_id: str | None) -> Section:
    return Section(
        id=f"sec_test_{seq:03d}",
        material_id="mat_test",
        chapter_id="ch_test_000",
        number=str(seq),
        title=f"第 {seq} 节",
        seq=seq,
        source_block_id=heading_block_id,
    )


def test_two_sections_do_not_swallow_next_heading() -> None:
    """★ 前一节**不能吞掉**下一节的标题块 —— 这是本文件最要紧的一条。

    块布局：
        0 标题A   1 正文A   2 标题B   3 正文B

    期望：
        节A -> [0, 1]（**到 2 之前为止**）
        节B -> [2, 3]

    如果这里错了（比如节A拿到 [0,2]），节A会多一个块、节B会少一个块 ——
    **而不会有任何报错。**
    """
    blocks = [
        _block(0, "heading"),
        _block(1),
        _block(2, "heading"),
        _block(3),
    ]
    sections = [_section(0, "blk_test_00000"), _section(1, "blk_test_00002")]

    got = [(sec.seq, lo, hi) for sec, lo, hi in _section_ranges(sections, blocks)]

    assert got == [(0, 0, 1), (1, 2, 3)], f"区间推导错了：{got}"


def test_last_section_extends_to_end_of_document() -> None:
    """最后一个节一直延伸到最后一个块 —— 否则尾部内容会没有归属。"""
    blocks = [_block(0, "heading"), _block(1), _block(2), _block(3), _block(4)]
    sections = [_section(0, "blk_test_00000")]

    got = [(sec.seq, lo, hi) for sec, lo, hi in _section_ranges(sections, blocks)]

    assert got == [(0, 0, 4)], f"末节没有延伸到文件末尾：{got}"


def test_single_section_covers_whole_document() -> None:
    """只有一个节时，它覆盖整份材料（含标题块自身）。"""
    blocks = [_block(0, "heading"), _block(1)]
    sections = [_section(0, "blk_test_00000")]

    (_, lo, hi), = _section_ranges(sections, blocks)
    assert (lo, hi) == (0, 1)


def test_missing_heading_block_does_not_crash_and_does_not_overlap() -> None:
    """标题块缺失时：**退化但不崩**，且相邻节仍不重叠。

    这是真实会发生的情况：`source_block_id` 可能为空（占位节、或解析没给出标题块）。
    这里只要求两件事：**不抛异常**、**不重叠**（lo <= hi 且前一节的 hi < 后一节的 lo）。
    """
    blocks = [_block(0), _block(1), _block(2)]
    sections = [_section(0, None), _section(1, "blk_test_00002")]

    got = _section_ranges(sections, blocks)

    assert len(got) == 2
    for _, lo, hi in got:
        assert lo <= hi, f"区间为空（lo={lo} > hi={hi}）—— 下游切片会拿到 []"

    (_, lo_a, hi_a), (_, lo_b, _) = got
    assert hi_a < lo_b or lo_a == lo_b, f"相邻节重叠了：A=[{lo_a},{hi_a}] B 起于 {lo_b}"
