"""答疑回复模板库（归属：P2）· SPEC §5.3 的模板表。

## SPEC 的模板表（原样）

| turn_type | 数据来源 | 模板骨架 |
|---|---|---|
| `probe` | `kp_misconceptions.trigger_pattern` + 知识点 | "先想一个问题：如果〔槽位〕，会怎样？" |
| `hint1` | 该知识点的 `summary_md` | "提示一个方向：〔摘要〕。你觉得这跟你的问题有什么关系？" |
| `hint2` | `source_quote`（原文片段） | "再缩小一点 —— 材料里说：『〔原文〕』。现在能对应上吗？" |
| `explain` | `summary_md` + 硬前置的 `summary_md` + `source_quote` | 分步拼接 + 过渡语 + 结尾自查问题 |
| `refuse` | 检索到的最接近知识点列表 | 固定模板 |
| `confirm` | `kp_examples` 的变式 | "对，就是这样。〔变式练习〕试试？" |

## ⚠️ 两个模板**没有数据源** —— 如实降级（2026-09-20 实测）

线上库的实测（容器里直接查）：

    KnowledgePoint : 638
    KpMisconception: 0     ← probe 的数据源
    KpExample      : 0     ← confirm 的数据源
    带 summary_md 的：638  ✅
    带 source_quote 的：638 ✅

**抽取（方案 B）只产 `knowledge_points` / `kp_prerequisites`，
不产 `kp_misconceptions` / `kp_examples`** —— 那两张表需要**单独的构建步骤**
（SPEC §4.8 的 P7 提示词，或人工录入），**目前是空的**。

**所以 `probe` 和 `confirm` 降级**：

| turn_type | 原设计 | 降级后 | 为什么这样降 |
|---|---|---|---|
| `probe` | 用 `trigger_pattern` 反问 | **用 `summary_md` 造开放式问题** | summary 是"这个知识点在讲什么"—— 拿它反着问，比拿它当答案更符合苏格拉底 |
| `confirm` | 用 `kp_examples` 出变式 | **用同章节的相邻知识点提问** | 同节的相邻知识点天然是"同一话题的另一个面" |

**降级是如实标注的**：回复里带 `data_source` 字段说明用了什么。
**不假装用了误区数据** —— 这符合 §1.4「宁缺毋错」：宁可承认降级，不制造"功能完整"的假象。

## 为什么文案要放在一个模块里、而且要多变体

SPEC：**「每个模板做 8–12 个变体轮换」**（避免模板痕迹可见）。
所以每个 turn_type 有一个**变体元组**，用 `(session_id, seq)` 做**确定性轮换** ——
同一个会话同一轮永远得到同一个变体（可复现），不同轮次会换（不呆板）。

**确定性而不是随机的理由**：我们要能**回放**一次演示。随机文案会让
"这次为什么这么说"无法复查。
"""

from __future__ import annotations

from typing import Any

from app.tutor.state import TurnType

# ---------------------------------------------------------------------------
# 六个模板 × 多变体
# ---------------------------------------------------------------------------
#
# 槽位（都用 `{}` 标出，组装时填充）：
#   {kp}      知识点名
#   {summary} 知识点摘要（summary_md）
#   {quote}   原文片段（source_quote）
#   {pre}     硬前置知识点的名字（explain 用）
#   {pre_sum} 硬前置知识点的摘要（explain 用）
#   {cands}   最接近的几个知识点（refuse 用）
#   {variant} 变式问题（confirm 用）

PROBE = (
    "先想一个问题：如果{summary_hint}，你觉得会发生什么？\n\n"
    "（不用急着答对 —— 先说说你现在是怎么理解的。）",
    "在讲「{kp}」之前，我想先问你：{summary_hint}。你的直觉是什么？",
    "别急着要答案。假设有人问你「{kp}」到底解决什么问题，你会怎么解释？",
    "我们先不谈标准答案。就你目前的理解，「{kp}」里最关键的一步是哪一步？为什么？",
    "换个角度想：如果没有「{kp}」这个东西，网络通信会遇到什么麻烦？",
    "我想知道你的起点在哪 —— 关于「{kp}」，你已经知道的那部分是什么？",
    "先试着用一句话说说「{kp}」在干什么。说错没关系，我要知道你现在站在哪。",
    "问个更小的：{summary_hint} —— 这个你怎么看？",
)

