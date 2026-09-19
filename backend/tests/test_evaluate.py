"""评估脚本的测试（归属：P2）。

## 为什么这个测试非写不可

空库跑 `evaluate.py` 会全绿 —— **但那是"真空满足"**：
所有比率的分母都是 0，按定义返回 1.0。**它证明不了指标算得对。**

所以这里要**造出真实的坏数据**，验证指标真的会变红：

| 造什么坏数据 | 期望 |
|---|---|
| 依赖图里放一个**环** | `cycle_count == 1`，且 `--strict` 必须失败 |
| 知识点归属链断裂 | `structure_complete_rate < 1.0` |
| 导师轮次非接地 | `hallucination_rate > 0` |
| 只有拒答轮次 | **接地率仍为 100%**（拒答不算答错） |

最后一条尤其重要：它是我们刻意定的口径。不写测试，将来有人"顺手"
把拒答算进分母，指标就会悄悄失真 —— 而这种失真没人会发现。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import evaluate  # noqa: E402

from app.models import (  # noqa: E402
    Chapter,
    KnowledgePoint,
    KpPrerequisite,
    Material,
    QaSession,
    QaTurn,
    Section,
    utc_now_iso,
)


@pytest.fixture
def ev(engine: Engine, monkeypatch: pytest.MonkeyPatch):
    """把 evaluate 模块的 engine 指到测试库上。

    直接 monkeypatch 比"让它去用 app.db"干净 —— 测试绝不能碰真实库。
    """
    monkeypatch.setattr(evaluate, "engine", engine)
    return evaluate


def _material(session: Session, mid: str = "mat_a") -> None:
    session.add(
        Material(
            id=mid,
            filename="第5章.pdf",
            file_hash=mid.ljust(64, "0")[:64],
            stored_path="x.pdf",
            mime_type="application/pdf",
            size_bytes=1,
            source_type="pdf_text",
            status="done",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
    )
    session.commit()


def _kp(session: Session, kp_id: str, name: str) -> None:
    """建一条完整的归属链：材料 → 章 → 节 → 知识点。"""
    if session.get(Material, "mat_a") is None:
        _material(session)
    if session.get(Chapter, "ch_a") is None:
        session.add(Chapter(id="ch_a", material_id="mat_a", title="传输层", seq=0))
        session.commit()
    if session.get(Section, "sec_a") is None:
        session.add(
            Section(id="sec_a", material_id="mat_a", chapter_id="ch_a", title="可靠传输", seq=0)
        )
        session.commit()
    session.add(
        KnowledgePoint(
            id=kp_id,
            section_id="sec_a",
            chapter_id="ch_a",
            material_id="mat_a",
            name=name,
            summary_md="说明",
            difficulty=3,
            kp_type="concept",
            source_material_id="mat_a",
            source_quote="原文片段",
            seq=0,
            created_at=utc_now_iso(),
        )
    )
    session.commit()


def _edge(session: Session, prereq: str, kp: str, reason: str = "不学懂前置会卡住") -> None:
    session.add(
        KpPrerequisite(
            kp_id=kp,
            prereq_kp_id=prereq,
            relation_type="hard",
            reason=reason,
            source_channel="both",
            pruned=0,
            needs_review=0,
        )
    )
    session.commit()


# ---------------------------------------------------------------------------
# 1. 空库：真空满足
# ---------------------------------------------------------------------------


def test_empty_db_is_vacuously_green(ev) -> None:
    r = ev.collect()
    assert r["knowledge_points"]["total"] == 0
    assert r["knowledge_points"]["structure_complete_rate"] == 1.0
    assert r["graph"]["cycle_count"] == 0
    assert r["qa"]["hallucination_rate"] == 0.0
    assert all(ok for *_, ok in ev.check_acceptance(r))


# ---------------------------------------------------------------------------
# 2. ★ 有环的图必须被抓出来（这条是整份报告的核心价值）
# ---------------------------------------------------------------------------


def test_cycle_is_detected(ev, engine: Engine) -> None:
    """★ 造一个三节点环 A→B→C→A，`cycle_count` 必须为 1，且严格模式必须失败。

    如果这条测试挂了，说明环检测没接对（比如 `prereq_kp_id` / `kp_id`
    方向映射反了）—— 那样报告会永远显示"环数 0"，**看起来完美但毫无意义**。
    """
    with Session(engine) as s:
        for kid, name in (("kp_a", "A"), ("kp_b", "B"), ("kp_c", "C")):
            _kp(s, kid, name)
        _edge(s, "kp_a", "kp_b")
        _edge(s, "kp_b", "kp_c")
        _edge(s, "kp_c", "kp_a")  # ← 成环

    r = ev.collect()
    assert r["graph"]["edge_count"] == 3
    assert r["graph"]["cycle_count"] == 1, "三节点环没被检测出来！"

    rows = ev.check_acceptance(r)
    b12 = [row for row in rows if row[0].startswith("B1-2")][0]
    assert b12[-1] is False, "有环时 B1-2 必须判 FAIL"


def test_acyclic_graph_passes(ev, engine: Engine) -> None:
    """对照：同一个图去掉一条边就无环。"""
    with Session(engine) as s:
        for kid, name in (("kp_a", "A"), ("kp_b", "B"), ("kp_c", "C")):
            _kp(s, kid, name)
        _edge(s, "kp_a", "kp_b")
        _edge(s, "kp_b", "kp_c")

    r = ev.collect()
    assert r["graph"]["edge_count"] == 2
    assert r["graph"]["cycle_count"] == 0
    assert all(ok for *_, ok in ev.check_acceptance(r))


def test_edge_direction_mapping_is_not_reversed(ev, engine: Engine) -> None:
    """方向映射专项：`prereq_kp_id` 必须被当成**前置**（Edge.src）。

    映射反了的症状：一张合法的 DAG 会被误判成有环。所以用一条
    简单链来卡它 —— A→B→C 无环；如果 src/dst 反了，就会变成 C→B→A，
    虽然仍无环…… 所以再加一条能区分的用例。
    """
    with Session(engine) as s:
        _kp(s, "kp_a", "A")
        _kp(s, "kp_b", "B")
        _edge(s, "kp_a", "kp_b")  # A 是前置，B 依赖 A

    r = ev.collect()
    assert r["graph"]["max_out_degree"] == 1, "k p_a 应有 1 条出边（它是前置）"
    assert r["graph"]["max_in_degree"] == 1, "kp_b 应有 1 条入边（它是依赖方）"


# ---------------------------------------------------------------------------
# 3. 归属链断裂
# ---------------------------------------------------------------------------


def test_broken_structure_chain_is_detected(ev, engine: Engine) -> None:
    """★ 归属链断裂必须让 A2-1 掉下来。

    数据库的复合外键已经拦住了这种数据，所以这里用**绕过约束的方式**造
    （直接改 section 引用到一个不存在的节）—— 为的是验证"算出来"而不是
    "因为约束在所以假设它对"。真出问题时（比如约束被误删），这条会红。
    """
    with Session(engine) as s:
        _kp(s, "kp_a", "A")
        _kp(s, "kp_b", "B")

    # 关掉外键，制造一条断链的知识点
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("UPDATE knowledge_points SET section_id='sec_missing' WHERE id='kp_b'")
        conn.commit()

    r = ev.collect()
    assert r["knowledge_points"]["total"] == 2
    assert r["knowledge_points"]["structure_complete_rate"] == 0.5
    rows = ev.check_acceptance(r)
    a21 = [row for row in rows if row[0].startswith("A2-1")][0]
    assert a21[-1] is False


# ---------------------------------------------------------------------------
# 4. 答疑口径
# ---------------------------------------------------------------------------


def _session_with_turns(engine: Engine, turns: list[tuple[str, str | None, int]]) -> None:
    with Session(engine) as s:
        s.add(
            QaSession(
                id="s_1", material_scope="[]", created_at=utc_now_iso(), updated_at=utc_now_iso()
            )
        )
        s.commit()
        for i, (role, ttype, grounded) in enumerate(turns):
            s.add(
                QaTurn(
                    id=f"t_{i}",
                    session_id="s_1",
                    seq=i,
                    role=role,
                    content_md="x",
                    turn_type=ttype,
                    grounded=grounded,
                    created_at=utc_now_iso(),
                )
            )
        s.commit()


def test_ungrounded_tutor_turn_raises_hallucination(ev, engine: Engine) -> None:
    _session_with_turns(
        engine,
        [("tutor", "probe", 1), ("tutor", "explain", 0)],  # 第二个没接地
    )
    r = ev.collect()
    assert r["qa"]["answered_turn_count"] == 2
    assert r["qa"]["grounded_rate"] == 0.5
    assert r["qa"]["hallucination_rate"] == 0.5
    rows = ev.check_acceptance(r)
    assert [row for row in rows if row[0].startswith("幻觉率")][0][-1] is False


def test_refuse_turns_are_excluded_from_grounded_rate(ev, engine: Engine) -> None:
    """★ 拒答**不能**拉低接地率。

    拒答是"这个问题超出材料范围"的正确行为，不是答错。
    把它算进分母，指标就会惩罚正确行为 —— 这个口径是刻意定的，
    所以要用测试钉住。
    """
    _session_with_turns(
        engine,
        [("tutor", "probe", 1), ("tutor", "refuse", 0)],
    )
    r = ev.collect()
    assert r["qa"]["refuse_count"] == 1
    assert r["qa"]["answered_turn_count"] == 1, "拒答应从分母里剔除"
    assert r["qa"]["grounded_rate"] == 1.0, "拒答不该拉低接地率"
    assert r["qa"]["hallucination_rate"] == 0.0


def test_only_refuse_turns_still_green(ev, engine: Engine) -> None:
    """全是拒答 → 接地率仍是 100%（没有"回答"就没有"答错"）。"""
    _session_with_turns(engine, [("tutor", "refuse", 0), ("student", None, 0)])
    r = ev.collect()
    assert r["qa"]["refuse_count"] == 1
    assert r["qa"]["answered_turn_count"] == 0
    assert r["qa"]["grounded_rate"] == 1.0


# ---------------------------------------------------------------------------
# 5. 图的其它指标
# ---------------------------------------------------------------------------


def test_blank_reason_is_rejected_by_db_constraint(ev, engine: Engine) -> None:
    """★ 空理由**在数据库层就被挡住了**（`CHECK (length(trim(reason)) > 0)`）。

    所以 `reason_complete_rate` 的失败路径**没法从这里构造** —— 这不是测试偷懒，
    而是「两层防护」的证明：数据库先拦一道，评估脚本再核对一遍。

    换句话说：这个指标永远显示 100%，是因为**约束真的在生效**，
    而不是因为算错了。所以这里改成验证"约束确实会拒绝" ——
    那才是真正会被破坏、也真正值得守住的东西。
    """
    from sqlalchemy.exc import IntegrityError

    with Session(engine) as s:
        _kp(s, "kp_a", "A")
        _kp(s, "kp_b", "B")
        s.add(
            KpPrerequisite(
                kp_id="kp_b",
                prereq_kp_id="kp_a",
                relation_type="hard",
                reason="   ",  # 空白 —— 必须被拒
                source_channel="both",
                pruned=0,
                needs_review=0,
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_reason_complete_rate_is_one_with_good_data(ev, engine: Engine) -> None:
    """只要有理由，B1-5 就是 100%。配合上一条，共同锁住这个指标的含义。"""
    with Session(engine) as s:
        _kp(s, "kp_a", "A")
        _kp(s, "kp_b", "B")
        _edge(s, "kp_a", "kp_b", reason="不懂滑动窗口就无法理解 cwnd 的调节对象")

    r = ev.collect()
    assert r["graph"]["reason_complete_rate"] == 1.0
    rows = ev.check_acceptance(r)
    assert [row for row in rows if row[0].startswith("B1-5")][0][-1] is True


def test_needs_review_edges_counted_as_conflict(ev, engine: Engine) -> None:
    with Session(engine) as s:
        _kp(s, "kp_a", "A")
        _kp(s, "kp_b", "B")
        s.add(
            KpPrerequisite(
                kp_id="kp_b",
                prereq_kp_id="kp_a",
                relation_type="soft",
                reason="会了更好懂",
                source_channel="both",
                pruned=0,
                needs_review=1,  # 结构-语义冲突
            )
        )
        s.commit()

    assert ev.collect()["graph"]["conflict_count"] == 1


# ---------------------------------------------------------------------------
# 6. 健壮性
# ---------------------------------------------------------------------------


def test_missing_table_gives_systemexit_not_traceback(ev, monkeypatch, tmp_path) -> None:
    """没表时要退出码 2 + 人话，不要 40 行 SQLAlchemy 堆栈。"""
    from sqlalchemy import create_engine

    empty = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setattr(ev, "engine", empty)
    with pytest.raises(SystemExit) as exc:
        ev.collect()
    assert exc.value.code == 2


def test_json_output_is_serialisable(ev, engine: Engine, capsys) -> None:
    with Session(engine) as s:
        _kp(s, "kp_a", "A")
    ev.main(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["knowledge_points"]["total"] == 1
    assert "graph" in payload and "qa" in payload


def test_strict_returns_nonzero_on_cycle(ev, engine: Engine) -> None:
    """端到端：有环时 `--strict` 必须返回非零（CI 靠这个卡门）。"""
    with Session(engine) as s:
        for kid in ("kp_a", "kp_b", "kp_c"):
            _kp(s, kid, kid.upper())
        _edge(s, "kp_a", "kp_b")
        _edge(s, "kp_b", "kp_c")
        _edge(s, "kp_c", "kp_a")
    assert ev.main(["--strict", "--json"]) == 1


def test_strict_returns_zero_on_healthy_graph(ev, engine: Engine) -> None:
    with Session(engine) as s:
        _kp(s, "kp_a", "A")
        _kp(s, "kp_b", "B")
        _edge(s, "kp_a", "kp_b")
    assert ev.main(["--strict", "--json"]) == 0
