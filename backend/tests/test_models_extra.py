"""第二批 8 张表的约束测试（归属：P2）。

覆盖 docs/data-model.md §2.6–§2.12。这些约束守的是几个具体承诺：

| 约束 | 守的是什么 |
|---|---|
| `questions.answer_missing_consistent` | 不允许「标了缺答案却又有答案」这种自相矛盾的数据 —— Stage 1 的"存疑处"必须是真的 |
| `kp_misconceptions.source` | LLM 推断的误区**不得伪装成人类确认过的结论** |
| `kp_embeddings.dim_matches_vector_length` | 维度与字节数不符会让 `numpy.frombuffer` 读出垃圾数据**且不报错** |
| `jobs.progress BETWEEN 0 AND 100` | 进度条的入参 |
| `qa_turns.grounded` | 「幻觉率必须为 0」这条红线的载体 |
"""

from __future__ import annotations

import struct

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Chapter,
    Job,
    KnowledgePoint,
    KpEmbedding,
    KpExample,
    KpMisconception,
    LlmCall,
    Material,
    QaSession,
    QaTurn,
    Question,
    Section,
    utc_now_iso,
)

HASH_A = "a" * 64


def _f32(*values: float) -> bytes:
    """构造 float32 小端连续数组 —— 与 `kp_embeddings.vector` 的存储约定一致。"""
    return struct.pack(f"<{len(values)}f", *values)


def must_fail(session: Session, obj: object) -> None:
    with pytest.raises(IntegrityError):
        session.add(obj)
        session.flush()
    session.rollback()


@pytest.fixture
def chain(session: Session) -> dict[str, str]:
    """最小可用链路：材料 → 章 → 节 → 知识点。"""
    mat = Material(
        id="mat_a",
        filename="第5章.pdf",
        file_hash=HASH_A,
        stored_path="x.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        source_type="pdf_text",
        status="done",
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )
    session.add(mat)
    session.flush()

    ch = Chapter(id="ch_a", material_id="mat_a", title="传输层", seq=0)
    session.add(ch)
    session.flush()

    sec = Section(id="sec_a", material_id="mat_a", chapter_id="ch_a", title="可靠传输", seq=0)
    session.add(sec)
    session.flush()

    kp = KnowledgePoint(
        id="kp_a",
        section_id="sec_a",
        chapter_id="ch_a",
        material_id="mat_a",
        name="滑动窗口",
        summary_md="说明",
        difficulty=3,
        kp_type="concept",
        source_material_id="mat_a",
        source_quote="原文",
        seq=0,
        created_at=utc_now_iso(),
    )
    session.add(kp)
    session.commit()
    return {"material": "mat_a", "chapter": "ch_a", "section": "sec_a", "kp": "kp_a"}


# ---------------------------------------------------------------------------
# questions —— 「存疑处」必须是真的
# ---------------------------------------------------------------------------


def _question(**over) -> Question:
    data = {
        "id": "q_1",
        "material_id": "mat_a",
        "question_type": "single_choice",
        "stem_md": "题干",
        "answer_md": "A",
        "answer_missing": 0,
    }
    data.update(over)
    return Question(**data)


def test_question_valid_round_trips(session: Session, chain: dict[str, str]) -> None:
    session.add(_question())
    session.commit()
    assert session.get(Question, "q_1") is not None


def test_question_type_must_be_known(session: Session, chain: dict[str, str]) -> None:
    must_fail(session, _question(question_type="essay"))


def test_answer_missing_1_requires_null_answer(session: Session, chain: dict[str, str]) -> None:
    """标了「材料没给答案」就不能同时有答案 —— 否则存疑处是假的。"""
    must_fail(session, _question(answer_missing=1, answer_md="A"))


def test_answer_missing_0_requires_an_answer(session: Session, chain: dict[str, str]) -> None:
    must_fail(session, _question(answer_missing=0, answer_md=None))


def test_answer_missing_1_without_answer_is_accepted(
    session: Session, chain: dict[str, str]
) -> None:
    session.add(_question(answer_missing=1, answer_md=None))
    session.commit()
    assert session.get(Question, "q_1") is not None


# ---------------------------------------------------------------------------
# kp_examples / kp_misconceptions
# ---------------------------------------------------------------------------


