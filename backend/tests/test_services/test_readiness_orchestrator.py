"""Diagnostic orchestrator tests.

LLM calls are stubbed so tests assert orchestration only — turn cap
enforcement, transcript persistence, JD-trigger capture, cost-cap
circuit-breaker, snapshot reuse, and abandon flow.

Coverage:

  1. start_session_persists_opening_turn — opening message lands as a
     turn row with role='agent' and metadata.
  2. snapshot_reused_across_turns — submit_turn re-fetches the same
     snapshot row by id (no duplicate snapshot rows per session).
  3. invoke_jd_decoder_token_propagates — when the interviewer emits
     invoke_jd_decoder=true, the orchestrator surfaces it on the
     TurnResult AND persists the excerpt on the agent turn's metadata.
  4. soft_cap_forces_finalize_at_max_turns — even if the interviewer
     never emits ready_for_verdict, the orchestrator flips the session
     to finalizing when the agent's turn count hits MAX_TURNS.
  5. ready_for_verdict_flips_status — interviewer's own
     ready_for_verdict signal moves the session to finalizing.
  6. cost_cap_raises_and_finalizes — high-cost stub pushes accumulated
     cost over the cap; orchestrator raises CostCapExceededError and
     leaves the session in 'finalizing' state.
  7. abandon_session_flips_status — abandon endpoint flips active or
     finalizing sessions to abandoned.
  8. submit_turn_on_closed_session_raises — calling submit_turn on a
     completed/abandoned session raises SessionAlreadyClosedError.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_invocation_log import (
    SOURCE_DIAGNOSTIC,
    AgentInvocationLog,
)
from app.models.readiness import (
    DIAGNOSTIC_STATUS_ABANDONED,
    DIAGNOSTIC_STATUS_FINALIZING,
    MAX_TURNS,
    ReadinessDiagnosticSession,
    ReadinessDiagnosticTurn,
    ReadinessStudentSnapshot,
)
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_regenerate_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot building transitively calls regenerate_resume which makes
    a live LLM call. Replace with a no-op."""
    from app.services import career_service
    from app.services import profile_aggregator as pa

    async def fake_regen(db, *, user_id, force: bool = False):
        return await career_service.get_or_create_resume(db, user_id=user_id)

    monkeypatch.setattr(career_service, "regenerate_resume", fake_regen)
    monkeypatch.setattr(pa, "regenerate_resume", fake_regen)


