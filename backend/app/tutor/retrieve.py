"""答疑的检索层（归属：P2）· SPEC §5.3 R1「必须先检索再回答」。

## 三件事

1. **找到与学生问题最相关的知识点**（决定这一轮讲什么）
2. **判断越界**（找不到 → REFUSE，对应 R4）
3. **卡点根因回溯**（F3.8 ★）—— 沿 `kp_prerequisites` 的 **hard 边反向可达**

## 为什么不用向量

SPEC §4.7 定的是「NumPy 暴力余弦 + FTS5，**不引入向量数据库**」。
但现在库里有 `kp_embeddings` 表却是空的（抽取不产 embedding），
而**目标学科是英文教材 + 中文提问的混合场景** —— 纯字面匹配会漏掉同义表达。

**所以这里的策略是「字面匹配为主、诚实报告置信度」**：

- 中文：按 **2-gram 重叠**打分（不需要分词器）
- 英文：按**词重叠**打分（小写化 + 去停用词）
- 混合：两种都算，取较高者

**并返回 `confidence`** —— 低于阈值就判越界。
**宁可 REFUSE 也不要"猜一个最像的"**（§1.4 宁缺毋错）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgePoint, KpPrerequisite

#: 命中阈值。低于它判越界（→ REFUSE）。
#: 取值理由：2-gram 重叠 2 个以上才算"有实质关系"（见 state.judge_answer 的同款判据），
#: 单字命中在中文里几乎必然发生（"的""是"），不能算证据。
HIT_THRESHOLD = 0.18

#: 英文停用词 —— 不参与打分，否则 "the is a" 会污染结果。
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "of", "to", "in", "on",
    "and", "or", "for", "with", "that", "this", "it", "as", "at", "by", "from",
    "what", "why", "how", "which", "when", "does", "do", "did", "can", "could",
    "的", "了", "是", "在", "和", "与", "有", "会", "什么", "为什么", "怎么",
    "怎样", "如何", "吗", "呢", "那", "这", "我", "你", "它",
}


@dataclass
class Hit:
    """一个检索命中。"""

    kp_id: str
    name: str
    summary_md: str
    source_quote: str
    difficulty: int
    section_id: str
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "kp_id": self.kp_id,
            "name": self.name,
            "difficulty": self.difficulty,
            "score": round(self.score, 4),
        }


def _grams(text: str, n: int = 2) -> set[str]:
    t = re.sub(r"\s+", "", text or "")
    return {t[i : i + n] for i in range(len(t) - n + 1)}


def _words(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{1,}", (text or "").lower())
        if w not in _STOP
    }


def score_text(query: str, target: str) -> float:
    """给「问题」和「知识点文本」算一个 0~1 的相关度。

    两个通道取较高者（**不平均** —— 平均会让"一边命中一边没命中"被拉低，
    而中文提问 + 英文材料**本来就只会在一边命中**）。
    """
    q, t = (query or "").strip(), (target or "").strip()
    if not q or not t:
        return 0.0

    # 通道 1：中文 2-gram（对中英混合也有效，只是会矮一点）
    qg, tg = _grams(q), _grams(t)
    g = len(qg & tg) / max(1, len(qg))

    # 通道 2：英文词重叠
    qw, tw = _words(q), _words(t)
    w = len(qw & tw) / max(1, len(qw)) if qw else 0.0

    return max(g, w)


# ---------------------------------------------------------------------------
# 主检索
# ---------------------------------------------------------------------------


def search_kps(
    session: Session,
    query: str,
    *,
    material_scope: str | None = None,
    limit: int = 5,
) -> list[Hit]:
    """在**已入库的知识点**里找最相关的几个。

    `material_scope`：会话创建时指定的答疑范围（SPEC F3.1）。
    `"all"` 或 `None` = 全部材料；否则是 material_id 的逗号分隔串。
    **范围影响检索域** —— 这是 F3.1 的规格要求，不是可选优化。
    """
    stmt = select(KnowledgePoint)
    if material_scope and material_scope != "all":
        ids = [x.strip() for x in material_scope.split(",") if x.strip()]
        if ids:
            stmt = stmt.where(KnowledgePoint.material_id.in_(ids))

    rows = session.scalars(stmt).all()

    scored: list[Hit] = []
    for kp in rows:
        # 名字权重更高 —— 它是"这个知识点叫什么"，比正文摘要更能代表主题
        s = max(
            score_text(query, kp.name) * 1.6,
            score_text(query, kp.summary_md or ""),
            score_text(query, kp.source_quote or ""),
        )
        if s <= 0:
            continue
        scored.append(
            Hit(
                kp_id=kp.id, name=kp.name, summary_md=kp.summary_md or "",
                source_quote=kp.source_quote or "", difficulty=kp.difficulty or 3,
                section_id=kp.section_id, score=min(1.0, s),
            )
        )

    scored.sort(key=lambda h: (-h.score, -(h.difficulty or 0)))
    return scored[:limit]


def is_out_of_scope(hits: list[Hit]) -> bool:
    """SPEC R4：检索不到就必须 REFUSE。

    **判据是「分数」而不是「有没有结果」** —— 字面匹配总会返回点东西，
    所以"有结果"不等于"材料里有这个内容"。低于 `HIT_THRESHOLD` 一律判越界。
    """
    return not hits or hits[0].score < HIT_THRESHOLD


# ---------------------------------------------------------------------------
# ★ F3.8 卡点根因回溯
# ---------------------------------------------------------------------------


def root_cause_of(session: Session, kp_id: str, *, max_depth: int = 3) -> str | None:
    """沿 `kp_prerequisites` 的 **hard 边反向可达**，找出最可能的断层前置。

    SPEC F3.8 的原话：

    > 学生在知识点 K 卡住时，沿 `kp_prerequisites` 的 **hard 边反向可达**，
    > 结合命中的误区，定位最可能的断层前置知识点 Pk；输出
    > 「你这一题卡在 K，但根因更可能是 Pk 没吃透（材料第 X 页）」。

    ## 两个刻意的选择

    **① 只走 hard 边。** soft 边是"顺序建议"（同节先后出现），
    拿它做根因会指向一堆不相干的邻居 —— 根因必须是**真依赖**。

    **② 返回"最远"的那个前置，而不是"最近"的。**
    理由：卡在 K 时，**最近的前置往往是刚讲过的**（所以才会卡在 K），
    而断层通常在更早的地方。`max_depth=3` 是上限，避免指到章首。

    **③ 找不到就返回 `None`**，不要编一个。
    """
    # 反向可达：从 kp_id 出发，沿 hard 边向 prereq 走
    depth = 0
    frontier = [kp_id]
    farthest: str | None = None
    seen = {kp_id}

    while frontier and depth < max_depth:
        rows = session.execute(
            select(KpPrerequisite.prereq_kp_id).where(
                KpPrerequisite.kp_id.in_(frontier),
                KpPrerequisite.relation_type == "hard",
                KpPrerequisite.pruned == 0,
            )
        ).all()
        nxt = [r[0] for r in rows if r[0] and r[0] not in seen]
        if not nxt:
            break
        seen.update(nxt)
        farthest = nxt[0]      # 越走越远，最后留下的就是最远的
        frontier = nxt
        depth += 1

    return farthest


def kp_page(session: Session, kp_id: str) -> int | None:
    """这个知识点出自材料第几页 —— F3.8 的输出里要带页码。"""
    kp = session.get(KnowledgePoint, kp_id)
    return kp.source_page if kp else None


def kp_brief(session: Session, kp_id: str) -> str:
    """给根因知识点起一个可读的"名字（第 X 页）"。"""
    kp = session.get(KnowledgePoint, kp_id)
    if kp is None:
        return ""
    page = f"（第 {kp.source_page} 页）" if kp.source_page else ""
    return f"{kp.name}{page}"


def sibling_variant(session: Session, kp_id: str) -> str:
    """找一个**同章节的相邻知识点**当变式问题（`confirm` 降级后的做法）。

    为什么是同章节：同一节的相邻知识点天然是"同一话题的另一个面"，
    用它提问既能巩固、又不会跳到不相干的内容上。

    `kp_examples` 为空时的替代方案 —— 恢复数据后应换回真正的变式例题。
    """
    kp = session.get(KnowledgePoint, kp_id)
    if kp is None:
        return ""
    rows = session.scalars(
        select(KnowledgePoint)
        .where(
            KnowledgePoint.section_id == kp.section_id,
            KnowledgePoint.id != kp.id,
        )
        .order_by(KnowledgePoint.seq)
        .limit(1)
    ).all()
    if not rows:
        return ""
    return f"那「{rows[0].name}」呢？它跟「{kp.name}」是什么关系？"
