"""Tests for the Mock Interview v3 orchestrator + sub-agents.

Covers the five constraints called out in the spec:
  1. Adaptive difficulty — difficulty floats with rolling overall.
  2. Anti-sycophancy — Scorer flags would-not-pass on bad answers.
  3. Confidence threshold — low Scorer confidence → needs_human_review surfaced.
  4. Cost cap — circuit breaker fires when total_cost_inr exceeds ₹40.
  5. Memory — prior weaknesses surface on the next session's greeting.

The tests stub every LLM via patching `MockSubAgent.invoke` so we don't hit
the network. The orchestrator itself is exercised end-to-end against an
in-memory SQLite DB.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.interview_session import InterviewSession
from app.models.mock_interview import (
    MockAnswer,
    MockCostLog,
    MockQuestion,
    MockSessionReport,
    MockWeaknessLedger,
)
from app.models.user import User
from app.services import mock_interview_service as svc
from app.services import mock_memory_service as mem
from app.services.mock_pattern_detector import (
    aggregate_session_patterns,
    detect_answer_signals,
)
from app.services.mock_rubric_engine import rubric_for


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def user(db_session) -> User:
    u = User(
        email="cand@test.com",
        full_name="Cand Idate",
        hashed_password="x",
        role="student",
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


def _mock_response(usage_in: int = 100, usage_out: int = 60) -> Any:
    resp = MagicMock()
    resp.usage_metadata = {"input_tokens": usage_in, "output_tokens": usage_out}
    resp.content = "{}"
    resp.response_metadata = {}
    return resp


def _selector_payload(*, difficulty: float, text: str = "Walk me through that.") -> dict[str, Any]:
    return {
        "question": {
            "text": text,
            "difficulty": difficulty,
            "source": "generated",
            "mode": "behavioral",
            "rubric_hint": "STAR",
            "references_weakness": None,
        },
        "confidence": 0.8,
        "needs_human_review": False,
        "selection_reasoning": "test",
    }


def _scorer_payload(
    *,
    overall: float,
    confidence: float = 0.85,
    weakness_signals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rubric = rubric_for("behavioral", "junior")
    score = int(round(overall))
    return {
        "criteria": [
            {"name": item["name"], "score": score, "rationale": "test"}
            for item in rubric
        ],
        "overall": overall,
        "would_pass": overall >= 7.5,
        "confidence": confidence,
        "needs_human_review": confidence < 0.6,
        "feedback": (
            "I'd recommend a human review on this one. test"
            if confidence < 0.6
            else "test feedback citing 'specific phrase' from the answer."
        ),
        "follow_up_concept": None,
        "weakness_signals": weakness_signals or [],
    }


def _interviewer_payload(*, next_action: str = "move_on") -> dict[str, Any]:
    return {
        "reply": "Got it.",
        "next_action": next_action,
        "confidence": 0.7,
    }


def _analyst_payload(*, confidence: float = 0.8) -> dict[str, Any]:
    return {
        "headline": "Strong on structure; thin on result quantification.",
        "verdict": "would_pass" if confidence >= 0.6 else "needs_human_review",
        "rubric_summary": {"clarity": 7.0, "structure": 8.0},
        "strengths": ["You used STAR structure cleanly: 'I noticed...'"],
        "weaknesses": ["Result was qualitative — no number."],
        "next_action": {
            "label": "Drill STAR-Result",
            "detail": "Pick 3 stories and rewrite each Result with a number.",
            "target_url": "/career/interview-bank",
        },
        "patterns_commentary": "Filler-word rate within range.",
        "analyst_confidence": confidence,
        "needs_human_review": confidence < 0.6,
        "weakness_ledger_updates": [],
    }


# ---------------------------------------------------------------------------
# Pattern detector — pure unit
# ---------------------------------------------------------------------------


def test_pattern_detector_counts_fillers() -> None:
    text = "Um, I think basically I would, you know, sort of build the API."
    sig = detect_answer_signals(text)
    assert sig.word_count > 0
    assert sig.filler_word_count >= 4  # um, basically, you know, sort of
    assert sig.hedge_word_count >= 1


def test_pattern_detector_aggregate_confidence_score() -> None:
    """Hedge-heavy answer drops confidence_language_score."""
    high_hedge = detect_answer_signals(
        "I think maybe I would probably build it. I'm not sure but I guess so."
    )
    clean = detect_answer_signals(
        "I built the API in Python. It handled retries with exponential backoff."
    )
    high_patterns = aggregate_session_patterns(
        answer_signals=[high_hedge], time_to_first_word_samples=[]
    )
    clean_patterns = aggregate_session_patterns(
        answer_signals=[clean], time_to_first_word_samples=[]
    )
    assert clean_patterns.confidence_language_score > high_patterns.confidence_language_score


# ---------------------------------------------------------------------------
# Memory service — round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_records_and_surfaces(db_session, user) -> None:
    sid = uuid.uuid4()
    await mem.record_weakness_signals(
        db_session,
        user_id=user.id,
        session_id=sid,
        signals=[
            {"concept": "result_quantification", "severity": 0.7},
            {"concept": "ownership", "severity": 0.6},
        ],
    )
    open_w = await mem.get_open_weaknesses(db_session, user_id=user.id)
    assert {w.concept for w in open_w} == {"result_quantification", "ownership"}
    greeting = mem.memory_recall_greeting(open_w)
    assert greeting is not None
    assert "result_quantification" in greeting or "ownership" in greeting


@pytest.mark.asyncio
async def test_memory_blends_severity_on_recurrence(db_session, user) -> None:
    sid1, sid2 = uuid.uuid4(), uuid.uuid4()
    await mem.record_weakness_signals(
        db_session,
        user_id=user.id,
        session_id=sid1,
        signals=[{"concept": "edge_cases", "severity": 0.9}],
    )
    await mem.record_weakness_signals(
        db_session,
        user_id=user.id,
        session_id=sid2,
        signals=[{"concept": "edge_cases", "severity": 0.5}],
    )
    open_w = await mem.get_open_weaknesses(db_session, user_id=user.id)
    assert len(open_w) == 1
    # 0.6*0.9 + 0.4*0.5 = 0.74
    assert 0.7 < open_w[0].severity < 0.78
    assert len(open_w[0].evidence_session_ids or []) == 2


@pytest.mark.asyncio
async def test_memory_mark_addressed(db_session, user) -> None:
    await mem.record_weakness_signals(
        db_session,
        user_id=user.id,
        session_id=uuid.uuid4(),
        signals=[{"concept": "depth", "severity": 0.7}],
    )
    await mem.mark_addressed(db_session, user_id=user.id, concepts=["depth"])
    open_w = await mem.get_open_weaknesses(db_session, user_id=user.id)
    assert open_w == []


@pytest.mark.asyncio
async def test_memory_recall_silent_without_high_severity(db_session, user) -> None:
    await mem.record_weakness_signals(
        db_session,
        user_id=user.id,
        session_id=uuid.uuid4(),
        signals=[{"concept": "minor", "severity": 0.3}],
    )
    open_w = await mem.get_open_weaknesses(db_session, user_id=user.id)
    assert mem.memory_recall_greeting(open_w) is None


# ---------------------------------------------------------------------------
# Orchestrator — end-to-end with stubbed sub-agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_session_creates_session_and_question(db_session, user) -> None:
    with (
        patch.object(
            svc.MockQuestionSelector,
            "invoke",
            new=AsyncMock(return_value=(_selector_payload(difficulty=0.2), _mock_response())),
        ),
        patch.object(svc, "get_student_skill_map", new=AsyncMock(return_value={"python": 0.7})),
        patch.object(svc, "get_exercise_count", new=AsyncMock(return_value=5)),
    ):
        result = await svc.start_session(
            db_session,
            user_id=user.id,
            mode="behavioral",
            target_role="Junior Python Dev",
            level="junior",
            jd_text=None,
            voice_enabled=False,
        )
    assert result.session.id is not None
    assert result.first_question.position == 1
    assert result.first_question.difficulty == 0.2
    cost_logs = (
        await db_session.execute(select(MockCostLog).where(MockCostLog.session_id == result.session.id))
    ).scalars().all()
    assert len(cost_logs) == 1


@pytest.mark.asyncio
async def test_memory_surfaces_in_next_session_greeting(db_session, user) -> None:
    """After a session that records a weakness, the next session greets with it."""
    await mem.record_weakness_signals(
        db_session,
        user_id=user.id,
        session_id=uuid.uuid4(),
        signals=[{"concept": "result_quantification", "severity": 0.75}],
    )
    with (
        patch.object(
            svc.MockQuestionSelector,
            "invoke",
            new=AsyncMock(return_value=(_selector_payload(difficulty=0.3), _mock_response())),
        ),
        patch.object(svc, "get_student_skill_map", new=AsyncMock(return_value={})),
        patch.object(svc, "get_exercise_count", new=AsyncMock(return_value=0)),
    ):
        result = await svc.start_session(
            db_session,
            user_id=user.id,
            mode="behavioral",
            target_role="Senior",
            level="senior",
            jd_text=None,
            voice_enabled=True,
        )
    assert result.memory_recall is not None
    assert "result_quantification" in result.memory_recall or "result quantification" in result.memory_recall


@pytest.mark.asyncio
async def test_adaptive_difficulty_scales_with_rolling_overall(db_session, user) -> None:
    """Two strong answers → next QuestionSelector call gets rolling_overall ≥ 7."""
    selector_calls: list[dict[str, Any]] = []

    async def selector_invoke(self, **kwargs):  # noqa: ANN001 - duck-typed stub
        selector_calls.append(kwargs)
        difficulty = 0.2 if kwargs.get("is_warmup") else 0.8
        return _selector_payload(difficulty=difficulty), _mock_response()

    with (
        patch.object(svc.MockQuestionSelector, "invoke", selector_invoke),
        patch.object(
            svc.MockScorer,
            "invoke",
            new=AsyncMock(return_value=(_scorer_payload(overall=8.5), _mock_response())),
        ),
        patch.object(
            svc.MockInterviewer,
            "invoke",
            new=AsyncMock(return_value=(_interviewer_payload(next_action="move_on"), _mock_response())),
        ),
        patch.object(svc, "get_student_skill_map", new=AsyncMock(return_value={"python": 0.9})),
        patch.object(svc, "get_exercise_count", new=AsyncMock(return_value=12)),
    ):
        result = await svc.start_session(
            db_session,
            user_id=user.id,
            mode="behavioral",
            target_role="Mid",
            level="mid",
            jd_text=None,
            voice_enabled=False,
        )
        # First answer
        ans1 = await svc.submit_answer(
            db_session,
            session=result.session,
            question_id=result.first_question.id,
            text="I built a payment processor that reduced p99 latency by 40%.",
            audio_ref=None,
            latency_ms=2000,
            time_to_first_word_ms=400,
        )
        assert ans1.next_question is not None
        # Second answer on the new question
        ans2 = await svc.submit_answer(
            db_session,
            session=result.session,
            question_id=ans1.next_question.id,
            text="I designed a multi-region failover that cut MTTR from 2h to 8 minutes.",
            audio_ref=None,
            latency_ms=2500,
            time_to_first_word_ms=300,
        )
        assert ans2.next_question is not None

    # The selector calls 1, 2, and 3 — index 2 is the 3rd (post-second-strong-answer).
    # By that point rolling_overall should be ≥ 7.
    third_call = selector_calls[2]
    assert third_call["rolling_overall"] is not None
    assert third_call["rolling_overall"] >= 7.0
    assert third_call["is_warmup"] is False


@pytest.mark.asyncio
async def test_confidence_threshold_marks_human_review(db_session, user) -> None:
    """Scorer confidence < 0.6 → API marks needs_human_review and prepends review preface."""
    with (
        patch.object(
            svc.MockQuestionSelector,
            "invoke",
            new=AsyncMock(return_value=(_selector_payload(difficulty=0.3), _mock_response())),
        ),
        patch.object(
            svc.MockScorer,
            "invoke",
            new=AsyncMock(
                return_value=(
                    _scorer_payload(overall=4.0, confidence=0.4),
                    _mock_response(),
                )
            ),
        ),
        patch.object(
            svc.MockInterviewer,
            "invoke",
            new=AsyncMock(return_value=(_interviewer_payload(next_action="move_on"), _mock_response())),
        ),
        patch.object(svc, "get_student_skill_map", new=AsyncMock(return_value={})),
        patch.object(svc, "get_exercise_count", new=AsyncMock(return_value=0)),
    ):
        result = await svc.start_session(
            db_session,
            user_id=user.id,
            mode="behavioral",
            target_role="Junior",
            level="junior",
            jd_text=None,
            voice_enabled=False,
        )
        ans = await svc.submit_answer(
            db_session,
            session=result.session,
            question_id=result.first_question.id,
            text="Stuff.",
            audio_ref=None,
            latency_ms=500,
            time_to_first_word_ms=200,
        )
    assert ans.evaluation["needs_human_review"] is True
    assert ans.evaluation["feedback"].startswith("I'd recommend a human review")


@pytest.mark.asyncio
async def test_cost_cap_circuit_breaker(db_session, user, monkeypatch) -> None:
    """When total_cost_inr exceeds ₹40 mid-session, the orchestrator stops picking new questions."""

    async def fat_response_invoke(self, **kwargs):  # noqa: ANN001
        # Return a usage payload that explodes cost on each call.
        resp = MagicMock()
        # 5_000_000 input tokens × Sonnet rate → ₹1260+ per call easily over cap
        resp.usage_metadata = {"input_tokens": 5_000_000, "output_tokens": 1_000_000}
        resp.content = "{}"
        resp.response_metadata = {}
        return _selector_payload(difficulty=0.3), resp

    async def normal_scorer(self, **kwargs):  # noqa: ANN001
        return _scorer_payload(overall=7.0), _mock_response()

    async def normal_interviewer(self, **kwargs):  # noqa: ANN001
        return _interviewer_payload(next_action="move_on"), _mock_response()

    with (
        patch.object(svc.MockQuestionSelector, "invoke", fat_response_invoke),
        patch.object(svc.MockScorer, "invoke", normal_scorer),
        patch.object(svc.MockInterviewer, "invoke", normal_interviewer),
        patch.object(svc, "get_student_skill_map", new=AsyncMock(return_value={})),
        patch.object(svc, "get_exercise_count", new=AsyncMock(return_value=0)),
    ):
        result = await svc.start_session(
            db_session,
            user_id=user.id,
            mode="behavioral",
            target_role="Junior",
            level="junior",
            jd_text=None,
            voice_enabled=False,
        )
        # First answer should trigger cost-cap because the *initial* selector call
        # already burned past ₹40, and the next selector call would push further.
        ans = await svc.submit_answer(
            db_session,
            session=result.session,
            question_id=result.first_question.id,
            text="A concrete answer with numbers.",
            audio_ref=None,
            latency_ms=2000,
            time_to_first_word_ms=400,
        )
    assert ans.cost_cap_exceeded is True
    assert ans.next_question is None
    assert ans.cost_inr_so_far > svc.COST_CAP_INR


@pytest.mark.asyncio
async def test_anti_sycophancy_bad_answer_flags_would_not_pass(db_session, user) -> None:
    """Feed a deliberately bad answer; assert would_pass is false and feedback is direct."""
    with (
        patch.object(
            svc.MockQuestionSelector,
            "invoke",
            new=AsyncMock(return_value=(_selector_payload(difficulty=0.3), _mock_response())),
        ),
        patch.object(
            svc.MockScorer,
            "invoke",
            new=AsyncMock(
                return_value=(
                    _scorer_payload(overall=3.5, confidence=0.8),
                    _mock_response(),
                )
            ),
        ),
        patch.object(
            svc.MockInterviewer,
            "invoke",
            new=AsyncMock(return_value=(_interviewer_payload(next_action="move_on"), _mock_response())),
        ),
        patch.object(svc, "get_student_skill_map", new=AsyncMock(return_value={})),
        patch.object(svc, "get_exercise_count", new=AsyncMock(return_value=0)),
    ):
        result = await svc.start_session(
            db_session,
            user_id=user.id,
            mode="behavioral",
            target_role="Junior",
            level="junior",
            jd_text=None,
            voice_enabled=False,
        )
        ans = await svc.submit_answer(
            db_session,
            session=result.session,
            question_id=result.first_question.id,
            text="we did some stuff and it was great",
            audio_ref=None,
            latency_ms=1000,
            time_to_first_word_ms=300,
        )
    assert ans.evaluation["would_pass"] is False
    assert ans.evaluation["overall"] < 5.5
    # Anti-sycophancy: forbidden phrase NOT in feedback
    feedback_lower = ans.evaluation.get("feedback", "").lower()
    assert "great answer" not in feedback_lower
    assert "excellent point" not in feedback_lower


@pytest.mark.asyncio
async def test_complete_session_writes_report_and_addresses_weaknesses(
    db_session, user
) -> None:
    """End-to-end completion writes a report and addresses any concept the analyst flagged."""
    # Pre-seed a weakness so the analyst can address it.
    await mem.record_weakness_signals(
        db_session,
        user_id=user.id,
        session_id=uuid.uuid4(),
        signals=[{"concept": "ownership", "severity": 0.7}],
    )

    analyst_payload = _analyst_payload(confidence=0.85)
    analyst_payload["weakness_ledger_updates"] = [
        {"concept": "ownership", "severity": 0.3, "addressed": True}
    ]

    with (
        patch.object(
            svc.MockQuestionSelector,
            "invoke",
            new=AsyncMock(return_value=(_selector_payload(difficulty=0.3), _mock_response())),
        ),
        patch.object(
            svc.MockScorer,
            "invoke",
            new=AsyncMock(return_value=(_scorer_payload(overall=8.0), _mock_response())),
        ),
        patch.object(
            svc.MockInterviewer,
            "invoke",
            new=AsyncMock(return_value=(_interviewer_payload(), _mock_response())),
        ),
        patch.object(
            svc.MockAnalyst,
            "invoke",
            new=AsyncMock(return_value=(analyst_payload, _mock_response())),
        ),
        patch.object(svc, "get_student_skill_map", new=AsyncMock(return_value={})),
        patch.object(svc, "get_exercise_count", new=AsyncMock(return_value=0)),
    ):
        result = await svc.start_session(
            db_session,
            user_id=user.id,
            mode="behavioral",
            target_role="Junior",
            level="junior",
            jd_text=None,
            voice_enabled=False,
        )
        await svc.submit_answer(
            db_session,
            session=result.session,
            question_id=result.first_question.id,
            text="I led the migration; here's the result with numbers.",
            audio_ref=None,
            latency_ms=2000,
            time_to_first_word_ms=400,
        )
        complete = await svc.complete_session(db_session, session=result.session)

    assert complete.session.status == "completed"
    assert complete.report.headline is not None
    assert complete.session.overall_score is not None
    assert complete.session.overall_score >= 7.0

    # The ownership weakness should be marked addressed.
    open_w = await mem.get_open_weaknesses(db_session, user_id=user.id)
    assert "ownership" not in {w.concept for w in open_w}


@pytest.mark.asyncio
async def test_analyst_low_confidence_marks_report_for_review(db_session, user) -> None:
    """Analyst confidence < 0.6 → report.verdict is needs_human_review."""
    with (
        patch.object(
            svc.MockQuestionSelector,
            "invoke",
            new=AsyncMock(return_value=(_selector_payload(difficulty=0.3), _mock_response())),
        ),
        patch.object(
            svc.MockScorer,
            "invoke",
            new=AsyncMock(return_value=(_scorer_payload(overall=5.0, confidence=0.7), _mock_response())),
        ),
        patch.object(
            svc.MockInterviewer,
            "invoke",
            new=AsyncMock(return_value=(_interviewer_payload(), _mock_response())),
        ),
        patch.object(
            svc.MockAnalyst,
            "invoke",
            new=AsyncMock(return_value=(_analyst_payload(confidence=0.4), _mock_response())),
        ),
        patch.object(svc, "get_student_skill_map", new=AsyncMock(return_value={})),
        patch.object(svc, "get_exercise_count", new=AsyncMock(return_value=0)),
    ):
        result = await svc.start_session(
            db_session,
            user_id=user.id,
            mode="behavioral",
            target_role="Junior",
            level="junior",
            jd_text=None,
            voice_enabled=False,
        )
        await svc.submit_answer(
            db_session,
            session=result.session,
            question_id=result.first_question.id,
            text="Some answer.",
            audio_ref=None,
            latency_ms=2000,
            time_to_first_word_ms=400,
        )
        complete = await svc.complete_session(db_session, session=result.session)

    assert complete.report.verdict == "needs_human_review"
    assert complete.report.analyst_confidence < 0.6


@pytest.mark.asyncio
async def test_system_design_mode_is_phase_2_stub(db_session, user) -> None:
    with pytest.raises(ValueError, match="Phase 2"):
        await svc.start_session(
            db_session,
            user_id=user.id,
            mode="system_design",
            target_role="Staff",
            level="senior",
            jd_text=None,
            voice_enabled=False,
        )


# ---------------------------------------------------------------------------
# Anti-sycophancy: prompt-level guardrail
# ---------------------------------------------------------------------------


def test_scorer_prompt_explicitly_forbids_flattery() -> None:
    """The Scorer prompt must contain the anti-sycophancy clause — it's the
    single most important guardrail in this feature."""
    from app.agents.mock_sub_agents import _SCORER_PROMPT

    lowered = _SCORER_PROMPT.lower()
    assert "great answer" in lowered  # listed as forbidden phrase
    assert "anti-sycophancy" in lowered or "sycophancy" in lowered
    assert "would not pass" in lowered


def test_interviewer_prompt_forbids_flattery_phrases() -> None:
    from app.agents.mock_sub_agents import _INTERVIEWER_PROMPT

    lowered = _INTERVIEWER_PROMPT.lower()
    assert "great answer" in lowered
    assert "forbidden" in lowered


def test_analyst_prompt_requires_strengths_with_evidence() -> None:
    from app.agents.mock_sub_agents import _ANALYST_PROMPT

    lowered = _ANALYST_PROMPT.lower()
    assert "strength" in lowered
    assert "no leaderboards" in lowered or "no leaderboard" in lowered
    assert "would_not_pass" in lowered


def test_selector_prompt_documents_adaptive_rule() -> None:
    from app.agents.mock_sub_agents import _QUESTION_SELECTOR_PROMPT

    lowered = _QUESTION_SELECTOR_PROMPT.lower()
    assert "adaptation" in lowered or "adaptive" in lowered
    assert "rolling overall" in lowered or "rolling" in lowered
