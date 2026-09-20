"""QA 独立验证 · 场景 17：**真实教材**冒烟（A1-2 / A1-5 / A1-6 / A2-7 / F1.2）。

为什么要有这个文件（而不是只用合成 PDF）
----------------------------------------
其余 QA 用例里的 PDF 都是脚本生成的：一页一两行字、字号统一、没有页眉页码、
没有图表。这类输入验证不了"真实教材"上才会暴露的东西 —— 本文件用一份**真实的
LaTeX 排版教材**（*Computer Networks: A Systems Approach*, Release 6.1，
489 页，文本层 PDF）跑一遍链路，覆盖：

  · A1-2 文本层抽取质量：抽出的块能否搜到教材正文的真实句子；抽出的字符相对
    **正文区**（每页字符**减去**页眉带 / 页脚带）原文文本量的覆盖率（下限 98%、
    上限 105%）；以及**逐字忠实性**（每个块去掉空白后必须是该页原文的连续子串 ——
    这条挡住"错字 / 捏造 / 错位"，"少抽"则由覆盖率与逐页完整性挡）。
  · A1-5 性能：30 页真实排版文本的解析耗时（门限 90 秒）。
  · A1-6 锚点：`to_markdown()` 的块锚点数量/唯一性/顺序，以及页锚点的覆盖范围。
  · A2-7 可复现：同一份材料解析两次，块序列与 Markdown 逐字节相同。
  · F1.2 扫描版判定：真实扫描件样本（无文本层、含整页图）判 `pdf_scan`。
  · 页数上限：489 页原文必须给**中文**报错并提示分批，**不得静默截断**。

素材在仓库**之外**（本文件不复制、不落盘到仓库内）
------------------------------------------------
  · 教材全文：`<repo>/.learnbuddy/materials/ComputerNetworks-SystemsApproach-6e.pdf`
  · 扫描件样本：`.../ComputerNetworks-SystemsApproach-6e-扫描件样本.pdf`
（`.learnbuddy/` 不受版本控制，所以 CI 上没有这两个文件）

因此有两个刻意的设计：
  1. **素材缺失时整文件 skip**（不是 fail）—— 没有素材的机器上不该报红，
     但也不该静默"通过"一个没跑过的验证，所以用 `pytest.skip` 明确说出来；
     可用环境变量 `QA_MATERIALS_DIR` 指向别处的素材目录。
  2. 30 页子集用 `pymupdf` 抽到 `tmp_path_factory` 的**系统临时目录**下，
     用完即弃，绝不写进仓库。超页数那条用例直接对 489 页原文调用，
     因为它在解析**之前**就会报错（只读页数），不会拖慢测试。

真实版式的观察（页眉 / 页码 / 图注 / 目录页）**不作为断言**
--------------------------------------------------------
`test_real_layout_noise_is_reported_not_asserted` 只断言"结构完整性"这类
不该随去噪功能变化的性质，把页眉/页码/图注/目录页的实际表现**打印出来**。
理由：这些现象（尤其是页眉页码噪声）是**下一批**要改的东西，写成断言会变成
"改对了反而报红"的钉子；而它们又必须被如实记录下来，作为下一批的输入。
"""

from __future__ import annotations

import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from app.core.errors import ApiError, ErrorCode
from app.models.ids import block_id
from app.parse import MAX_PAGES, parse_material, to_markdown

# ---------------------------------------------------------------------------
# 素材定位与跳过策略
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
MATERIALS_DIR = Path(os.environ.get("QA_MATERIALS_DIR", _REPO_ROOT / ".learnbuddy" / "materials"))

TEXTBOOK_PDF = MATERIALS_DIR / "ComputerNetworks-SystemsApproach-6e.pdf"
SCAN_SAMPLE_PDF = MATERIALS_DIR / "ComputerNetworks-SystemsApproach-6e-扫描件样本.pdf"

#: 从真实教材里抽出来解析的页数（前 N 页，含封面/目录/正文首章）
SUBSET_PAGES = 30

#: A1-5 的硬门限（秒）—— 与 `test_qa_parse_bounds_perf.py` 同一口径
PERFORMANCE_BUDGET_SEC = 90.0

