"""Diagnostic session orchestrator.

Manages the lifecycle of one ``ReadinessDiagnosticSession``:

  start_session
    ├── build StudentSnapshot (TTL-cached)
    ├── load prior_session_hint via readiness_memory_service
    ├── persist ReadinessDiagnosticSession (status=active)
    ├── run DiagnosticInterviewer with turn 1 context
    ├── persist agent's opening turn
    └── return opening message + snapshot summary

  submit_turn
    ├── persist student turn
    ├── enforce turn cap (≤ MAX_TURNS) — soft: if already at cap,
    │   short-circuit with a wrap-up reply and ready_for_verdict=true
    ├── enforce session cost cap (₹15)
    ├── run DiagnosticInterviewer
    ├── persist agent turn
    ├── on invoke_jd_decoder=true, surface that signal back to the
    │   route (decoder invocation lives in commit 9; here we only
    │   record the intent)
    └── return agent reply + ready_for_verdict + invoke_jd_decoder

  finalize_session
    ├── flip status → finalizing
    ├── (commit 7) call VerdictGenerator
    ├── persist ReadinessVerdict + link session.verdict_id
    └── flip status → completed, return verdict payload

Cost rows go to ``agent_invocation_log`` with source='diagnostic_session'.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_factory import estimate_cost_inr
from app.agents.readiness_sub_agents import (
    DiagnosticInterviewer,
    SubAgentResult,
    VerdictGenerator,
)
from app.models.agent_invocation_log import (
    SOURCE_DIAGNOSTIC,
    STATUS_CAP_EXCEEDED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    AgentInvocationLog,
)
from app.models.readiness import (
    DIAGNOSTIC_STATUS_ABANDONED,
    DIAGNOSTIC_STATUS_ACTIVE,
    DIAGNOSTIC_STATUS_COMPLETED,
    DIAGNOSTIC_STATUS_FINALIZING,
    MAX_TURNS,
    ReadinessDiagnosticSession,
    ReadinessDiagnosticTurn,
    ReadinessVerdict,
)
from app.services.agent_invocation_logger import log_invocation
from app.services.readiness_action_router import RoutedAction, route_intent
from app.services.readiness_anti_sycophancy import evaluate_verdict
from app.services.readiness_evidence_validator import validate_claims
from app.services.readiness_memory_service import build_prior_session_hint
from app.services.student_snapshot_service import (
    StudentSnapshot,
    build_student_snapshot,
)

log = structlog.get_logger()

# Hard ₹15 cap per diagnostic session.
COST_CAP_INR = 15.0


class CostCapExceededError(RuntimeError):
    pass


class SessionNotFoundError(RuntimeError):
    pass


class SessionAlreadyClosedError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StartSessionResult:
    session_id: uuid.UUID
    opening_message: str
    snapshot_summary: dict[str, Any]
    prior_session_hint: str | None
    snapshot_id: uuid.UUID
    invoke_jd_decoder: bool


@dataclass
class TurnResult:
    session_id: uuid.UUID
    turn: int
    agent_message: str
    is_final: bool
    invoke_jd_decoder: bool
    jd_text_excerpt: str


@dataclass
class VerdictPayload:
    headline: str
    evidence: list[dict[str, Any]]
    next_action_intent: str
    next_action_route: str
    next_action_label: str
    sycophancy_flags: list[str]


@dataclass
class FinalizeResult:
    session_id: uuid.UUID
    verdict_id: uuid.UUID
    verdict: VerdictPayload


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def start_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> StartSessionResult:
    """Create a session and return the agent's opening message.

    The interviewer runs once for turn 1 using the snapshot + prior
    session hint. Both the agent's reply turn and the cost row are
    persisted before this function returns.
    """
    snapshot = await build_student_snapshot(db, user_id=user_id)
    prior_hint = await build_prior_session_hint(
        db, user_id=user_id, snapshot=snapshot
    )

    session = ReadinessDiagnosticSession(
        user_id=user_id,
        snapshot_id=snapshot.id,
        status=DIAGNOSTIC_STATUS_ACTIVE,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    interviewer = DiagnosticInterviewer()
    result = await interviewer.run(
        snapshot_summary=snapshot.summary_for_llm(),
        prior_session_hint=prior_hint,
        transcript=[],
        student_message="(session start — no message yet)",
        turn_number=1,
    )
    await _record_invocation(
        db,
        user_id=user_id,
        session_id=session.id,
        sub_agent=interviewer.name,
        result=result,
    )
    await _enforce_cost_cap(db, session_id=session.id)

    agent_reply, ready_for_verdict, invoke_jd, jd_excerpt = _coerce_turn(result)
    await _persist_turn(
        db,
        session_id=session.id,
        role="agent",
        content=agent_reply,
        metadata={
            "turn_number": 1,
            "ready_for_verdict": ready_for_verdict,
            "invoke_jd_decoder": invoke_jd,
            "jd_text_excerpt": jd_excerpt,
            "model": result.model,
            "latency_ms": result.latency_ms,
        },
    )
    session.turns_count = 1
    if ready_for_verdict:
        session.status = DIAGNOSTIC_STATUS_FINALIZING
    await db.commit()

    return StartSessionResult(
        session_id=session.id,
        opening_message=agent_reply,
        snapshot_summary=snapshot.summary_for_llm(),
        prior_session_hint=prior_hint,
        snapshot_id=snapshot.id,
        invoke_jd_decoder=invoke_jd,
    )


async def submit_turn(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    student_message: str,
) -> TurnResult:
    session = await _load_active_session(
        db, user_id=user_id, session_id=session_id
    )
    snapshot = await _reload_snapshot_for(db, session=session)

    # Persist the student turn first so transcript order is honest even
    # if the LLM call fails downstream.
    await _persist_turn(
        db,
        session_id=session.id,
        role="student",
        content=student_message[:4000],
        metadata={"turn_number": session.turns_count + 1},
    )
    session.turns_count += 1

    # Soft cap. If the student's message lands at or past MAX_TURNS, we
    # still let the interviewer run once more so the agent can wrap
    # gracefully — but we hint hard for ready_for_verdict by counting
    # the agent's existing turns.
    agent_turns_so_far = await _count_agent_turns(db, session_id=session.id)
    next_agent_turn_number = agent_turns_so_far + 1
    at_or_past_cap = next_agent_turn_number >= MAX_TURNS

    transcript = await _load_transcript(db, session_id=session.id)
    interviewer = DiagnosticInterviewer()
    result = await interviewer.run(
        snapshot_summary=snapshot.summary_for_llm(),
        prior_session_hint=None,  # only surfaced on turn 1
        transcript=transcript,
        student_message=student_message,
        turn_number=next_agent_turn_number,
    )
    await _record_invocation(
        db,
        user_id=user_id,
        session_id=session.id,
        sub_agent=interviewer.name,
        result=result,
    )
    await _enforce_cost_cap(db, session_id=session.id)

    agent_reply, ready_for_verdict, invoke_jd, jd_excerpt = _coerce_turn(result)
    # If we're at the cap, force the orchestrator's hand: even if the
    # interviewer hasn't decided to wrap, we end the conversation here.
    if at_or_past_cap:
        ready_for_verdict = True

    await _persist_turn(
        db,
        session_id=session.id,
        role="agent",
        content=agent_reply,
        metadata={
            "turn_number": next_agent_turn_number,
            "ready_for_verdict": ready_for_verdict,
            "invoke_jd_decoder": invoke_jd,
            "jd_text_excerpt": jd_excerpt,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "soft_cap_forced": at_or_past_cap and not result.parsed.get(
                "ready_for_verdict", False
            ),
        },
    )
    session.turns_count += 1
    if ready_for_verdict:
        session.status = DIAGNOSTIC_STATUS_FINALIZING
    await db.commit()

    return TurnResult(
        session_id=session.id,
        turn=next_agent_turn_number,
        agent_message=agent_reply,
        is_final=ready_for_verdict,
        invoke_jd_decoder=invoke_jd,
        jd_text_excerpt=jd_excerpt,
    )


async def finalize_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    closing_note: str | None = None,
) -> FinalizeResult:
    """Run the verdict generator, persist the verdict, complete the session.

    Sequence:
      1. Reload session (must be active or finalizing).
      2. Reload locked snapshot + transcript.
      3. Optionally append the closing_note as a final student turn so
         the verdict generator sees it.
      4. Run VerdictGenerator → validate → retry once on failure.
      5. Run anti-sycophancy evaluator (warning-only per locked spec).
      6. Resolve next-action route via the action router.
      7. Persist ReadinessVerdict, link session.verdict_id, flip
         status to completed.

    Cost rows for the verdict generator land in agent_invocation_log
    with source='diagnostic_session'. The validator's optional LLM pass
    (Haiku) gets its own invocation row so we can split costs cleanly.
    """
    session = await _load_active_session(
        db,
        user_id=user_id,
        session_id=session_id,
        allow_finalizing=True,
    )
    snapshot = await _reload_snapshot_for(db, session=session)

    if closing_note and closing_note.strip():
        await _persist_turn(
            db,
            session_id=session.id,
            role="student",
            content=closing_note.strip()[:4000],
            metadata={"turn_number": session.turns_count + 1, "closing_note": True},
        )
        session.turns_count += 1
        await db.commit()

    transcript = await _load_transcript(db, session_id=session.id)
    prior_verdicts = list(
        snapshot.payload.get("recent_verdict_summaries") or []
    )
    jd_match_score = await _load_session_jd_match_score(
        db, user_id=user_id, session=session
    )

    verdict_payload = await _generate_verdict(
        db,
        user_id=user_id,
        session_id=session.id,
        snapshot=snapshot,
        transcript=transcript,
        prior_verdicts=prior_verdicts,
        jd_match_score=jd_match_score,
    )

    sycophancy = evaluate_verdict(
        headline=verdict_payload["headline"],
        evidence=verdict_payload["evidence"],
        snapshot_summary=snapshot.summary_for_llm(),
    )

    routed: RoutedAction = route_intent(
        verdict_payload.get("next_action_intent"),
        suggested_label=verdict_payload.get("next_action_label"),
    )

    verdict_row = ReadinessVerdict(
        session_id=session.id,
        headline=verdict_payload["headline"],
        evidence=verdict_payload["evidence"],
        next_action_intent=routed.intent,
        next_action_route=routed.route,
        next_action_label=routed.label,
        model=verdict_payload.get("_model"),
        validation=verdict_payload.get("_validation"),
        sycophancy_flags=(
            list(sycophancy.flags + sycophancy.forbidden_phrases_hit)
            if sycophancy.has_flags()
            else None
        ),
    )
    db.add(verdict_row)
    await db.commit()
    await db.refresh(verdict_row)

    session.verdict_id = verdict_row.id
    session.status = DIAGNOSTIC_STATUS_COMPLETED
    session.completed_at = datetime.now(UTC)
    await db.commit()

    return FinalizeResult(
        session_id=session.id,
        verdict_id=verdict_row.id,
        verdict=VerdictPayload(
            headline=verdict_row.headline,
            evidence=list(verdict_row.evidence or []),
            next_action_intent=verdict_row.next_action_intent,
            next_action_route=verdict_row.next_action_route,
            next_action_label=verdict_row.next_action_label,
            sycophancy_flags=list(verdict_row.sycophancy_flags or []),
        ),
    )


async def abandon_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> None:
    """Mark a session abandoned. Used when the student navigates away
    or the inactivity sweeper fires."""
    session = await _load_active_session(
        db, user_id=user_id, session_id=session_id, allow_finalizing=True
    )
    session.status = DIAGNOSTIC_STATUS_ABANDONED
    await db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_active_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    allow_finalizing: bool = False,
) -> ReadinessDiagnosticSession:
    session = (
        await db.execute(
            select(ReadinessDiagnosticSession).where(
                ReadinessDiagnosticSession.id == session_id,
                ReadinessDiagnosticSession.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise SessionNotFoundError(f"session {session_id} not found")
    if session.status == DIAGNOSTIC_STATUS_ACTIVE:
        return session
    if allow_finalizing and session.status == DIAGNOSTIC_STATUS_FINALIZING:
        return session
    raise SessionAlreadyClosedError(
        f"session {session_id} is {session.status}"
    )


async def _reload_snapshot_for(
    db: AsyncSession, *, session: ReadinessDiagnosticSession
) -> StudentSnapshot:
    """Re-fetch the snapshot used at session start. We don't rebuild
    mid-session — locking the snapshot at start means the verdict and
    every interim turn cite the same evidence."""
    if session.snapshot_id is None:
        return await build_student_snapshot(db, user_id=session.user_id)
    from app.models.readiness import ReadinessStudentSnapshot

    row = (
        await db.execute(
            select(ReadinessStudentSnapshot).where(
                ReadinessStudentSnapshot.id == session.snapshot_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return await build_student_snapshot(db, user_id=session.user_id)
    return StudentSnapshot(
        id=row.id,
        user_id=row.user_id,
        payload=dict(row.payload or {}),
        evidence_allowlist=set(row.evidence_allowlist or []),
        built_at=row.built_at,
    )


async def _persist_turn(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    role: str,
    content: str,
    metadata: dict[str, Any],
) -> None:
    db.add(
        ReadinessDiagnosticTurn(
            session_id=session_id,
            role=role,
            content=content,
            metadata_json=metadata,
        )
    )
    await db.flush()


async def _load_transcript(
    db: AsyncSession, *, session_id: uuid.UUID
) -> list[dict[str, str]]:
    rows = (
        await db.execute(
            select(ReadinessDiagnosticTurn)
            .where(ReadinessDiagnosticTurn.session_id == session_id)
            .order_by(ReadinessDiagnosticTurn.created_at)
        )
    ).scalars().all()
    return [{"role": r.role, "content": r.content} for r in rows]


async def _count_agent_turns(
    db: AsyncSession, *, session_id: uuid.UUID
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ReadinessDiagnosticTurn)
        .where(
            ReadinessDiagnosticTurn.session_id == session_id,
            ReadinessDiagnosticTurn.role == "agent",
        )
    )
    return int(result.scalar_one_or_none() or 0)


async def _record_invocation(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    sub_agent: str,
    result: SubAgentResult,
) -> None:
    cost = estimate_cost_inr(
        model=result.model,
        input_tokens=result.tokens_in,
        output_tokens=result.tokens_out,
    )
    await log_invocation(
        db,
        user_id=user_id,
        source=SOURCE_DIAGNOSTIC,
        source_id=str(session_id),
        sub_agent=sub_agent,
        model=result.model,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_inr=cost,
        latency_ms=result.latency_ms,
        status=STATUS_SUCCEEDED if result.succeeded else STATUS_FAILED,
        error_message=result.error,
    )


async def _enforce_cost_cap(
    db: AsyncSession, *, session_id: uuid.UUID
) -> None:
    """Sum invocation costs for this session and raise if over cap.

    Reads agent_invocation_log directly — no need for a session-level
    cost column since we have a unified cost log.
    """
    result = await db.execute(
        select(func.coalesce(func.sum(AgentInvocationLog.cost_inr), 0.0))
        .where(
            AgentInvocationLog.source == SOURCE_DIAGNOSTIC,
            AgentInvocationLog.source_id == str(session_id),
        )
    )
    accumulated = float(result.scalar_one_or_none() or 0.0)
    if accumulated > COST_CAP_INR:
        # Record a cap_exceeded marker row so the audit trail has a
        # single concrete event.
        session_row = (
            await db.execute(
                select(ReadinessDiagnosticSession).where(
                    ReadinessDiagnosticSession.id == session_id
                )
            )
        ).scalar_one()
        await log_invocation(
            db,
            user_id=session_row.user_id,
            source=SOURCE_DIAGNOSTIC,
            source_id=str(session_id),
            sub_agent="orchestrator",
            model="n/a",
            tokens_in=0,
            tokens_out=0,
            cost_inr=0.0,
            latency_ms=None,
            status=STATUS_CAP_EXCEEDED,
            error_message=(
                f"diagnostic session cost cap exceeded: "
                f"₹{accumulated:.2f} > ₹{COST_CAP_INR}"
            ),
        )
        # Force-finalize the session so the next request can't tip us
        # further over.
        await db.execute(
            update(ReadinessDiagnosticSession)
            .where(ReadinessDiagnosticSession.id == session_id)
            .values(status=DIAGNOSTIC_STATUS_FINALIZING)
        )
        await db.commit()
        raise CostCapExceededError(
            f"diagnostic session cost cap exceeded: ₹{accumulated:.2f}"
        )


async def _load_session_jd_match_score(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session: ReadinessDiagnosticSession,
) -> dict[str, Any] | None:
    """Find the latest JdMatchScore created during this session.

    The diagnostic ↔ JD decoder bundle has the user paste a JD inline
    when the interviewer flags `invoke_jd_decoder`. The decoder writes
    a JdMatchScore row at decode time. On finalize we surface the most
    recent in-window score so the verdict generator can fold it in.

    Returns None when the user did not decode a JD during the session.
    """
    from app.models.jd_decoder import JdMatchScore  # local — avoids circular

    row = (
        await db.execute(
            select(JdMatchScore)
            .where(
                JdMatchScore.user_id == user_id,
                JdMatchScore.created_at >= session.started_at,
            )
            .order_by(JdMatchScore.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "score": row.score,
        "headline": row.headline,
        "next_action_intent": row.next_action_intent,
        "evidence_count": len(row.evidence or []),
    }


async def _generate_verdict(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    snapshot: StudentSnapshot,
    transcript: list[dict[str, str]],
    prior_verdicts: list[dict[str, Any]],
    jd_match_score: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the VerdictGenerator with one validation-driven retry.

    Returns a normalized payload dict with the keys the persistence
    layer expects (``headline``, ``evidence``, ``next_action_intent``,
    ``next_action_label``, plus underscore-prefixed audit fields).
    """
    generator = VerdictGenerator()
    snapshot_summary = snapshot.summary_for_llm()

    last_payload: dict[str, Any] | None = None
    last_validation: dict[str, Any] | None = None
    last_model: str | None = None

    for attempt in range(2):
        result = await generator.run(
            snapshot_summary=snapshot_summary,
            evidence_allowlist=snapshot.evidence_allowlist,
            transcript=transcript,
            prior_verdict_summaries=prior_verdicts,
            jd_match_score=jd_match_score,
        )
        await _record_invocation(
            db,
            user_id=user_id,
            session_id=session_id,
            sub_agent=generator.name,
            result=result,
        )
        await _enforce_cost_cap(db, session_id=session_id)
        last_model = result.model

        if not result.parsed:
            continue

        # Validate every chip. Skip the LLM pass when budget is tight
        # so a retry can still fit under the cap.
        validation = await validate_claims(
            result.parsed.get("evidence", []),
            evidence_allowlist=snapshot.evidence_allowlist,
            snapshot_summary=snapshot_summary,
            skip_llm_check=True,  # cheap; verdict's own evidence list
            label="verdict_evidence",
        )
        last_validation = validation.to_dict()
        last_payload = result.parsed
        if validation.passed:
            break
        log.info(
            "verdict_generator.validation_failed_retrying",
            attempt=attempt,
            failures=validation.violations[:3],
        )

    if last_payload is None:
        # Both attempts produced no JSON — surface a thin-data verdict
        # rather than ship something fabricated. Same pattern as the
        # JD decoder's match-score fallback.
        return {
            "headline": (
                "Couldn't synthesize a faithful verdict for this session."
            ),
            "evidence": [],
            "next_action_intent": "thin_data",
            "next_action_label": "Build a week of activity, then come back",
            "_model": last_model,
            "_validation": last_validation
            or {
                "passed": False,
                "violations": ["verdict generator returned no parseable JSON"],
            },
        }

    return _normalize_verdict_payload(
        last_payload, model=last_model, validation=last_validation
    )


