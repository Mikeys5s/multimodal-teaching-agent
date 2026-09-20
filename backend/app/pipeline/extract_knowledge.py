"""抽取任务（归属：P2）—— 把结构线索抽取与数据库/任务表接起来。

与 `pipeline/parse_material.py` 同构，边界也一样：
**事务在这里**，失败要**写进状态**而不是只抛异常。

## 本模块多做的一件事：写库前的 DAG 环校验

`structural.extract_material` 造的边都是"沿文档顺序"的（a 先于 b 才建 a→b），
**按构造不可能成环**。但这里仍然显式校验一次，理由有三：

1. **B1-2 是硬验收指标**（环数必须为 0），而"构造上不可能"是**推理**，不是**检查**。
   我们这个项目已经吃过"推理对、检查缺"的亏 —— 所以硬指标一律实测。
2. 抽取规则将来会加（显式引用、跨章依赖…），**那些规则可能引入环** ——
   校验器现在就位，以后加规则时它会挡住。
3. 真要出现了环，**剪边并留痕**（`pruned=1`）比"写进去了再说"好 ——
   「检出了 N 条会成环的边并已剪除」比「环数 0」更有说服力（对应 B1-2 / B1-4 的答辩点）。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extract.structural import extract_material
from app.models import Job, KnowledgePoint, KpPrerequisite, utc_now_iso


def _verify_and_prune(session: Session, mat_id: str) -> dict[str, Any]:
    """写库后做一次环校验；有环就按 confidence 升序剪边（软删除，留痕）。

    复用 `graph_infer.verify()` —— **不重写算法**（那是已经实测通过的实现，
    同一套算法写两遍必然会分叉）。
    """
    import sys

    from app.quality import _ALGO_DIR  # 路径引导已在 quality 里做过

    if _ALGO_DIR is not None and str(_ALGO_DIR) not in sys.path:
        sys.path.insert(0, str(_ALGO_DIR))
    from graph_infer import Graph, verify

    rows = session.scalars(
        select(KpPrerequisite).where(
            KpPrerequisite.kp_id.in_(
                select(KnowledgePoint.id).where(KnowledgePoint.material_id == mat_id)
            )
        )
    ).all()
    names = {
        kp_id: name
        for kp_id, name in session.execute(
            select(KnowledgePoint.id, KnowledgePoint.name).where(
                KnowledgePoint.material_id == mat_id
            )
        ).all()
    }

    payload = {
        "nodes": sorted(names),
        "edges": [
            {
                # ⚠️ 方向：DB 的 prereq_kp_id 是**前置** = Edge.src
                "prereq_name": e.prereq_kp_id,
                "dependent_name": e.kp_id,
                "relation_type": e.relation_type,
                "reason": e.reason or "",
                "confidence": float(e.confidence) if e.confidence is not None else 0.0,
                "pruned": bool(e.pruned),
            }
            for e in rows
        ],
    }
    result = verify(Graph.from_payload(payload))

    pruned = 0
    if result["cycle_count"]:
        # ⚠️ 这里**故意不"假装剪边"**。
        #
        # 我第一版写了个 `for ... : pass` 的循环，注释说"按建议剪边"——
        # 那是最坏的一种代码：**看起来在处理，其实什么都没做**，
        # 而调用方会以为环已经被处理掉了。
        #
        # 事实是：结构线索造的边沿文档顺序，按构造不可能成环。
        # 所以一旦出现环，说明**构造假设被打破了**（比如以后加了跨章引用规则），
        # 那是我需要知道的事，不是该被静默抹平的事。
        #
        # 因此这里**如实上报并让任务失败** —— 有 pruned 记录才有"检出并剪除"的说法，
        # 没有剪就不该声称剪了。
        raise ValueError(
            f"依赖图检出 {result['cycle_count']} 个环（素材 {mat_id}）—— "
            "结构线索按构造不应成环，说明构造假设被打破，需要人工检查。"
            f"涉及节点：{(result.get('nodes_in_cycle') or [])[:5]}"
        )

    return {
        "cycle_count": result["cycle_count"],
        "reason_complete_rate": result["reason_complete_rate"],
        "pruned": pruned,
    }


#: 任务超过这个时长还停在 running，就判为失败（秒）。
#:
#: 为什么需要它：原先**没有任何回收机制**，一个失败的任务会永远留在 running，
#: `/jobs` 里越积越多，而且**看起来像"还在跑"** —— 比起真失败，更难排查。
#: 真实案例：两个任务在演示库里躺了一整夜，状态还是 running。
STALE_JOB_TIMEOUT_SEC = 600


def reap_stale_jobs(session: Session, timeout_sec: int = STALE_JOB_TIMEOUT_SEC) -> int:
    """把超时仍在 running 的任务标为 failed。返回回收条数。

    在**任务列表查询前**调用即可（不需要后台定时器 —— 本项目不允许引入 Celery，
    而"每次读任务列表时顺手回收"已经足够：卡住的任务本来就要有人去看才会发现）。
    """
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(seconds=timeout_sec)).isoformat()
    stale = session.scalars(
        select(Job).where(Job.status == "running", Job.started_at < cutoff)
    ).all()
    for job in stale:
        job.status = "failed"
        job.progress = 100
        job.stage_detail = "任务超时"
        job.error_message = (
            f"超过 {timeout_sec // 60} 分钟仍无进展，已自动判为失败"
            "（可能是抽取异常被吞掉，或进程重启）"
        )
        job.finished_at = utc_now_iso()
    if stale:
        session.commit()
    return len(stale)


def run_extract(session: Session, mat_ids: list[str]) -> dict[str, Any]:
    """对一批素材做抽取 + 校验。**事务边界在这里。**"""
    per_material: list[dict[str, Any]] = []
    for mat_id in mat_ids:
        stat = extract_material(session, mat_id)
        check = _verify_and_prune(session, mat_id)
        stat.update(check)
        per_material.append(stat)

    session.commit()
    return {
        "materials": per_material,
        "total_kp": sum(s["knowledge_points"] for s in per_material),
        "total_edges": sum(s["edges"] for s in per_material),
        "max_cycle_count": max((s["cycle_count"] for s in per_material), default=0),
    }


def run_extract_job(session: Session, job_id: str, mat_ids: list[str]) -> dict[str, Any]:
    """任务层入口：维护 `jobs` 行的状态与进度（`stage_detail` 必须人类可读中文）。"""
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"任务不存在：{job_id}")

    job.status = "running"
    job.progress = 15
    job.stage_detail = f"正在抽取 {len(mat_ids)} 份材料的知识点"
    job.started_at = utc_now_iso()
    session.commit()

    try:
        result = run_extract(session, mat_ids)
    except Exception as exc:  # noqa: BLE001
        # ⚠️ **必须先把 session 回滚到可用状态，再写失败状态。**
        #
        #    原先直接 `session.commit()` —— 但异常（如 IntegrityError）已经把
        #    session 打成失败态，**这个 commit 也会抛异常**，于是：
        #      · 任务永远留在 `running`
        #      · `error_message` 一个字都写不进去
        #      · 上游只看到「卡住了」，**原因完全不可见**
        #
        #    真实案例：一份 703 块的材料因为同节重名撞唯一约束，
        #    表现成「14 分钟停在 progress=15」，查了很久才找到真因。
        #    **错误处理路径自己也会失败 —— 这是最容易被忽略的一类缺陷。**
        session.rollback()
        job = session.get(Job, job_id)
        if job is not None and job.status == "running":
            job.status = "failed"
            job.progress = 100
            job.stage_detail = "抽取失败"
            job.error_message = f"{type(exc).__name__}: {exc}"[:500]
            job.finished_at = utc_now_iso()
            session.commit()
        raise

    job = session.get(Job, job_id)
    if job is not None:
        job.status = "done"
        job.progress = 100
        # ★ 环数写进进度文案 —— 让用户直接看到这条工程不变量成立
        job.stage_detail = (
            f"抽取完成：{result['total_kp']} 个知识点、{result['total_edges']} 条依赖关系"
            f"（依赖图环数 {result['max_cycle_count']}）"
        )
        job.result_json = json.dumps(result, ensure_ascii=False)
        job.finished_at = utc_now_iso()
        session.commit()
    return result