#: 版心上下带的分界线（LaTeX 教材的页眉 / 页脚位置），**全文件唯一定义**：
#:   · 页首带：文本块 `bbox.top < 60`   —— 书名页眉
#:   · 页脚带：文本块 `bbox.top > 730`  —— 页码 + running head
#: 下面既用它算 A1-2 的**分母扣除项**（`subset_page_noise_chars`），也用它做
#: 版式观察里的 `top_band` / `bottom_band` 统计 —— 两处必须是同一条带，
#: 否则"分母扣掉的"和"报告里数的噪声"就不是同一批字符，口径对不上。
#:
#: ⚠️ 这两个数是**本教材（LaTeX，612×792pt）版式的硬编码前提**，页高 792 时
#: 约合 **0.076 / 0.922**。
#: **换教材版式必须重新实测这两个值**，否则 A1-2 的分母扣除项与版式观察
#: 就不是同一条带（"分母扣掉了页眉页脚、报告里却把正文当噪声数"这种口径错位
#: 不会报错，只会让覆盖率数字悄悄失真）。本批**刻意**不改成页高比例：
#: `test_real_layout_noise_is_reported_not_asserted` 手里只有解析出的块的
#: `bbox[1]`、拿不到页高，改成比例就得给每个块补一次"它属于哪一页、该页多高"
#: 的查找，牵动整条观察链路 —— 换版式时连同本段一起重测即可。
HEADER_BAND_TOP = 60.0
FOOTER_BAND_TOP = 730.0

#: A1-2 验收线（SPEC 原文）：抽出的非空白字符 ≥ **正文区**非空白字符的 98%。
#:
#: 分母口径（M3 修正）：分母 = 该批每页 `get_text()` 的字符数 **减去** 该页
#: 页首带 + 页脚带里的字符数，即"**已剔除页眉页脚带的正文区字符**"。
#: 理由：页眉/页脚（书名、页码、running head）不属于"应当抽出的正文"，
#: 把它们算进分母等于要求解析器"务必把噪声也抽出来"，方向是反的。
#: 因此**下限永远回到 SPEC 的 98%，不因去噪而下调** —— 去噪在分子与分母上是
#: 同向的（分子少了页眉页脚，分母本来就不含页眉页脚），不会把比值压低。
#:
#: 本批**尚未**做页眉页脚去噪，所以分子里仍含这部分字符，而分母已不含 ——
#: **比值略大于 1 属于预期**（实测 59186 / 57502 ≈ 1.029），不是缺陷；
#: 下一批真正落地去噪后，分子回落到正文区字符量，比值自然回到 ≈1.000。
A1_2_MIN_COVERAGE = 0.98
#: 覆盖率上限：两侧都已去掉空白，所以**大于 1** 只可能来自"同一段文字被写进
#: 结果不止一次"（表格合并格被重复填那类缺陷在 PDF 侧的同型）。
#:
#: 上界卡在 **1.05**，只比"本批未去噪"的预期溢出（2.85% 的页眉页脚带）多留
#: 约 2 个百分点的余量。换算成字符：正文区 57502 字符 → 允许抽出 ≤ 60377，
#: 而今天抽出 59186，余量只剩约 1191 字符。也就是说**任何一段像样的正文被
#: 重复写第二次**（单段通常几百到上千字符、整页更是两千字符量级）都会立刻
#: 顶破这条上界；反过来，若把上界放到 1.10，就要写坏两三千字符才报红，
#: 护栏形同虚设。它与 `test_real_subset_has_no_duplicate_block_on_the_same_page`
#: 互补：那条查"完全相同的块"，这条查"总量层面的放大"。
A1_2_MAX_COVERAGE = 1.05

