"""结构线索抽取（归属：P2）—— 从"已解析的块与章节"里提出知识点与依赖边。

## 为什么是"结构线索"而不是"语义线索"

SPEC §1.5 的双通道设计里，依赖关系有两个来源：
**结构线索**（章节层级、出现顺序、显式引用）与**语义线索**（需要模型判断语义依赖）。

本模块只做**结构线索**，理由是：

1. **它是确定性的。** 同一份材料跑两次得到完全相同的结果 —— 可复现、可回归、可解释。
   这也正是我们的答辩话术：**「关键路径放在确定性算法上，LLM 只做增强」**。
2. **它不依赖任何模型。** 赛事不允许运行期调外部大模型，而结构线索只需要块与章节 ——
   那些已经在库里了。
3. **它的产出物是"候选"。** 结构线索抽出来的东西**一律 `needs_review=1`** ——
   它负责"把料备齐"，判断留给人工校验工作台。
   **「AI 干粗活 + 人做裁决」**，这里干的就是粗活。

**所以本模块的目标不是"抽得准"，是"抽得全、且每个都说得出来源与理由"。**
抽错是允许的（有 `needs_review` 兜着），**抽不出任何东西才是问题** ——
那意味着整条链路虽然通了，却没有内容可展示。

## 三条硬约束（都对应验收指标）

- **`source_quote` 必须有**（A2-3 溯源覆盖率 100%）→ 每个知识点都带原文片段
- **`reason` 必须有**（B1-5 边理由完备率 100%）→ 每条边都能说出"为什么"
- **写完必须过 DAG 环校验**（B1-2 环数 0）→ 有环就剪最弱的边并留痕

## 已知不足（诚实记账）

- **抽出来的 `name` 会偏长、偏口语** —— 结构线索没有能力把"这个知识点叫什么"提炼好。
  这是语义线索该干的活，本模块只保证"有候选、有来源"。
- **边只用了"同节顺序"与"跨节衔接"两种模式**，没有做显式引用识别（"见 x.y"）。
  那块需要更强的模式库，留到有真实教材之后再补。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import KnowledgePoint, KpPrerequisite, MaterialBlock, Section, utc_now_iso
from app.models.ids import knowledge_point_id

#: 定义句式的模式。命中后**主语**作为知识点候选。
#:
#: 中英文都收 —— 目标学科是计算机网络，教材英文、讲义中文，两种都会遇到。
_DEFINITION_PATTERNS = (
    re.compile(r"^\s*(?:\d+(?:\.\d+)*\s*)?([^\s，。；]{2,24}?)\s*(?:是指|指的是|称为|叫做|定义为|是一种)\s*(.{4,})"),
    re.compile(r"^\s*(?:\d+(?:\.\d+)*\s*)?([A-Za-z][A-Za-z0-9 \-]{2,40}?)\s+(?:is|are|refers to)\s+(?:a|an|the)?\s*(.{4,})"),
)

#: 知识点名的最长长度（超出就截断）。太长会影响界面与检索。
_MAX_NAME = 30

#: 结构线索抽出来的知识点一律标 needs_review —— 见模块 docstring。
_NEEDS_REVIEW = 1

#: 难点启发式用到的词。命中这些词的内容，难度给高一些。
_HARD_HINTS = ("证明", "推导", "算法", "复杂度", "拥塞", "握手", "窗口", "收敛", "compute", "prove")


#: 明显不是知识点名的模式（**只去明显垃圾**，剩下的交人工 —— 美佳拍板）。
#:
#: 这些是真实教材里抽出来的垃圾样本（今早那次抽取泄漏的）：
#:
#:     CHAPTER   FIVE   END-TO-END PROTOCOLS   Victory   —Winston Churchill
#:
#: 分类：
#: ① 全大写短词（页眉/章名残留）—— "CHAPTER"、"FIVE"
#: ② 署名/引语（`—Winston Churchill`、`(Smith, 2019)`）
#: ③ 纯符号/纯数字
#: ④ 过于通用的词（"Introduction" 这类单靠它说明不了什么）
#:
#: ⚠️ **不做语义判断** —— 那是语义线索的活。
#: 这里只做"一眼不像知识点名"的过滤，**宁可放过，不可误杀**：
#: 误杀一个真知识点比留一个垃圾名更糟（前者看不见，后者看得见）。
_JUNK_PATTERNS = (
    re.compile(r"^[—\-–]"),                      # 破折号开头 = 引语署名
    re.compile(r"^\([^)]{0,40}\)$"),            # 整条就是一个括号
    re.compile(r"^[\W_]+$"),                     # 全是符号
    re.compile(r"^\d+$"),                        # 纯数字
)

#: CJK（中日韩）字符 —— 用来区分「纯英文全大写」和「中英混合」。
#:
#: ⚠️ 这个常量是**为了修一个真实误杀**才加的：
#:    `"TCP 拥塞控制"` 曾被判成"全大写短词"丢掉（见 `_is_junk_name`）。
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


#: 全大写且很短的词 —— 页眉/章名残留（`CHAPTER` `FIVE` `TCP/IP` 这种除外）
#: 长度阈值 12：`TCP/IP`(6) 会被放过，`END-TO-END PROTOCOLS`(20) 会被拦
_JUNK_ALLCAPS_MAX = 12


def _is_junk_name(name: str) -> bool:
    """这个候选名是不是"一眼不像知识点"的垃圾。"""
    n = (name or "").strip()
    if len(n) < 4:
        return True
    for pat in _JUNK_PATTERNS:
        if pat.match(n):
            return True
    # 全大写短词（页眉/章名残留）。
    #
    # ⚠️ **必须同时要求"没有 CJK 字符"** —— 第一版我只写了 `n.isupper()`，
    #    结果 **`"TCP 拥塞控制"` 被判成垃圾丢掉了**：
    #    Python 的 `str.isupper()` 只检查「有大小写的字符」，
    #    中文无大小写，于是唯一的 cased 字符 `TCP` 全大写 → 返回 True。
    #
    #    **中英混合的短名会被整类误杀** —— 而我们的目标学科是计算机网络，
    #    教材英文、讲义中文，**这种名字才是常态**。
    if (
        n.isupper()
        and len(n) <= _JUNK_ALLCAPS_MAX
        and not _CJK_RE.search(n)
        and "/" not in n
        and not any(c.isdigit() for c in n)
    ):
        return True
    return False


def _clean(text: str) -> str:
    """去 markdown 标记与多余空白，用于做知识点名。"""
    t = re.sub(r"[`*_#>\[\]()]", "", text or "")
    return re.sub(r"\s+", " ", t).strip()


def _name_from_block(content: str, is_heading: bool = False) -> str | None:
    """从一段文本里推出"这个知识点叫什么"。抽不出来返回 None。

    ## 两类来源，可信度不同（2026-09-20 方案 B 后明确）

    **① `heading` —— 标题就是名字。**
    章/节标题本来就是知识点名（`3.5 Congestion Control`、`CONGESTION CONTROL`）。
    ⚠️ 但仍要过 `_is_junk_name`：**引语署名经常被解析器识别成 heading**
    （`—William Shakespeare` 就是这么进来的）。

    **② `paragraph` —— 只认定义句式。**
    一段话如果不是标题、又没有「X is a ...」/「X 是指 ...」，那它
    **不是知识点**，只是解释知识点的一段正文 —— 那段正文会通过
    `summary_md` / `evidence_quote` 挂在**真正的**知识点下面。

    ⚠️ **主语直接采信，不过 `_is_junk_name`。**
    一个短语能站在「X is a ...」的主语位置，它**已经是定义句的主语了**，
    比任何启发式都可信。上一版我在这里过滤，把 `TCP` 杀掉了
    （`len(n) < 4`）—— 而 `TCP` 恰恰是这份教材里最该留下的名字之一。
    """
    first_line = (content or "").strip().splitlines()[0] if content else ""
    if not first_line:
        return None

    if is_heading:
        head = _clean(first_line)
        if 4 <= len(head) <= _MAX_NAME * 2 and not _is_junk_name(head):
            return head[:_MAX_NAME]
        return None

    for pat in _DEFINITION_PATTERNS:
        m = pat.match(first_line)
        if m:
            # ★ 不过滤 —— 见上面 docstring 的理由
            name = _clean(m.group(1))
            if 2 <= len(name) <= _MAX_NAME * 2:
                return name[:_MAX_NAME]

    # ★ **不再退回"第一句话的前若干字"。**（2026-09-20 改，方案 B）
    #
    # 原注释写的是「**宁可给个粗糙的名字，也不丢一个候选**」——
    # 那个取舍在**手上没有真实教材**时是对的：那时最怕"抽不出东西"。
    #
    # **但在有真实教材之后反了。** 实测：一份教材 1000 个段落 →
    # **1000 个"知识点"**，而段落首句本来就不是知识点名：
    #
    #     The hand that hath made you fa      ← 引语
    #     By now we have seen enough lay      ← 句子片段
    #     • Guarantees message delivery       ← 列表项
    #
    # **它把"段落"变成了"知识点"，噪声淹没信号。**
    # 而且名字清洗只能治标：拦掉 `CHAPTER`，还会有下一批。
    #
    # 现在的口径：**heading（章/节标题）+ 定义句** 才算知识点候选。
    # 一段话如果既不是标题、又没有定义句式，它**不是知识点**，
    # 只是解释知识点的一段正文 —— 那段正文会通过 `summary_md` /
    # `evidence_quote` 挂在真正的知识点下面。
    return None


def _difficulty_of(content: str) -> int:
    """结构线索能给出的难度只是一个**启发式**（1–5）。

    真难度要人判 —— 所以这里只做"长/含难词就给高一点"，
    并且**在 `difficulty_reason` 里写明这是启发式**，不假装精确。
    """
    n = len(content or "")
    base = 2 if n < 60 else 3 if n < 200 else 4
    if any(h in (content or "") for h in _HARD_HINTS):
        base = min(5, base + 1)
    return base


def _kp_type_of(content: str) -> str:
    """按内容里的关键词猜一个类型。猜错没关系（要人工校验）。"""
    c = content or ""
    if any(w in c for w in ("算法", "方法", "步骤", "algorithm", "procedure")):
        return "method"
    if any(w in c for w in ("定理", "定律", "theorem", "law")):
        return "theorem"
    if any(w in c for w in ("协议", "机制", "机制")):
        return "concept"
    return "concept"


def _section_ranges(
    sections: list[Section], blocks: list[MaterialBlock]
) -> list[tuple[Section, int, int]]:
    """算出每个节覆盖的块区间 `[start_seq, end_seq]`（**闭区间**）。

    ⚠️ 区间是**推导出来的**，不是存下来的 —— `sections` 表里只有 `source_block_id`
    （那个节的标题块），没有 start/end。所以按"本节的标题块 seq → 下一节的标题块 seq - 1"推。

    **为什么值得写在这里**：这个推导一旦差了"一个块"，知识点就会挂到相邻的节上，
    而**它不会报错** —— 只会让"三级结构完整率 100%"这个指标虽然通过、内容却是错的。
    （这正是 `ParsedSection.__post_init__` 要用构造期不变量挡住的那类问题；
    可惜那个不变量没有跟着落库，所以在读侧还得再推一次。）
    """
    heading_seq: dict[str, int] = {
        b.id: b.seq for b in blocks
    }
    ordered = sorted(sections, key=lambda s: s.seq)

    out: list[tuple[Section, int, int]] = []
    max_seq = max((b.seq for b in blocks), default=-1)
    for i, sec in enumerate(ordered):
        start = heading_seq.get(sec.source_block_id or "", 0)
        if i + 1 < len(ordered):
            nxt = heading_seq.get(ordered[i + 1].source_block_id or "", max_seq + 1)
            end = max(start, nxt - 1)
        else:
            end = max_seq
        out.append((sec, start, end))
    return out


def extract_material(session: Session, mat_id: str) -> dict[str, Any]:
    """从一份**已解析**的素材里抽取知识点与依赖边。**事务边界由调用方管。**

    只读块与章节、只写 `knowledge_points` 与 `kp_prerequisites`；
    不碰 `material_blocks` / `sections`（那些是解析阶段的产物）。
    """
    blocks = (
        session.scalars(
            select(MaterialBlock)
            .where(MaterialBlock.material_id == mat_id)
            .order_by(MaterialBlock.seq)
        )
        .all()
    )
    if not blocks:
        raise ValueError(f"素材 {mat_id} 还没有解析块 —— 先跑解析（POST /materials 会自动触发）")

    sections = (
        session.scalars(select(Section).where(Section.material_id == mat_id).order_by(Section.seq))
        .all()
    )

    by_seq = {b.seq: b for b in blocks}

    # 重抽之前先清掉旧的（**调用方负责事务**，同 parse 的契约）
    session.execute(delete(KpPrerequisite).where(KpPrerequisite.kp_id.in_(
        select(KnowledgePoint.id).where(KnowledgePoint.material_id == mat_id)
    )))
    session.execute(delete(KnowledgePoint).where(KnowledgePoint.material_id == mat_id))

    now = utc_now_iso()
    created: list[KnowledgePoint] = []

    # ⚠️ **同一节内必须按 name 去重**（`uq_kp_section_name` 是硬约束）。
    #
    #    这个约束是对的 —— 它的注释写着理由：同一节里有重名知识点，
    #    依赖边就会指向「哪个重名的？」，**无法解释**（而可解释性是我们答辩的核心）。
    #
    #    而这里原先没去重，后果不是"少抽了几个"，是**整个抽取任务崩掉**：
    #    真实教材一份材料就有 999 个候选，其中大量同节重名
    #    （`CHAPTER` / `FIVE` / `Victory` …）→ flush 抛 IntegrityError
    #    → 而错误处理路径自己也失败 → **任务永远卡在 running**。
    #
    #    语义上也该去重：**同一个节里出现两次同一个名字，本来就是一个知识点。**
    _seen_in_section: dict[str, set[str]] = {}

    def _add_kp(block: MaterialBlock, sec: Section, seq_in_unit: int) -> None:
        # ★ heading 与 paragraph 走不同的口径（见 _name_from_block 的 docstring）
        name = _name_from_block(block.content_md, is_heading=(block.block_type == "heading"))
        if not name:
            return
        bucket = _seen_in_section.setdefault(sec.id, set())
        if name in bucket:
            return
        bucket.add(name)
        quote = _clean(block.content_md)[:300]
        kp = KnowledgePoint(
            id=knowledge_point_id(mat_id, sec.seq, sec.seq, len(created)),
            section_id=sec.id,
            chapter_id=sec.chapter_id,
            material_id=mat_id,
            name=name,
            summary_md=block.content_md.strip()[:500] or name,
            difficulty=_difficulty_of(block.content_md),
            difficulty_reason=(
                f"结构线索启发式（按长度 {len(block.content_md)} 字符"
                f"{'、含难点词' if any(h in block.content_md for h in _HARD_HINTS) else ''}"
                "估为 %d 级）—— **需人工复核**"
            )
            % _difficulty_of(block.content_md),
            kp_type=_kp_type_of(block.content_md),
            source_material_id=mat_id,
            source_page=block.page_no,
            source_block_id=block.id,
            source_quote=quote,
            confidence=0.5,  # 结构线索的置信度：不足以直接采信，但足以作为候选
            needs_review=_NEEDS_REVIEW,
            seq=len(created),
            created_at=now,
        )
        session.add(kp)
        created.append(kp)

    # ---- 逐节抽候选 ------------------------------------------------------
    for sec, start, end in _section_ranges(sections, blocks):
        for s in range(start, end + 1):
            b = by_seq.get(s)
            if b is None or b.block_type not in ("heading", "paragraph"):
                continue
            # 标题（二级及以下）本身就是知识的名字，直接作候选；
            # 段落走定义句式或首句截断。
            _add_kp(b, sec, s)

    if not created:
        # **抽不出东西要显式报错**，不能静默返回 0 ——
        # 那会让上游以为"抽完了，只是没有知识点"，而真实原因是规则没命中。
        raise ValueError(
            f"素材 {mat_id} 的 {len(blocks)} 个块里没有抽出任何知识点候选 —— "
            "这通常意味着解析产物不含可识别的标题或定义句"
        )

    session.flush()

    # ---- 建边：结构线索只有两种模式 --------------------------------------
    edges: list[KpPrerequisite] = []
    by_section: dict[str, list[KnowledgePoint]] = {}
    for kp in created:
        by_section.setdefault(kp.section_id, []).append(kp)

    ordered_secs = [sec for sec, _, _ in _section_ranges(sections, blocks)]
    prev_tail: KnowledgePoint | None = None
    for sec in ordered_secs:
        kps = by_section.get(sec.id, [])
        if not kps:
            continue
        # ① 节内顺序：先出现的概念是理解后者的基础（soft）
        for a, b in zip(kps, kps[1:], strict=False):
            if a.id == b.id:
                continue
            edges.append(
                KpPrerequisite(
                    kp_id=b.id,
                    prereq_kp_id=a.id,
                    relation_type="soft",
                    reason=f"同属「{sec.title}」，且原文中「{a.name}」先于「{b.name}」出现",
                    evidence_quote=(a.source_quote or "")[:200],
                    source_channel="structure",
                    confidence=0.4,
                    needs_review=1,
                    pruned=0,
                    created_at=now,
                )
            )
        # ② 跨节衔接：上一节的最后一个 → 本节的第一个
        if prev_tail is not None and prev_tail.id != kps[0].id:
            edges.append(
                KpPrerequisite(
                    kp_id=kps[0].id,
                    prereq_kp_id=prev_tail.id,
                    relation_type="soft",
                    reason=(
                        f"章节顺序：「{prev_tail.name}」所在的节先于「{kps[0].name}」所在的"
                        f"「{sec.title}」—— 先学前面的内容是后者的前提"
                    ),
                    evidence_quote=(prev_tail.source_quote or "")[:200],
                    source_channel="structure",
                    confidence=0.35,
                    needs_review=1,
                    pruned=0,
                    created_at=now,
                )
            )
        prev_tail = kps[-1]

    for e in edges:
        session.add(e)
    session.flush()

    return {
        "material_id": mat_id,
        "knowledge_points": len(created),
        "edges": len(edges),
        "sections": len(sections),
        "needs_review": sum(1 for k in created if k.needs_review),
    }