def test_example_difficulty_range_is_enforced(session: Session, chain: dict[str, str]) -> None:
    session.add(
        KpExample(
            id="ex_1", kp_id="kp_a", question_type="single_choice", stem_md="题", answer_md="A"
        )
    )
    session.commit()
    must_fail(
        session,
        KpExample(
            id="ex_2",
            kp_id="kp_a",
            question_type="single_choice",
            stem_md="题",
            answer_md="A",
            difficulty=9,
        ),
    )


def test_misconception_source_must_be_known(session: Session, chain: dict[str, str]) -> None:
    """★ LLM 推断的误区不得伪装成人类确认过的结论。"""
    must_fail(
        session,
        KpMisconception(id="mis_1", kp_id="kp_a", description="误区", source="guessed"),
    )


def test_misconception_source_llm_inferred_is_allowed(
    session: Session, chain: dict[str, str]
) -> None:
    """来源是 llm_inferred 也要能存 —— 重点是**如实标注**，不是禁止。"""
    session.add(
        KpMisconception(id="mis_1", kp_id="kp_a", description="误区", source="llm_inferred")
    )
    session.commit()
    assert session.get(KpMisconception, "mis_1") is not None


# ---------------------------------------------------------------------------
# kp_embeddings
# ---------------------------------------------------------------------------


def test_embedding_dim_must_match_vector_length(session: Session, chain: dict[str, str]) -> None:
    """★ 维度与字节数不符会让 numpy.frombuffer 读出垃圾数据且不报错 —— 必须在写入时拦住。"""
    good = _f32(1.0, 2.0, 3.0)  # 3 维 = 12 字节
    session.add(
        KpEmbedding(
            kp_id="kp_a", model="m", dim=3, vector=good, text_hash="h", created_at=utc_now_iso()
        )
    )
    session.commit()

    bad = _f32(1.0, 2.0)  # 只有 8 字节，却声称 3 维
    must_fail(
        session,
        KpEmbedding(
            kp_id="kp_a", model="m", dim=3, vector=bad, text_hash="h", created_at=utc_now_iso()
        ),
    )


# ---------------------------------------------------------------------------
# qa —— 幻觉率红线的载体
# ---------------------------------------------------------------------------


