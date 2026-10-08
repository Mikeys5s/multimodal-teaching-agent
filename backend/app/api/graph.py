"""图谱与学习路径（归属：P2）。对应 docs/api-spec.md §4.4，端点 16、17。

★ 本文件把**工程不变量变成评委可见的信任信号**：
`stats.cycle_count` 必须展示为 0；同时展示 `pruned_count`（因成环被剪除的边数）与
`conflict_count`（结构-语义冲突边数）—— **"检出了 2 条会成环的边并已剪除"比只写"环数 0"
更有说服力**，因为它证明系统真的在检查，而不只是恰好没出错（B1-2 / B1-4）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.response import Envelope, ok
from app.db import get_db
from app.graph_view import learning_path, load_graph
from app.schemas.graph import (
    GraphEdgeOut,
    GraphNodeOut,
    GraphOut,
    GraphStatsOut,
    LearningPathStepOut,
)

router = APIRouter(tags=["graph"])

DbSession = Annotated[Session, Depends(get_db)]




# ---------------------------------------------------------------------------
# 可读标题（**把被切坏的名字换成人看得懂的东西**）
# ---------------------------------------------------------------------------

_TITLES: dict[str, str] | None = None


def _load_titles() -> dict[str, str]:
    """读 `backend/app/kp-titles.json` → `{kp_id: display_title}`（只读一次）。

    **为什么图也要它**：节点现在显示的 `name` 常是被切坏的句片段
    （`There` / `At the heart of TCP`），而可读标题是从**材料小节标题或首句**
    提炼的 —— 438/629 有。

    **加载失败返回空 dict** ⇒ `display_title` 全为 None ⇒
    前端退回 `name` ⇒ **图照常显示**。
    """
    global _TITLES
    if _TITLES is None:
        import json as _json
        import pathlib as _pathlib

        p = _pathlib.Path(__file__).resolve().parents[1] / "kp-titles.json"
        try:
            items = _json.loads(p.read_text(encoding="utf-8")).get("items", [])
            _TITLES = {x["kp_id"]: x["display_title"]
                       for x in items if x.get("display_title")}
        except Exception:  # noqa: BLE001
            _TITLES = {}
    return _TITLES



@router.get(
    "/knowledge-graph",
    response_model=Envelope[GraphOut],
    summary="知识图谱数据",
    description=(
        "返回 DAG 的节点、边与统计。\n\n"
        "节点带 `difficulty`（前端做颜色映射）与 `needs_review`；边带 `relation_type`。\n"
        "**`stats.cycle_count` 为 0** 是本项目的工程不变量；"
        "`pruned_count` / `conflict_count` 则说明这个 0 是「检查过」的结果，不只是恰好没出错。"
    ),
)
def get_graph(
    db: DbSession,
    material_id: Annotated[str | None, Query()] = None,
    chapter_id: Annotated[str | None, Query()] = None,
    max_nodes: Annotated[int, Query(ge=1, le=1000, description="节点数上限")] = 200,
) -> Envelope[GraphOut]:
    # ★ 真读库 + 真做环校验。
    #
    # 这里最容易写错的一处：`stats.cycle_count` **不是常量 0**，它来自
    # `graph_infer.verify()` 的实算结果。区别很重要 ——
    # **「检查过的 0」和「恰好没出错的 0」不是一回事**，
    # 而前者才配写进答辩材料（对应 B1-2 的验收口径）。
    graph, kps, edge_rows, result = load_graph(db, material_id=material_id, chapter_id=chapter_id)

    # 截断到 max_nodes —— **按重要性取，不按 seq**（2026-10-08 改）。
    #
    # ⚠️ 原先写的是 `kps[:max_nodes]`（**按 seq 取前 N 个**）——
    # 那意味着评委打开图谱看到的是「顺序排在前面的 200 个」，
    # **而不是「最值得看的 200 个」**。而最硬的跨章依赖边很可能落在被截掉的部分。
    #
    # **判据（量过，不是拍的）**：
    #     score = hard 边数 × 3 + 总度数 × 1          （同分按 id 稳定排序）
    #
    #     按 seq 取 200 ⇒ hard 边覆盖 **18/23 = 78.3%**
    #     按 score 取 200 ⇒ hard 边覆盖 **23/23 = 100%**
    #
    # **为什么 hard 权重高**：`hard` 是真的知识依赖（材料原文支持），
    # 而 `soft` 是结构线索（章节顺序）。**答辩主线是依赖图** ⇒ hard 更值钱。
    #
    # ⚠️ 我试过一个「更聪明」的变体（把章节标题降权）—— **反而掉到 95.7%**，
    # 因为 `QUIC` / `DHCP` 这类全大写但**确实是知识点**。**判据不成立就弃用。**
    titles = _load_titles()      # ⚠️ **先加载再引用**（`_TITLES` 初值是 None）
    deg: dict[str, int] = {}
    hard: dict[str, int] = {}
    for e in edge_rows:
        if e.pruned:
            continue
        for kp in (e.prereq_kp_id, e.kp_id):
            deg[kp] = deg.get(kp, 0) + 1
            if e.relation_type == "hard":
                hard[kp] = hard.get(kp, 0) + 1

    ranked = sorted(kps, key=lambda k: (-(hard.get(k.id, 0) * 3 + deg.get(k.id, 0)), k.id))
    kept = ranked[:max_nodes]
    kept_ids = {k.id for k in kept}

    nodes = [
        GraphNodeOut(
            id=k.id,
            name=k.name,
            # ⭐ 可读标题（438/629 有）—— 前端优先显示它，`name` 收进 tooltip。
            #    取不到返回 None ⇒ 前端退回 `name`。**不编。**
            display_title=titles.get(k.id),
            difficulty=k.difficulty,
            chapter_id=k.chapter_id,
            section_id=k.section_id,
            needs_review=bool(k.needs_review),
        )
        for k in kept
    ]
    edges = [
        GraphEdgeOut(
            source=e.prereq_kp_id,  # ★ 前置 = source（硬约定，见 docs/api-spec.md §4.4）
            target=e.kp_id,
            relation_type=e.relation_type,
        )
        for e in edge_rows
        if not e.pruned and e.kp_id in kept_ids and e.prereq_kp_id in kept_ids
    ]

    return ok(
        GraphOut(
            material_id=material_id,
            nodes=nodes,
            edges=edges,
            stats=GraphStatsOut(
                node_count=len(nodes),
                edge_count=len(edges),
                cycle_count=result["cycle_count"],  # ★ 实算，不是常量
                pruned_count=result["pruned_edge_count"],
                conflict_count=sum(1 for e in edge_rows if e.needs_review == 1),
                hard_edge_count=sum(1 for e in edges if e.relation_type == "hard"),
                soft_edge_count=sum(1 for e in edges if e.relation_type == "soft"),
            ),
        )
    )


@router.get(
    "/learning-path",
    # ⚠️ **顶层数组，不是对象** —— api-spec §4.4 就是这么承诺的。
    #
    #    原先这里是 `Envelope[LearningPathOut]`，实际返回 `{target_kp_id, steps}`，
    #    与 spec 不符。后果不是"少了字段"，是**前端 `/path` 页直接崩**：
    #    `PathTimeline` 对返回值做 `for (const step of steps)`，
    #    而对象不可迭代 -> `steps is not iterable`；且 `steps.length` 是 undefined，
    #    连「加载中 / 空状态 / 时间线」三个分支全部落空 -> **白屏且无提示**。
    #
    #    P3 在前端做了"两种形状都读"的兼容层兜住了（并因此在 #15 评论区请我收口）。
    #    **spec 是唯一权威源** —— 所以这里改后端，不是改 spec。
    response_model=Envelope[list[LearningPathStepOut]],
    summary="学习路径",
    description=(
        "拓扑有序的学习路径。\n\n"
        "**每一步的 `reason` 来自依赖边上的 reason** —— 前端逐条展示，"
        "让「为什么这个要排在前面」可解释，而不是黑盒拓扑排序的结果。"
    ),
)
def get_learning_path(
    db: DbSession,
    kp_id: Annotated[str, Query(description="目标知识点 id")],
) -> Envelope[list[LearningPathStepOut]]:
    if not kp_id.startswith("kp_"):
        raise ApiError(ErrorCode.NOT_FOUND, f"知识点 {kp_id} 不存在（id 应以 kp_ 开头）")

    # ★ 真算路径：沿 hard 边反向可达 + 拓扑排序（算法在 graph_infer，不重写）
    graph, kp_rows, _, _ = load_graph(db)
    by_id = {k.id: k for k in kp_rows}

    result = learning_path(graph, kp_id)
    if not result.get("ok"):
        # 目标不在图里 —— 可能是 id 不存在，也可能是它还没有任何依赖边。
        # **两者都该报 404**：对调用方来说"查不到这个知识点的路径"是同一件事。
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"知识点 {kp_id} 不在依赖图里（可能不存在，或它还没有任何前置依赖边）",
        )

    steps = [
        LearningPathStepOut(
            order=i + 1,
            kp_id=s["knowledge_point"],
            name=(by_id[s["knowledge_point"]].name if s["knowledge_point"] in by_id else ""),
            difficulty=(
                by_id[s["knowledge_point"]].difficulty
                if s["knowledge_point"] in by_id
                else 3
            ),
            # ★ reason 直接来自边上的 reason（api-spec 的约定）——
            #   这样"为什么这个要排在前面"是可解释的，不是黑箱拓扑排序的结果。
            reason=(s.get("reason") or None),
            is_start_point=bool(s.get("is_start_point")),
        )
        for i, s in enumerate(result["steps"])
    ]
    # ★ **返回顶层数组**（api-spec §4.4 的承诺）。
    #
    # ⚠️ 改 `response_model` 时**必须同时改这里** —— 否则模型说"要数组"、
    #    函数返回对象，FastAPI 会在响应校验那一步抛错。
    #    （我这次就先改了签名，隔了几步才想起来看返回体 —— 差一点又漏。）
    return ok(steps)