@pytest.fixture
def stub_interviewer(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stubs DiagnosticInterviewer.run with a configurable response.

    The fixture returns a dict with a ``next_response`` callable: tests
    set it per-call to control what the stub returns.
    """
    from app.agents import readiness_sub_agents
    from app.agents.readiness_sub_agents import SubAgentResult

    state: dict[str, Any] = {
        "calls": 0,
        "tokens_in": 200,
        "tokens_out": 80,
    }

    def default_response(turn_number: int) -> dict[str, Any]:
        return {
            "reply": f"Agent turn {turn_number}.",
            "ready_for_verdict": False,
            "invoke_jd_decoder": False,
            "jd_text_excerpt": "",
        }

    state["next_response"] = default_response

    async def fake_run(
        self,
        *,
        snapshot_summary,
        prior_session_hint,
        transcript,
        student_message,
        turn_number,
    ):
        state["calls"] += 1
        parsed = state["next_response"](turn_number)
        return SubAgentResult(
            parsed=parsed,
            raw_text="{}",
            model="claude-haiku-4-5",
            tokens_in=int(state["tokens_in"]),
            tokens_out=int(state["tokens_out"]),
            latency_ms=900,
            succeeded=True,
        )

    monkeypatch.setattr(
        readiness_sub_agents.DiagnosticInterviewer, "run", fake_run
    )
    return state


async def _make_user(db: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"{uuid.uuid4()}@test.local",
        full_name="Diagnostic Tester",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_session_persists_opening_turn(
    db_session: AsyncSession, stub_interviewer: dict[str, Any]
) -> None:
    from app.services.readiness_orchestrator import start_session

    user_id = await _make_user(db_session)
    result = await start_session(db_session, user_id=user_id)

    assert result.session_id is not None
    assert result.opening_message.startswith("Agent turn 1")

    turns = (
        await db_session.execute(
            select(ReadinessDiagnosticTurn).where(
                ReadinessDiagnosticTurn.session_id == result.session_id
            )
        )
    ).scalars().all()
    assert len(turns) == 1
    assert turns[0].role == "agent"
    assert turns[0].metadata_json["turn_number"] == 1


@pytest.mark.asyncio
async def test_snapshot_reused_across_turns(
    db_session: AsyncSession, stub_interviewer: dict[str, Any]
) -> None:
    """submit_turn must re-use the snapshot row created at session start
    rather than building a new one each turn."""
    from app.services.readiness_orchestrator import start_session, submit_turn

    user_id = await _make_user(db_session)
    started = await start_session(db_session, user_id=user_id)
    await submit_turn(
        db_session,
        user_id=user_id,
        session_id=started.session_id,
        student_message="I'm stuck on system design.",
    )
    await submit_turn(
        db_session,
        user_id=user_id,
        session_id=started.session_id,
        student_message="Specifically the scaling parts.",
    )

    snapshot_rows = (
        await db_session.execute(
            select(ReadinessStudentSnapshot).where(
                ReadinessStudentSnapshot.user_id == user_id
            )
        )
    ).scalars().all()
    assert len(snapshot_rows) == 1, (
        "submit_turn rebuilt the snapshot — it must reuse the row "
        "linked to the session."
    )


@pytest.mark.asyncio
async def test_invoke_jd_decoder_token_propagates(
    db_session: AsyncSession, stub_interviewer: dict[str, Any]
) -> None:
    from app.services.readiness_orchestrator import start_session, submit_turn

    user_id = await _make_user(db_session)
    started = await start_session(db_session, user_id=user_id)

    stub_interviewer["next_response"] = lambda turn_number: {
        "reply": "Paste the JD when you're ready.",
        "ready_for_verdict": False,
        "invoke_jd_decoder": True,
        "jd_text_excerpt": "Junior Data Analyst at Acme",
    }

    result = await submit_turn(
        db_session,
        user_id=user_id,
        session_id=started.session_id,
        student_message="I'm looking at a Junior Data Analyst role at Acme.",
    )
    assert result.invoke_jd_decoder is True
    assert "Acme" in result.jd_text_excerpt

    # Persisted on the agent turn's metadata too.
    turns = (
        await db_session.execute(
            select(ReadinessDiagnosticTurn)
            .where(
                ReadinessDiagnosticTurn.session_id == started.session_id,
                ReadinessDiagnosticTurn.role == "agent",
            )
            .order_by(ReadinessDiagnosticTurn.created_at)
        )
    ).scalars().all()
    last_agent_turn = turns[-1]
    assert last_agent_turn.metadata_json["invoke_jd_decoder"] is True
    assert "Acme" in last_agent_turn.metadata_json["jd_text_excerpt"]


@pytest.mark.asyncio
async def test_soft_cap_forces_finalize_at_max_turns(
    db_session: AsyncSession, stub_interviewer: dict[str, Any]
) -> None:
    """When the interviewer never decides to wrap, the orchestrator
    forces ready_for_verdict on the MAX_TURNS-th agent turn."""
    from app.services.readiness_orchestrator import start_session, submit_turn

    user_id = await _make_user(db_session)
    # Stub never emits ready_for_verdict; orchestrator must force.
    stub_interviewer["next_response"] = lambda turn_number: {
        "reply": f"Turn {turn_number}.",
        "ready_for_verdict": False,
        "invoke_jd_decoder": False,
        "jd_text_excerpt": "",
    }

    started = await start_session(db_session, user_id=user_id)
    last: Any = None
    # Already had 1 agent turn from start_session; submit MAX_TURNS-1
    # student turns to drive the agent up to MAX_TURNS.
    for i in range(MAX_TURNS - 1):
        last = await submit_turn(
            db_session,
            user_id=user_id,
            session_id=started.session_id,
            student_message=f"Student turn {i + 1}.",
        )

    assert last is not None
    assert last.is_final is True

    session = (
        await db_session.execute(
            select(ReadinessDiagnosticSession).where(
                ReadinessDiagnosticSession.id == started.session_id
            )
        )
    ).scalar_one()
    assert session.status == DIAGNOSTIC_STATUS_FINALIZING


@pytest.mark.asyncio
async def test_ready_for_verdict_flips_status(
    db_session: AsyncSession, stub_interviewer: dict[str, Any]
) -> None:
    from app.services.readiness_orchestrator import start_session, submit_turn

    user_id = await _make_user(db_session)
    started = await start_session(db_session, user_id=user_id)

    # Next turn the interviewer signals ready_for_verdict.
    stub_interviewer["next_response"] = lambda turn_number: {
        "reply": "Got it — let me pull this together.",
        "ready_for_verdict": True,
        "invoke_jd_decoder": False,
        "jd_text_excerpt": "",
    }
    result = await submit_turn(
        db_session,
        user_id=user_id,
        session_id=started.session_id,
        student_message="Just tell me where I stand.",
    )
    assert result.is_final is True

    session = (
        await db_session.execute(
            select(ReadinessDiagnosticSession).where(
                ReadinessDiagnosticSession.id == started.session_id
            )
        )
    ).scalar_one()
    assert session.status == DIAGNOSTIC_STATUS_FINALIZING


@pytest.mark.asyncio
async def test_cost_cap_raises_and_finalizes(
    db_session: AsyncSession, stub_interviewer: dict[str, Any]
) -> None:
    """A pathological high-cost stub trips the cap; the orchestrator
    raises CostCapExceededError and force-finalizes the session."""
    from app.services.readiness_orchestrator import (
        COST_CAP_INR,
        CostCapExceededError,
        start_session,
    )

    user_id = await _make_user(db_session)
    # Inflate the per-call cost so even one extra turn busts the ₹15 cap.
    # Haiku pricing is ~$0.80/1M input, $4/1M output → set huge token
    # counts.
    stub_interviewer["tokens_in"] = 5_000_000
    stub_interviewer["tokens_out"] = 5_000_000

    # The cap protection trips on the very first invocation since the
    # stub's pathological token counts blow past the ₹15 cap in one
    # call. start_session raises and leaves the session row in
    # 'finalizing' — see _enforce_cost_cap.
    with pytest.raises(CostCapExceededError):
        await start_session(db_session, user_id=user_id)

    # The session row was created before the cap-trip and should now
    # be 'finalizing' (force-flipped by the cap check).
    sessions = (
        await db_session.execute(
            select(ReadinessDiagnosticSession).where(
                ReadinessDiagnosticSession.user_id == user_id
            )
        )
    ).scalars().all()
    assert len(sessions) == 1
    assert sessions[0].status == DIAGNOSTIC_STATUS_FINALIZING

    # A cap_exceeded marker row was logged.
    rows = (
        await db_session.execute(
            select(AgentInvocationLog).where(
                AgentInvocationLog.source == SOURCE_DIAGNOSTIC,
                AgentInvocationLog.status == "cap_exceeded",
            )
        )
    ).scalars().all()
    assert len(rows) >= 1
    assert COST_CAP_INR == 15.0  # invariant; if you change it, update tests


@pytest.mark.asyncio
async def test_abandon_session_flips_status(
    db_session: AsyncSession, stub_interviewer: dict[str, Any]
) -> None:
    from app.services.readiness_orchestrator import (
        abandon_session,
        start_session,
    )

    user_id = await _make_user(db_session)
    started = await start_session(db_session, user_id=user_id)
    await abandon_session(
        db_session, user_id=user_id, session_id=started.session_id
    )
    session = (
        await db_session.execute(
            select(ReadinessDiagnosticSession).where(
                ReadinessDiagnosticSession.id == started.session_id
            )
        )
    ).scalar_one()
    assert session.status == DIAGNOSTIC_STATUS_ABANDONED


@pytest.mark.asyncio
async def test_submit_turn_on_closed_session_raises(
    db_session: AsyncSession, stub_interviewer: dict[str, Any]
) -> None:
    from app.services.readiness_orchestrator import (
        SessionAlreadyClosedError,
        abandon_session,
        start_session,
        submit_turn,
    )

    user_id = await _make_user(db_session)
    started = await start_session(db_session, user_id=user_id)
    await abandon_session(
        db_session, user_id=user_id, session_id=started.session_id
    )
    with pytest.raises(SessionAlreadyClosedError):
        await submit_turn(
            db_session,
            user_id=user_id,
            session_id=started.session_id,
            student_message="too late",
        )


# ---------------------------------------------------------------------------
# Finalize flow (commit 7)
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_verdict(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stubs VerdictGenerator.run with a configurable response."""
    from app.agents import readiness_sub_agents
    from app.agents.readiness_sub_agents import SubAgentResult

    state: dict[str, Any] = {"calls": 0}

    def default_response() -> dict[str, Any]:
        return {
            "headline": "System design is the gap; the rest is in shape.",
            "evidence": [
                {
                    "text": "Strong on fundamentals",
                    "evidence_id": "lessons_completed",
                    "kind": "strength",
                },
                {
                    "text": "No system design exposure yet",
                    "evidence_id": "weakness:system_design",
                    "kind": "gap",
                },
            ],
            "next_action": {
                "intent": "skills_gap",
                "label": "Open the system design lesson",
            },
        }

    state["next_response"] = default_response

    async def fake_run(
        self,
        *,
        snapshot_summary,
        evidence_allowlist,
        transcript,
        prior_verdict_summaries,
        jd_match_score,
    ):
        state["calls"] += 1
        # Coerce evidence_id values to actually be in the allowlist for
        # the most common test path. Tests that want validation
        # failures override next_response directly.
        parsed = state["next_response"]()
        return SubAgentResult(
            parsed=parsed,
            raw_text="{}",
            model="claude-sonnet-4-6",
            tokens_in=600,
            tokens_out=200,
            latency_ms=1800,
            succeeded=True,
        )

    monkeypatch.setattr(
        readiness_sub_agents.VerdictGenerator, "run", fake_run
    )
    return state


@pytest.mark.asyncio
async def test_finalize_session_persists_verdict_and_flips_status(
    db_session: AsyncSession,
    stub_interviewer: dict[str, Any],
    stub_verdict: dict[str, Any],
) -> None:
    from app.models.readiness import (
        DIAGNOSTIC_STATUS_COMPLETED,
        ReadinessVerdict,
    )
    from app.services.readiness_orchestrator import (
        finalize_session,
        start_session,
    )

    user_id = await _make_user(db_session)
    started = await start_session(db_session, user_id=user_id)
    result = await finalize_session(
        db_session, user_id=user_id, session_id=started.session_id
    )

    assert result.verdict.headline.startswith("System design")
    assert result.verdict.next_action_intent == "skills_gap"
    assert result.verdict.next_action_route == "/courses"
    assert result.verdict.next_action_label == "Open the system design lesson"

    # Session flipped to completed and links the verdict.
    session = (
        await db_session.execute(
            select(ReadinessDiagnosticSession).where(
                ReadinessDiagnosticSession.id == started.session_id
            )
        )
    ).scalar_one()
    assert session.status == DIAGNOSTIC_STATUS_COMPLETED
    assert session.completed_at is not None
    assert session.verdict_id == result.verdict_id

    # Verdict row exists, evidence persisted.
    verdict = (
        await db_session.execute(
            select(ReadinessVerdict).where(
                ReadinessVerdict.id == result.verdict_id
            )
        )
    ).scalar_one()
    assert len(verdict.evidence) == 2
    assert any(c.get("kind") == "gap" for c in verdict.evidence)


@pytest.mark.asyncio
async def test_finalize_validation_failure_triggers_retry(
    db_session: AsyncSession,
    stub_interviewer: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First verdict cites an out-of-allowlist evidence_id; second
    cites a real one. The second is what gets persisted."""
    from app.agents import readiness_sub_agents
    from app.agents.readiness_sub_agents import SubAgentResult
    from app.services.readiness_orchestrator import (
        finalize_session,
        start_session,
    )

    attempts = {"n": 0}

    async def flaky_run(
        self,
        *,
        snapshot_summary,
        evidence_allowlist,
        transcript,
        prior_verdict_summaries,
        jd_match_score,
    ):
        attempts["n"] += 1
        evidence_id = (
            "fabricated_signal"
            if attempts["n"] == 1
            else next(iter(evidence_allowlist))
        )
        return SubAgentResult(
            parsed={
                "headline": f"Verdict attempt {attempts['n']}.",
                "evidence": [
                    {
                        "text": "Some claim",
                        "evidence_id": evidence_id,
                        "kind": "strength",
                    }
                ],
                "next_action": {
                    "intent": "skills_gap",
                    "label": "Open the lesson",
                },
            },
            raw_text="{}",
            model="claude-sonnet-4-6",
            tokens_in=500,
            tokens_out=180,
            latency_ms=1400,
            succeeded=True,
        )

    monkeypatch.setattr(
        readiness_sub_agents.VerdictGenerator, "run", flaky_run
    )

    user_id = await _make_user(db_session)
    started = await start_session(db_session, user_id=user_id)
    result = await finalize_session(
        db_session, user_id=user_id, session_id=started.session_id
    )
    assert attempts["n"] == 2
    assert result.verdict.headline == "Verdict attempt 2."


@pytest.mark.asyncio
async def test_finalize_writes_sycophancy_flags_when_present(
    db_session: AsyncSession,
    stub_interviewer: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sycophantic verdict makes it through (warning-only per spec)
    but the flags are persisted for later audit / promotion."""
    from app.agents import readiness_sub_agents
    from app.agents.readiness_sub_agents import SubAgentResult
    from app.models.readiness import ReadinessVerdict
    from app.services.readiness_orchestrator import (
        finalize_session,
        start_session,
    )

    async def sycophantic_run(
        self,
        *,
        snapshot_summary,
        evidence_allowlist,
        transcript,
        prior_verdict_summaries,
        jd_match_score,
    ):
        return SubAgentResult(
            parsed={
                "headline": "Keep up the great work — you're on the right track!",
                "evidence": [
                    {
                        "text": "Amazing progress",
                        "evidence_id": next(iter(evidence_allowlist)),
                        "kind": "strength",
                    }
                ],
                "next_action": {
                    "intent": "skills_gap",
                    "label": "Open the next lesson",
                },
            },
            raw_text="{}",
            model="claude-sonnet-4-6",
            tokens_in=500,
            tokens_out=180,
            latency_ms=1400,
            succeeded=True,
        )

    monkeypatch.setattr(
        readiness_sub_agents.VerdictGenerator, "run", sycophantic_run
    )

    user_id = await _make_user(db_session)
    started = await start_session(db_session, user_id=user_id)
    result = await finalize_session(
        db_session, user_id=user_id, session_id=started.session_id
    )

    # Verdict shipped (warning, not blocking) but flags surfaced.
    assert "keep up the" in result.verdict.sycophancy_flags
    assert "amazing progress" in result.verdict.sycophancy_flags

    # Flags persisted on the row too.
    verdict = (
        await db_session.execute(
            select(ReadinessVerdict).where(
                ReadinessVerdict.id == result.verdict_id
            )
        )
    ).scalar_one()
    assert verdict.sycophancy_flags is not None
    assert len(verdict.sycophancy_flags) >= 1


@pytest.mark.asyncio
async def test_finalize_closing_note_lands_in_transcript(
    db_session: AsyncSession,
    stub_interviewer: dict[str, Any],
    stub_verdict: dict[str, Any],
) -> None:
    """An optional closing_note becomes a final student turn so the
    verdict generator sees it."""
    from app.services.readiness_orchestrator import (
        finalize_session,
        start_session,
    )

    user_id = await _make_user(db_session)
    started = await start_session(db_session, user_id=user_id)
    await finalize_session(
        db_session,
        user_id=user_id,
        session_id=started.session_id,
        closing_note="One last thing — I'm interviewing in 3 weeks.",
    )

    turns = (
        await db_session.execute(
            select(ReadinessDiagnosticTurn)
            .where(
                ReadinessDiagnosticTurn.session_id == started.session_id,
                ReadinessDiagnosticTurn.role == "student",
            )
            .order_by(ReadinessDiagnosticTurn.created_at)
        )
    ).scalars().all()
    assert any("3 weeks" in t.content for t in turns)


@pytest.mark.asyncio
async def test_finalize_on_completed_session_raises(
    db_session: AsyncSession,
    stub_interviewer: dict[str, Any],
    stub_verdict: dict[str, Any],
) -> None:
    from app.services.readiness_orchestrator import (
        SessionAlreadyClosedError,
        finalize_session,
        start_session,
    )

    user_id = await _make_user(db_session)
    started = await start_session(db_session, user_id=user_id)
    await finalize_session(
        db_session, user_id=user_id, session_id=started.session_id
    )
    with pytest.raises(SessionAlreadyClosedError):
        await finalize_session(
            db_session, user_id=user_id, session_id=started.session_id
        )