HINT1 = (
    "提示一个方向：{summary}\n\n你觉得这跟你的问题有什么关系？",
    "给你个方向，不直接说答案：{summary}\n\n顺着这条线想一想。",
    "往这边想 —— {summary}。现在能接上吗？",
    "我先缩小范围：{summary}\n\n你从这个里能推出什么？",
    "一个提示：{summary}\n\n哪个词跟你刚才说的对得上？",
    "别急，先看这句：{summary}\n\n它跟你卡住的地方有什么联系？",
    "方向在这里：{summary}\n\n试着用它解释你刚才的问题。",
    "给你一块拼图：{summary}\n\n它应该能补上你缺的那一角。",
)

HINT2 = (
    "再缩小一点 —— 材料里说：\n\n> {quote}\n\n现在能对应上了吗？",
    "直接给你原文，你来找对应关系：\n\n> {quote}\n\n这句话解释了哪一步？",
    "看这段原文（材料里的原话）：\n\n> {quote}\n\n它答的是不是你刚才那个问题？",
    "材料原文是这样写的：\n\n> {quote}\n\n现在把它的意思用自己的话讲一遍？",
    "提示到这 —— 原文：\n\n> {quote}\n\n哪几个字是关键？",
    "这是材料里的原句：\n\n> {quote}\n\n它和你卡住的那一步是什么关系？",
    "再看一遍材料：\n\n> {quote}\n\n这次能读出来了吗？",
    "最后一块拼图，材料原文：\n\n> {quote}\n\n现在串起来说说看？",
)

EXPLAIN = (
    # explain 是**分步拼接**（SPEC：分步拼接 + 过渡语 + 结尾自查问题）
    "行，连续两次没答上，我直接讲。\n\n"
    "**「{kp}」是这样一件事**：{summary}\n\n"
    "{pre_part}"
    "**材料里的原话**（可以点回原文核对）：\n\n> {quote}\n\n"
    "---\n\n"
    "**自查一下**：把上面这段用自己的话讲一遍，然后回答 —— "
    "如果去掉「{kp}」，你刚才那个问题还成立吗？",
)

REFUSE = (
    "**材料里没有这个内容。**\n\n"
    "我翻了当前入库的材料，没有找到能支撑这个问题的段落 —— "
    "所以我不答，**不猜**。\n\n"
    "不过这几个已入库的知识点可能跟你想问的方向相关，要不从它们入手？\n\n"
    "{cands}\n\n"
    "（如果你觉得材料里确实有，请把那一页或那句话告诉我，我去核对。）",
)

CONFIRM = (
    "对，就是这样。\n\n"
    "{variant}\n\n"
    "试试这个 —— 它跟刚才那题是同一个道理，但换了个说法。",
    "没错。\n\n"
    "那再往前一步：{variant}",
    "答对了。\n\n"
    "用同一套逻辑看这个：{variant}",
    "对了。\n\n"
    "{variant}\n\n"
    "（这题答上来，说明你是真懂了，不是记住的。）",
    "对。\n\n"
    "巩固一下：{variant}",
    "正确。\n\n"
    "换个场景问你：{variant}",
    "就是这样。\n\n"
    "再来一个：{variant}",
    "对了就是这个意思。\n\n"
    "{variant}\n\n"
    "想想它和刚才那题的关系。",
)

#: turn_type -> 变体元组
VARIANTS: dict[TurnType, tuple[str, ...]] = {
    TurnType.PROBE: PROBE,
    TurnType.HINT1: HINT1,
    TurnType.HINT2: HINT2,
    TurnType.EXPLAIN: EXPLAIN,
    TurnType.REFUSE: REFUSE,
    TurnType.CONFIRM: CONFIRM,
}

