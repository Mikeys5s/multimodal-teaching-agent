"""解析产物的数据结构（归属：P1）。

这一层**与存储完全无关**：解析器只产出 `ParsedDocument`，由 `persist.py`
决定怎么落 `material_blocks` 表。好处是 PDF / DOCX 两个解析器都不必知道
SQLAlchemy 的存在，绝大多数测试可以纯内存跑。

两条纪律
--------
1. **`seq` 只有一个来源**：`ParsedDocument.numbered()`。拼 Markdown 锚点与
   落库都走它，保证"锚点里的 seq" 与 "库里的 seq" 永远一致（A1-6 可定位）。
2. **空白块只在一个地方过滤**：`ParsedDocument.__post_init__`。如果落库时
   再过滤一次，锚点序号与库里的序号就会错位 —— 这种错位不会报错，只会让
   溯源指向错误的行，属于最坏的一类 bug。

异常约定
--------
· 用户输入导致的问题（加密、损坏、超页数）→ `ApiError` + 中文文案，由解析器抛。
· 本模块的类型/字段契约被违反（编程错误）→ `ValueError`，不做兜底。
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.models._common import BLOCK_TYPES, PARSE_METHODS, SOURCE_TYPES

BBox = tuple[float, float, float, float]

HEADING_LEVEL_MIN = 1
HEADING_LEVEL_MAX = 6

# uncertain_notes 的取值集合，与 app/schemas/material.py::UncertainNoteOut 逐字一致。
# 在这里复述一遍是有意的：解析层不该为了一个字符串常量去 import P2 的 schema 层
# （那会把 P1 的解析器和对外契约耦合死），但值域必须对齐，否则前端角标会认不出来。
UNCERTAIN_KINDS: tuple[str, ...] = (
    "low_confidence_ocr",
    "missing_field",
    "ambiguous_structure",
    "other",
)
UNCERTAIN_SEVERITIES: tuple[str, ...] = ("high", "medium", "low")


# ---------------------------------------------------------------------------
# 章节号识别（PDF / DOCX / sections.py 共用）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeadingNumber:
    """从一行文本里拆出来的章节号。

    `number` 保留材料原貌（`3.1`、`第1章`、`一、`），不做归一化 ——
    规格要求"章节号与标题保持材料原貌"（docs/extraction-channel.md §2 步骤 2）。
    """

    number: str
    title: str
    depth: int


# `3`、`3.1`、`3.1.2`；后面必须跟空白/顿号/点号/右括号，避免把 `2020年` 当成编号
_NUM_RE = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){0,5})(?=[\s、.．:：）)]|$)[\s、.．:：）.．]*\s*(.*)$"
)
# `第1章` / `第三章`
_CN_CHAPTER_RE = re.compile(r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*章)\s*[:：.、]?\s*(.*)$")
# `第1节` / `第三节`
_CN_SECTION_RE = re.compile(r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*节)\s*[:：.、]?\s*(.*)$")
# `一、` —— 中文教材里章 → 节 → 一、 三级常见
_CN_ORDINAL_RE = re.compile(r"^\s*([一二三四五六七八九十]+)\s*[、.．]\s*(.*)$")
# `Chapter 1. Foundation` / `Chapter 3: Routing`
#   · 只认**带编号分隔符**（`.`/`:`/`：`/`、`）的写法 —— 与图注识别同一套取舍：
#     "以 Chapter 开头"太弱，正文里 `Chapter 1 describes the ...` 是完整句子
#     （真实教材的正文里就有），只看前缀会把它判成标题并把一段正文切碎。
#     分隔符是**必需**信号，没有就返回 None（宁可漏判，不误判）。
#   · 编号原貌保留为 `Chapter 1`，标题取分隔符之后的部分。
_EN_CHAPTER_RE = re.compile(
    r"^\s*((?:Chapter|CHAPTER|chapter)\s*\d{1,3})\s*[.．:：、]\s+(?=\S)(.+)$"
)

# 各形式对应的层级。中文顿号序号在教材里普遍是第三级，故记 3。
_CN_ORDINAL_DEPTH = 3


def split_heading_number(text: str) -> HeadingNumber | None:
    """把 `3.1 Routing basics` 拆成 (`3.1`, `Routing basics`, 2)。

    拆不出来返回 None —— 不猜、不补默认值。调用方据此决定"这一块是不是标题"。
    """
    line = text.strip()
    if not line:
        return None

    m = _CN_CHAPTER_RE.match(line)
    if m:
        return HeadingNumber(number=m.group(1), title=m.group(2).strip(), depth=1)

    m = _CN_SECTION_RE.match(line)
    if m:
        return HeadingNumber(number=m.group(1), title=m.group(2).strip(), depth=2)

    m = _CN_ORDINAL_RE.match(line)
    if m:
        return HeadingNumber(number=m.group(1), title=m.group(2).strip(), depth=_CN_ORDINAL_DEPTH)

    # `Chapter 1. Foundation` —— 英文教材的章标题。放在中文规则之后、通用数字规则
    # 之前：它一定是章级（depth=1），而 `_NUM_RE` 只认"行首就是数字"，认不出它。
    m = _EN_CHAPTER_RE.match(line)
    if m:
        return HeadingNumber(number=m.group(1), title=m.group(2).strip(), depth=1)

    m = _NUM_RE.match(line)
    if m:
        number, title = m.group(1), m.group(2).strip()
        return HeadingNumber(number=number, title=title, depth=min(number.count(".") + 1, 6))

    return None


# ---------------------------------------------------------------------------
# 块与文档
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedBlock:
    """一个待落库的块。字段与 `material_blocks` 一一对应，但**不含 id/material_id/seq**。

    为什么不存 id：id 依赖 `mat_<hash8>`，而 hash 来自文件内容，属于"落库时才
    知道的上下文"。解析器只管产出与位置无关的内容，`persist.py` 再把它钉到
    具体的材料上 —— 这样同一份内容换个材料 ID 也能复用（重新上传同一文件走
    materials 的 file_hash 去重，本来就会命中同一个 mat_id）。

    `content_md` 的约定：
      · heading 块存**纯标题文本**，不带 `#`。层级由 `heading_level` 表达，
        让 `to_markdown` 统一渲染 —— 若在 content 里也写一遍 `#`，两处就可能
        不一致（DB 有 CHECK 约束 level，content 里的 `#` 没有）。
      · table 块存完整的 Markdown 表格。
      · 其余块存纯文本。
    """

    block_type: str
    content_md: str
    page_no: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    heading_level: int | None = None
    bbox: BBox | None = None
    image_path: str | None = None
    #: OCR 置信度（0–1）。只有走 OCR 的块（`parse_method="ocr"`）才有值，
    #: 其余一律 None —— 文本层 PDF / DOCX 没跑过 OCR，填个数字就是假账。
    ocr_confidence: float | None = None

    def __post_init__(self) -> None:
        if self.block_type not in BLOCK_TYPES:
            raise ValueError(
                f"未知的 block_type：{self.block_type!r}；"
                f"合法取值见 app.models._common.BLOCK_TYPES → {BLOCK_TYPES}"
            )
        if self.heading_level is not None and not (
            HEADING_LEVEL_MIN <= self.heading_level <= HEADING_LEVEL_MAX
        ):
            raise ValueError(
                f"heading_level 必须在 {HEADING_LEVEL_MIN}–{HEADING_LEVEL_MAX}，"
                f"收到 {self.heading_level}"
            )
        if self.block_type == "heading" and self.heading_level is None:
            raise ValueError("heading 块必须给出 heading_level（1–6）")
        if self.block_type != "heading" and self.heading_level is not None:
            # DB 侧没有这条 CHECK（只查了取值范围），但"非 heading 却有 level"
            # 会让下游按 level 建骨架时凭空多出一节。在这里就掐掉。
            raise ValueError(f"只有 heading 块能有 heading_level，{self.block_type} 块不该有")
        if self.page_no is not None and self.page_no < 1:
            raise ValueError(f"page_no 是 1-based，收到 {self.page_no}")
        if self.line_start is not None and self.line_start < 1:
            raise ValueError(f"line_start 是页内 1-based，收到 {self.line_start}")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError(f"line_end({self.line_end}) 不能小于 line_start({self.line_start})")
        if self.bbox is not None:
            if len(self.bbox) != 4:
                raise ValueError(f"bbox 必须是 [x1,y1,x2,y2]，收到 {self.bbox!r}")
            # 统一保留 2 位小数：让"同输入可复现"（A2-7）在浮点上也稳定，
            # 顺便让 bbox 的 JSON 串短一点。
            object.__setattr__(self, "bbox", tuple(round(float(v), 2) for v in self.bbox))
        if self.ocr_confidence is not None and not 0.0 <= self.ocr_confidence <= 1.0:
            # DB 侧只约束了"非空时是浮点"，范围是应用层的责任：置信度写成 95（而不是 0.95）
            # 会让前端的角标阈值全线失灵，而且不报错。
            raise ValueError(f"ocr_confidence 必须在 0–1，收到 {self.ocr_confidence}")

    @property
    def is_heading(self) -> bool:
        return self.block_type == "heading"

    @property
    def is_blank(self) -> bool:
        return not self.content_md.strip()


@dataclass(frozen=True)
class UncertainNote:
    """存疑处（`materials.uncertain_notes` 的元素）。

    "宁缺毋错"：解析拿不准的地方主动标出来，不装完美。
    解析阶段还不知道 block_id（要先落库才有），所以这里的 `block_id` 留空，
    由上层在落库后按需补充。
    """

    kind: str
    message: str
    severity: str = "medium"
    page: int | None = None
    block_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in UNCERTAIN_KINDS:
            raise ValueError(f"未知的存疑类型：{self.kind!r}；合法取值 {UNCERTAIN_KINDS}")
        if self.severity not in UNCERTAIN_SEVERITIES:
            raise ValueError(f"未知的严重度：{self.severity!r}；合法取值 {UNCERTAIN_SEVERITIES}")
        if not self.message.strip():
            raise ValueError("存疑处的 message 不能为空 —— 空说明等于没标，还会让前端显示空卡片")

    def to_dict(self) -> dict[str, Any]:
        """转成 `uncertain_notes` 的 JSON 元素结构（键名与 UncNoteOut 对齐）。"""
        return {
            "kind": self.kind,
            "page": self.page,
            "block_id": self.block_id,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ParsedDocument:
    """一份材料的解析产物。

    `blocks` 的顺序**就是**文档顺序，`seq` 由 `numbered()` 按这个顺序生成。
    `page_count` / `char_count` 供 P2 回填 materials 表用。
    """

    source_type: str
    blocks: list[ParsedBlock] = field(default_factory=list)
    page_count: int | None = None
    parse_method: str | None = "text_extract"
    uncertain_notes: list[UncertainNote] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(
                f"未知的 source_type：{self.source_type!r}；"
                f"合法取值见 app.models._common.SOURCE_TYPES → {SOURCE_TYPES}"
            )
        if self.parse_method is not None and self.parse_method not in PARSE_METHODS:
            raise ValueError(
                f"parse_method 必须是枚举值，收到 {self.parse_method!r}；合法取值 {PARSE_METHODS}"
            )
        if self.page_count is not None and self.page_count < 0:
            raise ValueError(f"page_count 不能为负：{self.page_count}")
        # ★ 空白块的唯一过滤点（见模块 docstring 第 2 条纪律）
        self.blocks = [b for b in self.blocks if not b.is_blank]

    # ---- 派生属性 ----

    @property
    def char_count(self) -> int:
        """正文字符数（不含空白），用于 materials.char_count 与质量自评。"""
        return sum(len(b.content_md) for b in self.blocks)

    @property
    def headings(self) -> list[ParsedBlock]:
        return [b for b in self.blocks if b.is_heading]

    def numbered(self) -> Iterator[tuple[int, ParsedBlock]]:
        """产出 `(seq, block)`，seq 从 0 开始全局连续。

        **这是 seq 的唯一来源**：落库（`persist.persist_blocks`）与拼锚点
        （`markdown.to_markdown`）都调它，两边不可能对不上。
        """
        yield from enumerate(self.blocks)


def as_blocks(doc: ParsedDocument | Sequence[ParsedBlock]) -> list[ParsedBlock]:
    """让接受 `ParsedDocument | Sequence[ParsedBlock]` 的函数少写一份分支。"""
    return doc.blocks if isinstance(doc, ParsedDocument) else list(doc)