def test_qa_turn_role_must_be_known(session: Session, chain: dict[str, str]) -> None:
    session.add(
        QaSession(
            id="s_1",
            material_scope="[]",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
    )
    session.commit()

    session.add(
        QaTurn(
            id="t_1",
            session_id="s_1",
            seq=0,
            role="tutor",
            content_md="先想一个问题",
            turn_type="probe",
            grounded=1,
            created_at=utc_now_iso(),
        )
    )
    session.commit()

    must_fail(
        session,
        QaTurn(
            id="t_2",
            session_id="s_1",
            seq=1,
            role="teacher",  # 非法角色
            content_md="x",
            grounded=1,
            created_at=utc_now_iso(),
        ),
    )


def test_qa_turn_type_must_be_known(session: Session, chain: dict[str, str]) -> None:
    session.add(
        QaSession(id="s_1", material_scope="[]", created_at=utc_now_iso(), updated_at=utc_now_iso())
    )
    session.commit()
    must_fail(
        session,
        QaTurn(
            id="t_1",
            session_id="s_1",
            seq=0,
            role="tutor",
            content_md="x",
            turn_type="lecture",  # 不在状态机词表里
            grounded=1,
            created_at=utc_now_iso(),
        ),
    )


def test_qa_turn_seq_unique_within_session(session: Session, chain: dict[str, str]) -> None:
    session.add(
        QaSession(id="s_1", material_scope="[]", created_at=utc_now_iso(), updated_at=utc_now_iso())
    )
    session.commit()
    session.add(
        QaTurn(
            id="t_1",
            session_id="s_1",
            seq=0,
            role="student",
            content_md="a",
            grounded=0,
            created_at=utc_now_iso(),
        )
    )
    session.commit()
    must_fail(
        session,
        QaTurn(
            id="t_2",
            session_id="s_1",
            seq=0,  # 同会话同 seq
            role="tutor",
            content_md="b",
            grounded=1,
            created_at=utc_now_iso(),
        ),
    )


def test_grounded_accepts_refuse_turn_as_zero(session: Session, chain: dict[str, str]) -> None:
    """★ 拒答轮次必须能记 `grounded=0` —— 否则"接地率"会被算高，幻觉率红旗就形同虚设。"""
    session.add(
        QaSession(id="s_1", material_scope="[]", created_at=utc_now_iso(), updated_at=utc_now_iso())
    )
    session.commit()
    session.add(
        QaTurn(
            id="t_1",
            session_id="s_1",
            seq=0,
            role="tutor",
            content_md="这个问题超出当前材料范围",
            turn_type="refuse",
            grounded=0,
            created_at=utc_now_iso(),
        )
    )
    session.commit()
    turn = session.get(QaTurn, "t_1")
    assert turn is not None and turn.grounded == 0


# ---------------------------------------------------------------------------
# jobs —— 进度必须对用户可读
# ---------------------------------------------------------------------------


def _job(**over) -> Job:
    data = {
        "id": "job_1",
        "job_type": "parse",
        "status": "running",
        "progress": 35,
        "stage_detail": "正在识别第 7/20 页",
        "created_at": utc_now_iso(),
    }
    data.update(over)
    return Job(**data)


def test_job_valid_round_trips_with_readable_stage_detail(
    session: Session, chain: dict[str, str]
) -> None:
    session.add(_job())
    session.commit()
    job = session.get(Job, "job_1")
    assert job is not None
    # stage_detail 是给用户看的，必须是中文 —— 这条靠约定，但值得断言住
    assert job.stage_detail and any("\u4e00" <= ch <= "\u9fff" for ch in job.stage_detail)


def test_job_type_must_be_known(session: Session, chain: dict[str, str]) -> None:
    must_fail(session, _job(job_type="explode"))


def test_job_status_must_be_known(session: Session, chain: dict[str, str]) -> None:
    must_fail(session, _job(status="finished"))


@pytest.mark.parametrize("bad_progress", [-1, 101, 999])
def test_job_progress_range(session: Session, chain: dict[str, str], bad_progress: int) -> None:
    must_fail(session, _job(progress=bad_progress))


# ---------------------------------------------------------------------------
# llm_calls
# ---------------------------------------------------------------------------


def test_llm_call_valid_round_trips(session: Session, chain: dict[str, str]) -> None:
    session.add(
        LlmCall(
            id="call_1",
            caller="parse.image_to_md",
            prompt_version="P2@v1",
            provider="learnbuddy",
            model="platform",
            schema_valid=1,
            retry_count=0,
            created_at=utc_now_iso(),
        )
    )
    session.commit()
    assert session.get(LlmCall, "call_1") is not None


def test_llm_call_schema_valid_must_be_boolean(session: Session, chain: dict[str, str]) -> None:
    must_fail(
        session,
        LlmCall(
            id="call_1",
            caller="x",
            prompt_version="P1@v1",
            provider="p",
            model="m",
            schema_valid=7,
            retry_count=0,
            created_at=utc_now_iso(),
        ),
    )


def test_llm_call_retry_count_non_negative(session: Session, chain: dict[str, str]) -> None:
    must_fail(
        session,
        LlmCall(
            id="call_1",
            caller="x",
            prompt_version="P1@v1",
            provider="p",
            model="m",
            retry_count=-1,
            created_at=utc_now_iso(),
        ),
    )


# ---------------------------------------------------------------------------
# 级联删除
# ---------------------------------------------------------------------------


def test_deleting_kp_cascades_to_examples_and_embeddings(
    session: Session, chain: dict[str, str]
) -> None:
    session.add(
        KpExample(
            id="ex_1", kp_id="kp_a", question_type="short_answer", stem_md="题", answer_md="答"
        )
    )
    session.add(KpMisconception(id="mis_1", kp_id="kp_a", description="误区", source="human"))
    session.add(
        KpEmbedding(
            kp_id="kp_a",
            model="m",
            dim=1,
            vector=_f32(1.0),
            text_hash="h",
            created_at=utc_now_iso(),
        )
    )
    session.commit()

    session.delete(session.get(KnowledgePoint, "kp_a"))
    session.commit()

    assert session.get(KpExample, "ex_1") is None
    assert session.get(KpMisconception, "mis_1") is None
    assert session.get(KpEmbedding, "kp_a") is None


def test_deleting_qa_session_cascades_to_turns(session: Session, chain: dict[str, str]) -> None:
    session.add(
        QaSession(id="s_1", material_scope="[]", created_at=utc_now_iso(), updated_at=utc_now_iso())
    )
    session.add(
        QaTurn(
            id="t_1",
            session_id="s_1",
            seq=0,
            role="tutor",
            content_md="x",
            grounded=1,
            created_at=utc_now_iso(),
        )
    )
    session.commit()

    session.delete(session.get(QaSession, "s_1"))
    session.commit()
    assert session.get(QaTurn, "t_1") is None