#: 每个 turn_type 的数据来源标注 —— **降级的地方如实写出来**。
#: 这个字段会进 SSE 的 `state` 事件，评审能看到"这条回复依赖什么数据"。
DATA_SOURCE: dict[TurnType, str] = {
    TurnType.PROBE: "summary_md（**降级**：kp_misconceptions 为空，原设计要用 trigger_pattern）",
    TurnType.HINT1: "summary_md",
    TurnType.HINT2: "source_quote",
    TurnType.EXPLAIN: "summary_md + source_quote + 硬前置 summary_md",
    TurnType.REFUSE: "检索到的最接近知识点",
    TurnType.CONFIRM: "同章节相邻知识点（**降级**：kp_examples 为空，原设计要用变式例题）",
}


def pick_variant(turn_type: TurnType, seed: str) -> int:
    """按一个确定的种子挑变体下标。

    `seed` 用 `f"{session_id}:{seq}"` —— 同会话同步永远同一个变体（可回放），
    不同步会轮换（不呆板）。

    **用 hash 而不是 random**：随机需要保存状态才能回放，而 hash 是可重算的。
    （`hash()` 在同一进程内对 str 是稳定的，但对跨进程不稳定 ——
    所以用 `zlib.crc32` 求一个稳定值，不依赖 `PYTHONHASHSEED`。）
    """
    import zlib

    n = len(VARIANTS[turn_type])
    return zlib.crc32(seed.encode("utf-8")) % n


def render_probe_summary_hint(summary: str, kp_name: str = "") -> str:
    """把 `summary_md` 转成一个**开放式问题**（`probe` 降级后的做法）。

    为什么不能直接把 summary 塞进问句：summary 是**陈述句**，
    直接读出来等于给了半个答案 —— 那违反 R2（首轮绝不给答案）。

    做法：**取摘要里最有信息量的一个短语做引子，把结论留白**。
    实现在这里保持"轻"：不引入任何模型，只用标点与长度切分。
    """
    s = (summary or "").strip()
    if not s:
        return f"「{kp_name}」解决的是什么问题"

    # 取第一句，去掉句末标点
    for sep in ("。", "；", ";", ".", "\n"):
        if sep in s:
            s = s.split(sep)[0]
            break
    s = s.strip()[:60]

    # 陈述 → 疑问：把常见的判断句式换成问法
    # （做不到句子分析，所以只做几个高置信度的替换，其余交给"你觉得"兜住）
    for old, new in (
        ("是指", "是什么意思"),
        ("是", "为什么是"),
        ("用于", "用来干什么"),
        ("通过", "是通过什么"),
    ):
        if old in s:
            return s.replace(old, new, 1)
    return f"{s} —— 这句话在说什么"


def build_reply(
    turn_type: TurnType,
    *,
    seed: str,
    kp_name: str = "",
    summary: str = "",
    quote: str = "",
    pre_name: str = "",
    pre_summary: str = "",
    candidates: list[str] | None = None,
    variant_question: str = "",
) -> tuple[str, dict[str, Any]]:
    """组装一条回复。返回 `(回复正文, 元信息)`。

    元信息里有 `variant_index` / `data_source` —— **两者都进 SSE**，
    让"这条回复是靠什么拼出来的"可被复核（而不是一个黑盒字符串）。
    """
    idx = pick_variant(turn_type, seed)
    tpl = VARIANTS[turn_type][idx]

    cands = candidates or []
    cand_lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(cands[:3]))
    if not cand_lines:
        cand_lines = "（当前库里还没有相关的知识点）"

    variant_q = variant_question or "换一个同章节的知识点，你还能说清它的作用吗"

    body = tpl.format(
        kp=kp_name or "这个知识点",
        summary=summary or "（这个知识点的摘要还没抽出来）",
        quote=quote or "（这个知识点还没有原文片段）",
        summary_hint=render_probe_summary_hint(summary, kp_name),
        pre_part=(f"**先铺垫一步**：{pre_name} —— {pre_summary}\n\n" if pre_name else ""),
        cands=cand_lines,
        variant=variant_q,
    )

    meta = {
        "turn_type": turn_type.value,
        "variant_index": idx,
        "variant_total": len(VARIANTS[turn_type]),
        "data_source": DATA_SOURCE[turn_type],
    }
    return body, meta