#: 教材正文的真实句子（用于 A1-2 的"搜得到原文"验证）。
#: 选的是正文段落里的话，不是目录行也不是图注 —— 目录/图注的抽取是另一回事。
BODY_SENTENCES = (
    "What most web users are not aware of, however, is that by clicking on just one such URL",
    "A system that is designed to support growth to an arbitrarily large size is said to scale.",
    "the two most common are circuit switched and packet switched",
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_BLOCK_ANCHOR_RE = re.compile(r"<!-- block: (blk_[0-9a-f]{8}_\d{5}) -->")
_PAGE_ANCHOR_RE = re.compile(r"<!-- page: (\d+) -->")
_HEADING_TYPES = {"heading", "paragraph"}

pytestmark = pytest.mark.skipif(
    not (TEXTBOOK_PDF.is_file() and SCAN_SAMPLE_PDF.is_file()),
    reason=(
        "真实教材素材缺失（不受版本控制）。把教材与扫描件样本放到 "
        f"{MATERIALS_DIR} 下，或设置环境变量 QA_MATERIALS_DIR 指向素材目录。"
        f"缺少：{TEXTBOOK_PDF.name} / {SCAN_SAMPLE_PDF.name}"
    ),
)


def _report(line: str) -> None:
    """打印实测数字（跑本文件时加 `-s` 即可看到）。"""
    print(line)


def _nows(text: str) -> str:
    """去掉所有空白 —— 比较字符数/子串时统一口径。"""
    return "".join(text.split())


@pytest.fixture(scope="module")
def subset_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """从 489 页原文里抽出前 `SUBSET_PAGES` 页，存到系统临时目录（不落进仓库）。"""
    target = tmp_path_factory.mktemp("qa_real_material") / f"subset{SUBSET_PAGES}.pdf"
    source = pymupdf.open(TEXTBOOK_PDF)
    try:
        assert source.page_count > SUBSET_PAGES, "原文页数不足，抽页策略需要复核"
        subset = pymupdf.open()
        try:
            subset.insert_pdf(source, from_page=0, to_page=SUBSET_PAGES - 1)
            subset.save(str(target))
        finally:
            subset.close()
    finally:
        source.close()
    return target


@pytest.fixture(scope="module")
def subset_parsed(subset_pdf: Path) -> Any:
    """解析 30 页子集（模块级缓存：同一份材料不重复解析，用例之间共享结果）。"""
    return parse_material(subset_pdf)


@pytest.fixture(scope="module")
def subset_page_text(subset_pdf: Path) -> dict[int, str]:
    """子集每页 `get_text()` 的**去空白**文本，作为 A1-2 的分母与忠实性底本。"""
    doc = pymupdf.open(subset_pdf)
    try:
        return {i + 1: _nows(doc[i].get_text()) for i in range(doc.page_count)}
    finally:
        doc.close()


@pytest.fixture(scope="module")
def subset_page_noise_chars(subset_pdf: Path) -> dict[int, int]:
    """子集每页**页首带 + 页脚带**里的非空白字符数（A1-2 分母的扣除项）。

    口径与 `test_real_layout_noise_is_reported_not_asserted` 里的
    `top_band` / `bottom_band` 完全一致 —— 同一条 `HEADER_BAND_TOP` /
    `FOOTER_BAND_TOP` 分界，只是这里按**页自己的文本块**数**字符**，
    而不是按解析出的块数**块**：覆盖率的分母要的是"应抽出的原文有多少字符"。

    这些字符是**页眉/页脚**（书名、页码、running head），不属于应抽出的正文，
    所以从分母里剔除。注意 `get_text("blocks")` 的文本拼起来与 `get_text()`
    是同一批字符（实测两边都是 59186），因此扣除是干净的，不会把正文误伤。
    """
    doc = pymupdf.open(subset_pdf)
    try:
        noise: dict[int, int] = {}
        for i in range(doc.page_count):
            total = 0
            for block in doc[i].get_text("blocks"):
                # 元组布局：(x0, y0, x1, y1, text, block_no, block_type)
                top = block[1]
                if top < HEADER_BAND_TOP or top > FOOTER_BAND_TOP:
                    total += len(_nows(block[4]))
            noise[i + 1] = total
        return noise
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# 1. 超页数保护：489 页原文必须报中文错误，不得静默截断
# ---------------------------------------------------------------------------


def test_real_489_page_textbook_is_rejected_with_batch_hint() -> None:
    """★ 直接对 489 页真实教材调 `parse_material()` → 抛中文 `ApiError` 提示分批。

    关键词是"**不静默截断**"：静默返回前 100 页会让"这份 489 页的教材怎么只抽出
    了这么点知识点"变成一个查不出来的问题。所以断言的是抛异常，而不是
    "返回 100 页的结果"。
    """
    source = pymupdf.open(TEXTBOOK_PDF)
    real_pages = source.page_count
    source.close()
    assert real_pages == 489, f"素材页数变了（{real_pages}），本用例的前提需要复核"

    started = time.perf_counter()
    with pytest.raises(ApiError) as excinfo:
        parse_material(TEXTBOOK_PDF)
    elapsed = time.perf_counter() - started

    err = excinfo.value
    _report(f"\n[真实素材] 489 页超限报错：{elapsed:.3f}s，message={err.message!r}")
    assert err.code == ErrorCode.INVALID_PARAM
    assert err.status_code == 400
    assert _CJK_RE.search(err.message), "报错文案必须是中文"
    assert str(real_pages) in err.message
    assert str(MAX_PAGES) in err.message
    assert "分批" in err.message
    assert "Traceback" not in err.message
    # 报错应当在读页数阶段就发生（不做全文抽取），否则用户要白等几十秒
    assert elapsed < PERFORMANCE_BUDGET_SEC


def test_real_489_page_textbook_does_not_return_a_truncated_document() -> None:
    """反向断言：超限时**不许**返回一份"看起来成功"的截断结果。"""
    try:
        doc = parse_material(TEXTBOOK_PDF)
    except ApiError:
        return  # 期望路径
    pytest.fail(
        f"489 页教材没有报错却被静默截断成了 {doc.page_count} 页、{len(doc.blocks)} 块"
    )


# ---------------------------------------------------------------------------
# 2. 合法子集可解析
# ---------------------------------------------------------------------------


def test_real_subset_parses_with_correct_page_count_and_page_numbers(
    subset_parsed: Any,
) -> None:
    """★ 30 页真实子集能解析成功，页数正确，且**每个块都有 `page_no`（A1-6）**。"""
    doc = subset_parsed
    _report(
        f"\n[真实素材] 子集解析：{SUBSET_PAGES} 页 → {len(doc.blocks)} 块，"
        f"source_type={doc.source_type}，parse_method={doc.parse_method}"
    )
    assert doc.source_type == "pdf_text"
    assert doc.parse_method == "text_extract"
    assert doc.page_count == SUBSET_PAGES
    assert doc.blocks, "真实文本层教材抽出了 0 个块"
    assert all(b.page_no is not None for b in doc.blocks), "存在没有页码的块（破坏 A1-6）"
    assert {b.page_no for b in doc.blocks} <= set(range(1, SUBSET_PAGES + 1))
    assert all(b.block_type in _HEADING_TYPES for b in doc.blocks)
    assert all(b.content_md.strip() for b in doc.blocks), "存在空白块"


# ---------------------------------------------------------------------------
# 3. 文本层质量（A1-2 的精神）
# ---------------------------------------------------------------------------


def test_real_subset_contains_verbatim_body_sentences(subset_parsed: Any) -> None:
    """★ A1-2：抽出的块里能搜到教材**正文**的真实句子。"""
    doc = subset_parsed
    joined = "\n".join(b.content_md for b in doc.blocks)
    for sentence in BODY_SENTENCES:
        assert sentence in joined, f"教材正文句子没能原样抽出：{sentence!r}"
        hit = next(b for b in doc.blocks if sentence in b.content_md)
        assert hit.block_type == "paragraph"
        assert hit.page_no is not None
        _report(f"[真实素材] 正文命中 p{hit.page_no}：{sentence[:56]!r}…")


def test_real_subset_blocks_are_verbatim_substrings_of_the_source_pages(
    subset_parsed: Any, subset_page_text: dict[int, str]
) -> None:
    """★ A1-2（更硬的一条）：每个块去掉空白后必须是**该页原文的连续子串**。

    比"覆盖率"更能说明问题：覆盖率只数总量，错字、捏造、把两段不同的文字拼在
    一起（错位）都不会改变字符总数。逐字子串检查把这三类问题一次挡住 ——
    「原文抽取准确率 ≥ 98%」的真实含义就在这里。

    **但它看不见"少抽"**：整段、整页没被抽出来时，抽出来的那些块依旧每一块都是
    原文的连续子串，本用例照过。少抽只能由覆盖率下限与逐页完整性来挡。
    两条约束方向正交、缺一不可：
        · 本用例      → 抽出来的**都对**（无错字 / 捏造 / 错位，不受去噪影响）
        · 覆盖率下限  → 该抽的**没少抽**（且分母已剔除页眉页脚带，去噪不会压低它）
        · 覆盖率上限  → 没有**重复写**
    """
    doc = subset_parsed
    violations: list[tuple[int, str, str]] = []
    for block in doc.blocks:
        needle = _nows(block.content_md)
        haystack = subset_page_text.get(block.page_no or 0, "")
        if needle not in haystack:
            violations.append(
                (block.page_no or 0, block.block_type, block.content_md[:120])
            )

    _report(
        f"[真实素材] 逐字忠实性：{len(doc.blocks) - len(violations)}/{len(doc.blocks)} 块"
        f"是原文连续子串（违规 {len(violations)} 块）"
    )
    assert not violations, (
        "以下块的内容不是所在页原文的连续子串（可能是错字 / 捏造 / 跨段错位，"
        "或块跨越了页边界而破坏了 A1-6 的单页归属）："
        f"{violations[:5]}"
    )


def test_real_subset_text_coverage_meets_a1_2(
    subset_parsed: Any,
    subset_page_text: dict[int, str],
    subset_page_noise_chars: dict[int, int],
) -> None:
    """★ A1-2：抽出的字符量相对**正文区**原文文本量的覆盖率必须落在 [98%, 105%]。

    分母口径（本用例的要点）：
        分母 = Σ(每页 `get_text()` 字符数)
             − Σ(每页页首带 + 页脚带的字符数)          ← `subset_page_noise_chars`
             = **已剔除页眉页脚带的正文区字符**（实测 59186 − 1684 = 57502）

    两侧都去掉空白，避免把排版空格算成抽取成果。分母剔除页眉页脚，是因为
    书名/页码/running head 不是"应当抽出的正文"；分子这一批**还没去噪**，
    所以仍含那部分字符，比值会**略大于 1**（≈1.029）——这是预期，不是缺陷，
    下一批去噪落地后会回到 ≈1.000。下限始终是 SPEC 的 98%，不因去噪下调。

    这条与下面的**逐字忠实性**用例分工明确：那条管"抽出来的字对不对"
    （错字 / 捏造 / 错位），这条管"**该抽的有没有少抽**"——少抽不会产生任何
    非子串内容，逐字检查看不见它，所以两条必须同时在。
    """
    doc = subset_parsed
    extracted = sum(len(_nows(b.content_md)) for b in doc.blocks)
    page_total = sum(len(t) for t in subset_page_text.values())
    noise_total = sum(subset_page_noise_chars.get(p, 0) for p in subset_page_text)
    body_total = page_total - noise_total
    coverage = extracted / body_total if body_total else 0.0

    _report(
        f"[真实素材] 文本量：抽出 {extracted} 字符 / 整页 {page_total} 字符"
        f"（扣页眉页脚带 {noise_total} 字符）→ 正文区 {body_total} 字符"
        f" → 覆盖率 {coverage * 100:.2f}%（口径 ["
        f"{A1_2_MIN_COVERAGE:.0%}, {A1_2_MAX_COVERAGE:.0%}]，本批未去噪故略高于 100% 属预期）"
    )
    assert page_total > 0
    assert 0 <= noise_total < page_total, "页眉页脚带扣得不合理（把整页都扣没了）"
    assert body_total > 0
    assert coverage >= A1_2_MIN_COVERAGE, (
        f"正文区覆盖率 {coverage * 100:.2f}% 低于 A1-2 的 {A1_2_MIN_COVERAGE:.0%}"
        f"（正文区 {body_total} 字符只抽出 {extracted}）—— 正文被大面积少抽 / 丢掉"
    )
    assert coverage <= A1_2_MAX_COVERAGE, (
        f"正文区覆盖率 {coverage * 100:.2f}% 超过 {A1_2_MAX_COVERAGE:.0%}"
        f"（正文区 {body_total} 字符却抽出 {extracted}）—— 有内容被重复写"
    )

    # 少抽的**逐页**护栏：只要某页有正文文本，就必须至少抽出一个块。
    # 覆盖率是个比值，整页被丢掉时可以靠别处的重复写掩盖过去；这条不能。
    # （实测第 2 页是完全空白页，`get_text()` 为空，因此它不被要求有块。）
    pages_with_text = {p for p, t in subset_page_text.items() if t}
    pages_with_blocks = {b.page_no for b in doc.blocks if b.page_no is not None}
    dropped = sorted(pages_with_text - pages_with_blocks)
    _report(
        f"[真实素材] 逐页完整性：有正文的页 {len(pages_with_text)} 个，"
        f"其中有块的 {len(pages_with_text & pages_with_blocks)} 个，整页被丢={dropped}"
    )
    assert not dropped, f"这些页有正文却一个块都没抽出（整页少抽）：{dropped}"


def test_real_subset_has_no_duplicate_block_on_the_same_page(subset_parsed: Any) -> None:
    """同一页内不允许出现两块内容完全相同（重复写是 PDF 侧最典型的静默污染）。"""
    doc = subset_parsed
    by_page: dict[int, Counter[str]] = {}
    for block in doc.blocks:
        key = _nows(block.content_md)
        by_page.setdefault(block.page_no or 0, Counter())[key] += 1
    dups = [
        (page_no, text[:60], count)
        for page_no, counter in by_page.items()
        for text, count in counter.items()
        if count > 1
    ]
    assert not dups, f"同页出现重复块：{dups[:5]}"


# ---------------------------------------------------------------------------
# 4. 锚点（A1-6）
# ---------------------------------------------------------------------------


def test_real_subset_block_anchors_match_blocks_exactly(subset_parsed: Any) -> None:
    """★ A1-6：`to_markdown()` 里块锚点数量 == 块数，且 ID 与 `block_id()` 一致有序。"""
    doc = subset_parsed
    mat_id = "mat_0123abcd"
    md = to_markdown(doc, mat_id)
    anchors = _BLOCK_ANCHOR_RE.findall(md)
    expected = [block_id(mat_id, seq) for seq in range(len(doc.blocks))]

    _report(f"[真实素材] 块锚点 {len(anchors)} 个 / 块数 {len(doc.blocks)}，唯一 {len(set(anchors))}")
    assert len(anchors) == len(doc.blocks)
    assert len(set(anchors)) == len(anchors), "块锚点有重复"
    assert anchors == expected, "块锚点顺序与 block_id(seq) 不一致（下游定位会错位）"


def test_real_subset_page_anchors_cover_exactly_the_pages_that_have_blocks(
    subset_parsed: Any,
) -> None:
    """★ A1-6：页锚点**事件式**（`markdown.py` 的稳定契约）——只对"有块的页"发锚点。

    实测这份教材的前 30 页里，**第 2 页一个块都没有**，所以页锚点是 29 个而不是
    30 个。独立核查过第 2 页（`get_text()` 为空、`get_images()` 为空、
    `get_drawings()` 为空、`get_xobjects()` 为空）—— 它是一张**完全空白的页**，
    不是"整页图片"页：没有任何可归属的内容，抽取出 0 块是正确结果。
    这不是缺陷：页锚点的契约（`markdown.py` 模块 docstring）是"页码变化处插一行"，
    没有块的页没有可归属的内容，凭空补一个 `<!-- page: 2 -->` 会让下游按锚点还原
    "这一页有哪些块"时算错。因此这里断言的是"**锚点页集合 == 有块的页集合**"，
    而不是"覆盖 1..page_count" —— 后者在存在空白页的**真实**材料上无法成立，
    强行满足只能靠捏造一个空锚点。
    """
    doc = subset_parsed
    md = to_markdown(doc, "mat_0123abcd")
    pages = [int(p) for p in _PAGE_ANCHOR_RE.findall(md)]
    pages_with_blocks = sorted({b.page_no for b in doc.blocks if b.page_no is not None})
    missing = sorted(set(range(1, doc.page_count + 1)) - set(pages_with_blocks))

    _report(
        f"[真实素材] 页锚点 {len(pages)} 个，覆盖页={sorted(set(pages))}；"
        f"有块的页 {len(pages_with_blocks)}/{doc.page_count}；无块的页={missing}"
    )
    assert pages == sorted(set(pages)), "页锚点必须严格递增且不重复"
    assert pages == pages_with_blocks, (
        f"页锚点集合与有块的页集合不一致：锚点={sorted(set(pages))}，有块的页={pages_with_blocks}"
    )
    assert all(1 <= p <= doc.page_count for p in pages)
    assert 1 in pages, "第一页有块却没有页锚点"
    assert not missing or all(1 <= p <= doc.page_count for p in missing)


# ---------------------------------------------------------------------------
# 5. 性能（A1-5）
# ---------------------------------------------------------------------------


def test_real_subset_parses_within_performance_budget(subset_pdf: Path) -> None:
    """★ A1-5：30 页真实排版文本的解析耗时 < 90 秒（实测数字打印出来）。

    这里**重新解析一次**（不复用模块级 fixture），因为要测的就是这一次调用的墙钟
    耗时；fixture 里那次已经跑完了，不受影响。门限写死 90 秒，不用"当前值 + 余量"——
    后者会把一次性能回归固化成正例。
    """
    started = time.perf_counter()
    doc = parse_material(subset_pdf)
    elapsed = time.perf_counter() - started

    per_page = elapsed / doc.page_count
    _report(
        f"\n[真实素材] 性能实测：{doc.page_count} 页真实教材解析 {elapsed:.3f}s"
        f"（{per_page * 1000:.1f} ms/页，{len(doc.blocks)} 块，门限 {PERFORMANCE_BUDGET_SEC:.0f}s）"
    )
    assert doc.page_count == SUBSET_PAGES
    assert elapsed < PERFORMANCE_BUDGET_SEC, (
        f"30 页真实教材解析耗时 {elapsed:.3f}s，超过 A1-5 的 {PERFORMANCE_BUDGET_SEC:.0f}s 门限"
    )


# ---------------------------------------------------------------------------
# 6. 可复现（A2-7）
# ---------------------------------------------------------------------------


def test_real_subset_parse_is_byte_reproducible(subset_pdf: Path, subset_parsed: Any) -> None:
    """★ A2-7：同一份真实材料解析两次，块序列与 Markdown **逐字节相同**。

    解析结果要进库、要被人工核对、要作为评测基线 —— 不可复现意味着"同一个文件
    今天抽出来的知识点和昨天不一样"，任何审计都无从谈起。这里连同 `bbox` 一起比，
    因为定位高亮依赖它。
    """
    mat_id = "mat_0123abcd"
    again = parse_material(subset_pdf)

    def _fingerprint(doc: Any) -> list[tuple[Any, ...]]:
        return [
            (
                b.block_type,
                b.page_no,
                b.line_start,
                b.line_end,
                b.heading_level,
                b.content_md,
                tuple(b.bbox) if b.bbox is not None else None,
            )
            for b in doc.blocks
        ]

    md_first = to_markdown(subset_parsed, mat_id)
    md_second = to_markdown(again, mat_id)
    same_blocks = _fingerprint(subset_parsed) == _fingerprint(again)
    same_md = md_first == md_second

    _report(
        f"[真实素材] 可复现：块序列逐字段相同={same_blocks}，"
        f"Markdown 逐字节相同={same_md}（{len(md_first)} 字符）"
    )
    assert same_blocks, "两次解析的块序列不一致（含 page_no / 行号 / 层级 / bbox）"
    assert same_md, "两次解析的 Markdown 不是逐字节相同"


# ---------------------------------------------------------------------------
# 7. 扫描件样本（F1.2）
# ---------------------------------------------------------------------------


def test_real_scan_sample_is_classified_as_scan_with_chinese_note() -> None:
    """★ F1.2：真实扫描件样本（无文本层、含整页图）→ `pdf_scan` + 中文存疑说明。

    本批次不做 OCR，所以 `blocks` 必须为空（不能编内容），且 `parse_method`
    必须是 `None`（一行 OCR 都没跑，写 `"ocr"` 就是假账）。
    """
    doc = parse_material(SCAN_SAMPLE_PDF)
    notes = doc.uncertain_notes

    _report(
        f"\n[真实素材] 扫描件样本：source_type={doc.source_type}，page_count={doc.page_count}，"
        f"blocks={len(doc.blocks)}，parse_method={doc.parse_method}"
    )
    assert doc.source_type == "pdf_scan"
    assert doc.blocks == [], "判成扫描版就不许产出任何内容块"
    assert doc.parse_method is None
    assert doc.page_count == 3

    assert len(notes) == 1
    note = notes[0]
    _report(f"[真实素材] 扫描件说明：severity={note.severity} page={note.page}\n  {note.message}")
    assert note.severity == "high"
    assert _CJK_RE.search(note.message), "存疑说明必须是中文"
    assert "扫描" in note.message
    assert "OCR" in note.message or "ocr" in note.message


def test_real_textbook_is_not_misclassified_as_scan(subset_parsed: Any) -> None:
    """反向陷阱：真实文本层教材**绝不能**被判成扫描版（否则整份材料零产物）。"""
    assert subset_parsed.source_type == "pdf_text"
    assert subset_parsed.blocks


# ---------------------------------------------------------------------------
# 8. 真实版式的观察（**报告，不作断言**）
# ---------------------------------------------------------------------------


def test_real_layout_noise_is_reported_not_asserted(
    subset_parsed: Any, subset_page_text: dict[int, str]
) -> None:
    """★ 真实版式观察：页眉 / 页码 / 图注 / 目录页在块表里的实际表现。

    这里**刻意只打印、不针对噪声下断言**：页眉页脚去噪是下一批的任务，
    把"每页多出 2 个噪声块"写成断言，等于让下一批改对之后反而报红。
    断言只保留"不该随去噪变化"的结构完整性。

    观测口径（LaTeX 教材的版心，与 A1-2 分母扣除项**同一条带**）：
      · 页首带 `bbox.top < HEADER_BAND_TOP` (60)  —— 书名页眉
      · 页脚带 `bbox.top > FOOTER_BAND_TOP` (730) —— 页码 + running head
    """
    doc = subset_parsed
    total = len(doc.blocks)

    top_band = [b for b in doc.blocks if b.bbox and b.bbox[1] < HEADER_BAND_TOP]
    bottom_band = [b for b in doc.blocks if b.bbox and b.bbox[1] > FOOTER_BAND_TOP]
    pure_digits = [b for b in doc.blocks if re.fullmatch(r"\d{1,3}", b.content_md.strip())]
    captions = [
        b for b in doc.blocks if re.match(r"(?i)^(figure|table)\s*\d", b.content_md.strip())
    ]
    # 本教材（LaTeX）目录行的真实版式是「**行首**页码 + 标题 + 前导点」：
    #     '5 1.1 Applications . . . . . . . .'
    # 所以**不能**用"行尾跟页码"去识别目录行 —— 那会数出 0 行，把"目录行其实已被
    # 拼成整行"误报成"目录被打散成碎块"。这里按前导点（`. . . .`，点之间带空格）
    # 识别，并单独统计"页码在行首"的比例。
    toc_leadered = [b for b in doc.blocks if re.search(r"\.(?:\s*\.){4,}", b.content_md)]
    toc_head_numbered = [
        b for b in toc_leadered if re.match(r"^\d{1,3}\s+\S", b.content_md.strip())
    ]
    toc_pages = {
        p for p in {b.page_no for b in doc.blocks} if any(
            "TABLE OF CONTENTS" in b.content_md for b in doc.blocks if b.page_no == p
        )
    }
    repeated = Counter(b.content_md.strip() for b in doc.blocks if len(b.content_md.strip()) <= 80)

    _report("\n===== 真实版式观察（30 页子集，非断言）=====")
    _report(f"总块={total}；块类型分布={dict(Counter(b.block_type for b in doc.blocks))}")
    lengths = sorted(len(b.content_md) for b in doc.blocks)
    _report(
        f"块长度：min={lengths[0]} p50={lengths[len(lengths) // 2]} "
        f"p90={lengths[int(len(lengths) * 0.9)]} max={lengths[-1]}"
    )

    _report(f"\n[页眉] 页首带(top<60) 块数={len(top_band)}（占 {len(top_band) / total:.1%}）")
    for text, count in Counter(b.content_md.strip() for b in top_band).most_common(3):
        _report(f"   x{count} {text[:70]!r}")

    _report(f"\n[页码] 页脚带(top>730) 块数={len(bottom_band)}（占 {len(bottom_band) / total:.1%}）")
    digit_in_bottom = [
        b for b in bottom_band if re.fullmatch(r"\d{1,3}", b.content_md.strip())
    ]
    _report(
        f"   纯数字块：全文档 {len(pure_digits)} 个（页脚带 {len(digit_in_bottom)} 个，"
        f"其余在目录页版心内）；全部被判 heading="
        f"{all(b.block_type == 'heading' for b in pure_digits)}"
        f"，heading_level 分布={dict(Counter(b.heading_level for b in pure_digits))}"
    )
    _report(f"   页码样例={[(b.page_no, b.content_md.strip(), b.block_type) for b in pure_digits[:8]]}")
    footer_text = Counter(
        b.content_md.strip()
        for b in bottom_band
        if not re.fullmatch(r"\d{1,3}", b.content_md.strip())
    )
    _report(f"   页脚 running head 文本={footer_text.most_common(4)}")

    _report(f"\n[图注] 以 Figure/Table 开头的块={len(captions)}，类型={dict(Counter(b.block_type for b in captions))}")
    _report(f"   出现 image_caption 类型的块={sum(1 for b in doc.blocks if b.block_type == 'image_caption')}")
    # 图注的风险是"与正文段粘连"：图注通常是一两行短句，若某个 Figure 开头的块
    # 长出几百字符，多半是它把紧随其后的正文段一起吞进了同一块。
    long_captions = [b for b in captions if len(b.content_md) > 200]
    _report(
        f"   其中长度 >200 字符的（疑似图注与正文段粘连）={len(long_captions)}"
        f"{[ (b.page_no, len(b.content_md)) for b in long_captions ]}"
    )
    for b in captions[:4]:
        _report(f"   p{b.page_no} {b.block_type} len={len(b.content_md)} {b.content_md[:90]!r}")

    _report(f"\n[目录页] 含 'TABLE OF CONTENTS' 的页={sorted(toc_pages)}")
    for pno in sorted(toc_pages):
        page_blocks = [b for b in doc.blocks if b.page_no == pno]
        _report(f"   p{pno}: {len(page_blocks)} 块，合计 {sum(len(b.content_md) for b in page_blocks)} 字符")
    _report(f"   含前导点（'. . . .' 样式）的目录行块={len(toc_leadered)}，"
            f"其中页码在**行首**的={len(toc_head_numbered)}")
    _report(f"   目录行样例={[b.content_md.strip()[:60] for b in toc_leadered[:3]]}")
    _report("   → 结论：目录行**已被拼成整行**（页码在行首是这本 LaTeX 教材的版式，"
            "不是碎块）；碎块问题只体现在页脚 running head / 页码被拆成独立块。")

    _report(f"\n[跨页重复的短文本] {repeated.most_common(6)}")

    # ---- 只断言"结构完整性"（不随去噪变化）----
    assert all(b.bbox is not None for b in doc.blocks), "真实 PDF 的块必须带 bbox"
    assert all(
        b.line_start is not None and b.line_end is not None and b.line_start <= b.line_end
        for b in doc.blocks
    ), "行号缺失或倒置"
    assert all(b.page_no in subset_page_text for b in doc.blocks)