def _normalize_verdict_payload(
    raw: dict[str, Any],
    *,
    model: str | None,
    validation: dict[str, Any] | None,
) -> dict[str, Any]:
    headline = str(raw.get("headline") or "").strip()[:280] or (
        "Verdict generated, but the agent didn't write a headline."
    )
    raw_evidence = raw.get("evidence")
    evidence: list[dict[str, Any]] = (
        [
            {
                "text": str(c.get("text") or "")[:240],
                "evidence_id": str(c.get("evidence_id") or ""),
                "kind": (
                    c.get("kind")
                    if c.get("kind") in ("strength", "gap", "neutral")
                    else "neutral"
                ),
            }
            for c in raw_evidence
            if isinstance(c, dict)
        ]
        if isinstance(raw_evidence, list)
        else []
    )
    next_action_raw = raw.get("next_action") or {}
    if not isinstance(next_action_raw, dict):
        next_action_raw = {}
    intent = str(next_action_raw.get("intent") or "thin_data")
    label = str(next_action_raw.get("label") or "")
    return {
        "headline": headline,
        "evidence": evidence,
        "next_action_intent": intent,
        "next_action_label": label,
        "_model": model,
        "_validation": validation,
    }


def _coerce_turn(result: SubAgentResult) -> tuple[str, bool, bool, str]:
    """Coerce the interviewer's structured output to safe primitives.

    Falls back to a calm wrap-up reply if the LLM returned no parseable
    JSON — better than surfacing raw tokens to the student. We do NOT
    set ready_for_verdict on a failure-fallback because the orchestrator
    will keep going until the soft turn cap (and at that point the cap
    forces wrap anyway).
    """
    parsed = result.parsed or {}
    reply = str(parsed.get("reply") or "").strip()
    if not reply:
        reply = "Hold on a second — let me re-read the picture."
    ready = bool(parsed.get("ready_for_verdict", False))
    invoke_jd = bool(parsed.get("invoke_jd_decoder", False))
    excerpt = str(parsed.get("jd_text_excerpt") or "").strip()
    if not invoke_jd:
        excerpt = ""
    return reply[:1200], ready, invoke_jd, excerpt[:400]


__all__ = [
    "COST_CAP_INR",
    "CostCapExceededError",
    "FinalizeResult",
    "SessionAlreadyClosedError",
    "SessionNotFoundError",
    "StartSessionResult",
    "TurnResult",
    "VerdictPayload",
    "abandon_session",
    "finalize_session",
    "start_session",
    "submit_turn",
]
