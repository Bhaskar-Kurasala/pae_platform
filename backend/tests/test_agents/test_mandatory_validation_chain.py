"""D13.5 Stage 2 — mandatory validation chain dispatch tests.

Pins the dispatch_single → auto-validator extension behavior across
all six required cases:

  1. Happy path: producer + validator both succeed; both outputs in
     readable list; chain-summed timeout applied.
  2. Producer fails: validator NOT invoked.
  3. Validator fails: producer's output ships + validation_unavailable
     marker.
  4. Adapter fails: chain returns structured error (fail-loud).
  5. Timeout sum: chain budget computed correctly.
  6. Output projection: validator output appears under VALIDATION_OUTPUT_KEY.

Pure stubs — _FakeAgenticAgent stand-ins for both producer and
validator, no LLM calls, no DB. Mirrors test_checkpoint3_dispatch.py
patterns where the dispatch layer is exercised in isolation.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dispatch import (
    VALIDATION_OUTPUT_KEY,
    _CHAIN_TIMEOUT_MULTIPLIER,
    _resolve_chain_summed_budget,
    dispatch_single,
)
from app.schemas.entitlement import (
    ActiveEntitlement,
    EntitlementContext,
)
from app.schemas.supervisor import (
    AgentCapability,
    ConversationTurn,
    RateLimitState,
    RouteDecision,
    StudentSnapshot,
    SupervisorContext,
)

pytestmark = []  # individual async tests carry their own marker


# ── Test doubles ────────────────────────────────────────────────────


def _stub_session() -> AsyncSession:
    return MagicMock(spec=AsyncSession)


class _FakeAgenticAgent:
    """Minimal AgenticBaseAgent stand-in (mirrors test_checkpoint3_dispatch)."""

    allowed_callers: tuple[str, ...] = ()
    allowed_callees: tuple[str, ...] = ()

    def __init__(
        self,
        name: str,
        *,
        return_value: dict | None = None,
        raise_exception: bool = False,
        sleep_seconds: float = 0.0,
        status: str = "ok",
        error: str | None = None,
    ) -> None:
        self.name = name
        self.return_value = return_value or {
            "output_text": f"response from {name}",
            "summary": f"summary from {name}",
        }
        self.raise_exception = raise_exception
        self.sleep_seconds = sleep_seconds
        self.status = status
        self.error = error
        self.calls: list[dict] = []

    async def run_agentic(self, payload, chain):  # type: ignore[no-untyped-def]
        self.calls.append({"payload": payload, "chain": chain})
        if self.sleep_seconds > 0:
            await asyncio.sleep(self.sleep_seconds)
        if self.raise_exception:
            raise RuntimeError(f"simulated {self.name} failure")
        from app.agents.primitives.communication import AgentCallResult

        return AgentCallResult(
            callee=self.name,
            output=self.return_value,
            status=self.status,
            error=self.error,
            duration_ms=int(self.sleep_seconds * 1000),
        )


# ── Fixtures ────────────────────────────────────────────────────────


def _empty_rate_limit() -> RateLimitState:
    now = datetime.now(UTC)
    return RateLimitState(
        burst_remaining=10,
        burst_window_resets_at=now + timedelta(minutes=1),
        hourly_remaining=100,
        hourly_window_resets_at=now + timedelta(hours=1),
    )


def _entitled_ctx(user_id: uuid.UUID) -> EntitlementContext:
    return EntitlementContext(
        user_id=user_id,
        active_entitlements=[
            ActiveEntitlement(
                entitlement_id=uuid.uuid4(),
                user_id=user_id,
                course_id=uuid.uuid4(),
                course_slug="genai-engineering-101",
                tier="standard",
                source="purchase",
                granted_at=datetime.now(UTC) - timedelta(days=10),
            )
        ],
        free_tier=None,
        effective_tier="standard",
        cost_budget_remaining_today_inr=Decimal("47.50"),
        cost_budget_used_today_inr=Decimal("2.50"),
        rate_limit_state=_empty_rate_limit(),
    )


def _supervisor_context(student_id: uuid.UUID | None = None) -> SupervisorContext:
    """Mirrors test_checkpoint3_dispatch.py's helper exactly."""
    student_id = student_id or uuid.uuid4()
    return SupervisorContext(
        student_id=student_id,
        request_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        actor_id=student_id,
        actor_role="student",
        user_message="Tailor my resume for this JD",
        attachments=[],
        entitlements=[],
        rate_limit_remaining=_empty_rate_limit(),
        cost_budget_remaining_today_inr=Decimal("47.50"),
        student_snapshot=StudentSnapshot(),
        thread_summary=None,
        recent_turns=[],
        recent_agent_actions=[],
        available_agents=[],
        available_tools=[],
    )


def _representative_tailored_output() -> dict[str, Any]:
    """A minimal valid TailoredResumeOutput as a dict (what call_agent
    returns; matches what the real run() emits via model_dump)."""
    return {
        "tailored_resume": "Tailored resume body — keyword-aligned bullets.",
        "changes_made": [],
        "keyword_alignment_score": 0.85,
        "unsupported_additions": [],
        "ats_compatibility_notes": ["Use standard fonts."],
        "handoff_request": None,
        # Top-level convention key.
        "answer": "Tailored resume body — keyword-aligned bullets.",
    }


def _representative_reviewer_output() -> dict[str, Any]:
    """A minimal valid ResumeReviewerOutput as a dict."""
    return {
        "overall_score": 78,
        "headline_assessment": "Solid tailoring; one unsupported claim.",
        "strengths": ["Relevant keyword density"],
        "issues": [],
        "unsupported_claims": [
            {
                "claim_text": "Led a team of 12 ML engineers",
                "missing_evidence": "No team-size capstone evidence",
                "suggested_action": "verify_with_student",
            }
        ],
        "underrepresented_accomplishments": [],
        "suggested_changes": [],
        "handoff_request": None,
        "answer": "Solid tailoring; one unsupported claim.",
    }


# ── Helpers to register fake agents into the agentic registry ───────


def _register_fakes(
    *,
    producer: _FakeAgenticAgent,
    validator: _FakeAgenticAgent | None = None,
) -> None:
    """Stamp fake agents into the agentic registry under their names.
    The registry is global; tests using these names must register before
    calling dispatch_single."""
    from app.agents.primitives.communication import register_agentic

    register_agentic(producer)
    if validator is not None:
        register_agentic(validator)


# ── Tests ───────────────────────────────────────────────────────────


# Happy path
# -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_validator_auto_invoked() -> None:
    """tailored_resume's capability declares resume_reviewer as its
    mandatory validator. Happy path: both succeed, validator is
    auto-invoked, both outputs land in the AgentResult."""
    fake_producer = _FakeAgenticAgent(
        "tailored_resume", return_value=_representative_tailored_output()
    )
    fake_validator = _FakeAgenticAgent(
        "resume_reviewer", return_value=_representative_reviewer_output()
    )
    _register_fakes(producer=fake_producer, validator=fake_validator)

    decision = RouteDecision(
        action="dispatch_single",
        target_agent="tailored_resume",
        constructed_context={"resume_text": "x", "job_description": "y"},
        reasoning="test",
        confidence="high",
        primary_intent="resume_tailoring",
    )
    ctx = _supervisor_context()
    from app.agents.primitives.communication import CallChain

    chain = CallChain.start_root(user_id=ctx.student_id)
    ent_ctx = _entitled_ctx(ctx.student_id)

    result = await dispatch_single(
        decision, ctx, db=_stub_session(), chain=chain, fresh_ctx=ent_ctx
    )

    # Producer ran.
    assert result.agent_name == "tailored_resume"
    assert result.blocked is False
    assert len(fake_producer.calls) == 1

    # Validator was auto-invoked.
    assert len(fake_validator.calls) == 1

    # Output projection: validator's output is under VALIDATION_OUTPUT_KEY.
    assert result.structured_output is not None
    assert VALIDATION_OUTPUT_KEY in result.structured_output
    validation_block = result.structured_output[VALIDATION_OUTPUT_KEY]
    assert validation_block["overall_score"] == 78
    assert len(validation_block["unsupported_claims"]) == 1


@pytest.mark.asyncio
async def test_happy_path_adapter_threads_resume_to_validator() -> None:
    """The adapter (tailored_resume_to_reviewer_input) must run between
    producer and validator. Validator must receive the producer's
    tailored_resume body in its resume_text field."""
    producer_body = "ADAPTED-RESUME-BODY-MARKER-12345"
    fake_producer = _FakeAgenticAgent(
        "tailored_resume",
        return_value={**_representative_tailored_output(), "tailored_resume": producer_body},
    )
    fake_validator = _FakeAgenticAgent(
        "resume_reviewer", return_value=_representative_reviewer_output()
    )
    _register_fakes(producer=fake_producer, validator=fake_validator)

    decision = RouteDecision(
        action="dispatch_single",
        target_agent="tailored_resume",
        constructed_context={"resume_text": "x", "job_description": "y"},
        reasoning="test",
        confidence="high",
        primary_intent="resume_tailoring",
    )
    ctx = _supervisor_context()
    from app.agents.primitives.communication import CallChain

    chain = CallChain.start_root(user_id=ctx.student_id)

    await dispatch_single(
        decision, ctx, db=_stub_session(), chain=chain,
        fresh_ctx=_entitled_ctx(ctx.student_id),
    )

    # The validator received the producer's body via the adapter.
    validator_payload = fake_validator.calls[0]["payload"]
    assert validator_payload["resume_text"] == producer_body
    # Adapter populated specific_concerns per the validation contract.
    assert "unsupported_claims" in validator_payload["specific_concerns"]
    assert "ats_compatibility" in validator_payload["specific_concerns"]


# Producer fails
# -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_producer_fails_validator_not_invoked() -> None:
    """Producer raises → validator MUST NOT be invoked. The chain
    short-circuits at producer failure."""
    fake_producer = _FakeAgenticAgent("tailored_resume", raise_exception=True)
    fake_validator = _FakeAgenticAgent(
        "resume_reviewer", return_value=_representative_reviewer_output()
    )
    _register_fakes(producer=fake_producer, validator=fake_validator)

    decision = RouteDecision(
        action="dispatch_single",
        target_agent="tailored_resume",
        constructed_context={},
        reasoning="test",
        confidence="high",
        primary_intent="resume_tailoring",
    )
    ctx = _supervisor_context()
    from app.agents.primitives.communication import CallChain

    chain = CallChain.start_root(user_id=ctx.student_id)

    result = await dispatch_single(
        decision, ctx, db=_stub_session(), chain=chain,
        fresh_ctx=_entitled_ctx(ctx.student_id),
    )

    # Producer failure surfaced as blocked AgentResult (call_agent's
    # internal error handling; same shape as Failure Class C).
    assert result.blocked is True
    # Validator was NEVER invoked.
    assert len(fake_validator.calls) == 0


# Validator fails (best-effort: producer ships + marker)
# -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_validator_fails_producer_ships_with_marker() -> None:
    """Validator raises → producer's output STILL ships, plus a
    validation_unavailable marker so the frontend can surface the
    absence of validation. Compositional, not gating (D-B)."""
    fake_producer = _FakeAgenticAgent(
        "tailored_resume", return_value=_representative_tailored_output()
    )
    fake_validator = _FakeAgenticAgent(
        "resume_reviewer", raise_exception=True
    )
    _register_fakes(producer=fake_producer, validator=fake_validator)

    decision = RouteDecision(
        action="dispatch_single",
        target_agent="tailored_resume",
        constructed_context={},
        reasoning="test",
        confidence="high",
        primary_intent="resume_tailoring",
    )
    ctx = _supervisor_context()
    from app.agents.primitives.communication import CallChain

    chain = CallChain.start_root(user_id=ctx.student_id)

    result = await dispatch_single(
        decision, ctx, db=_stub_session(), chain=chain,
        fresh_ctx=_entitled_ctx(ctx.student_id),
    )

    # Producer's output ships — NOT blocked.
    assert result.blocked is False
    assert result.agent_name == "tailored_resume"
    assert result.structured_output is not None
    assert result.structured_output["tailored_resume"]

    # Validation marker is present.
    validation_block = result.structured_output[VALIDATION_OUTPUT_KEY]
    assert validation_block["validation_unavailable"] is True
    assert validation_block["validator"] == "resume_reviewer"
    # The reason is one of our marker strings; doesn't have to be exact
    # match (validator_blocked vs validator_error are both valid).
    assert validation_block["reason"] in {
        "validator_blocked", "validator_error", "validator_timeout",
    }


# Adapter fails (fail-loud)
# -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_fails_chain_blocks_fail_loud() -> None:
    """Adapter raises → producer's output is BLOCKED. The mandatory-
    validation contract is fail-loud: if validation can't even start,
    the user shouldn't get un-validated content silently."""
    # Register a synthetic capability whose adapter raises. We swap
    # the real adapter via monkeypatch on the registry.
    fake_producer = _FakeAgenticAgent(
        "tailored_resume", return_value={"malformed": "shape"}
    )
    fake_validator = _FakeAgenticAgent(
        "resume_reviewer", return_value=_representative_reviewer_output()
    )
    _register_fakes(producer=fake_producer, validator=fake_validator)

    # Swap tailored_resume's adapter with one that raises.
    from app.agents.capability import get_capability

    cap = get_capability("tailored_resume")
    assert cap is not None
    original_adapter = cap.validation_input_adapter

    def _broken_adapter(_: Any) -> Any:
        raise ValueError("adapter cannot map this shape")

    try:
        cap.validation_input_adapter = _broken_adapter

        decision = RouteDecision(
            action="dispatch_single",
            target_agent="tailored_resume",
            constructed_context={},
            reasoning="test",
            confidence="high",
            primary_intent="resume_tailoring",
        )
        ctx = _supervisor_context()
        from app.agents.primitives.communication import CallChain

        chain = CallChain.start_root(user_id=ctx.student_id)

        result = await dispatch_single(
            decision, ctx, db=_stub_session(), chain=chain,
            fresh_ctx=_entitled_ctx(ctx.student_id),
        )

        # Fail-loud: blocked, with the canonical reason.
        assert result.blocked is True
        assert result.block_reason == "validation_adapter_error"
        # Validator was NEVER invoked because adapter failed first.
        assert len(fake_validator.calls) == 0
    finally:
        cap.validation_input_adapter = original_adapter


# Chain-summed timeout math (D-E)
# -----------------------------------------------------------------


def test_chain_summed_budget_for_tailored_resume_pair() -> None:
    """Per D-E: sum(producer_timeout, validator_timeout) × 1.10.

    tailored_resume has timeout_override_seconds=120; resume_reviewer
    has typical_latency_ms=18000 → resolves to 60s ceiling (per D12
    calibration). 120 + 60 = 180 × 1.10 = 198. Asserts the formula
    composes against current capability values (the assertion adapts
    to whatever the resolver returns so a future calibration tweak
    doesn't mass-break this test)."""
    from app.agents.capability import (
        get_capability,
        resolve_timeout_seconds,
    )

    producer_cap = get_capability("tailored_resume")
    validator_cap = get_capability("resume_reviewer")
    assert producer_cap is not None and validator_cap is not None

    producer_budget = resolve_timeout_seconds(producer_cap)
    validator_budget = resolve_timeout_seconds(validator_cap)
    expected = (producer_budget + validator_budget) * _CHAIN_TIMEOUT_MULTIPLIER

    actual = _resolve_chain_summed_budget(producer_cap, validator_cap)
    assert actual == pytest.approx(expected, abs=0.01)
    # Sanity: must be at least the sum (no rounding-down bug).
    assert actual >= producer_budget + validator_budget


def test_chain_summed_multiplier_is_ten_percent_margin() -> None:
    """The multiplier is documented as 1.10 (10% margin). Pin it to
    catch accidental tightening (e.g., 1.05) that would squeeze the
    chain budget under MiniMax variance."""
    assert _CHAIN_TIMEOUT_MULTIPLIER == 1.10


# Output projection key
# -----------------------------------------------------------------


def test_validation_output_key_is_canonical() -> None:
    """The output projection key is fixed at 'validation' — frontends
    rely on this string to find the validator's output. Pin it so a
    future rename doesn't silently break the frontend contract."""
    assert VALIDATION_OUTPUT_KEY == "validation"


# Validator returns blocked status (best-effort fallback path)
# -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_validator_unknown_in_registry_marks_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge: tailored_resume's capability declares a validator that
    isn't actually registered (typo, or registry drift). The chain
    must mark the validation unavailable rather than blocking the
    producer's output."""
    from app.agents.capability import get_capability

    fake_producer = _FakeAgenticAgent(
        "tailored_resume", return_value=_representative_tailored_output()
    )
    _register_fakes(producer=fake_producer)
    # Don't register a validator under any name; redirect the
    # capability's pointer to a non-existent agent.
    cap = get_capability("tailored_resume")
    assert cap is not None
    monkeypatch.setattr(
        cap, "requires_mandatory_validation_by", "ghost_validator_404"
    )

    decision = RouteDecision(
        action="dispatch_single",
        target_agent="tailored_resume",
        constructed_context={},
        reasoning="test",
        confidence="high",
        primary_intent="resume_tailoring",
    )
    ctx = _supervisor_context()
    from app.agents.primitives.communication import CallChain

    chain = CallChain.start_root(user_id=ctx.student_id)

    result = await dispatch_single(
        decision, ctx, db=_stub_session(), chain=chain,
        fresh_ctx=_entitled_ctx(ctx.student_id),
    )

    # Producer's output ships — best-effort fallback path.
    assert result.blocked is False
    validation_block = result.structured_output[VALIDATION_OUTPUT_KEY]
    assert validation_block["validation_unavailable"] is True
    assert validation_block["reason"] == "validator_not_registered"
    assert validation_block["validator"] == "ghost_validator_404"


# Non-validating agent: no auto-extension
# -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_validating_agent_does_not_extend_chain() -> None:
    """An agent whose capability has requires_mandatory_validation_by=
    None (i.e., every agent except tailored_resume) does NOT auto-
    extend. Sanity: D13.5 doesn't accidentally turn every dispatch
    into a chain."""
    fake_producer = _FakeAgenticAgent(
        "career_coach", return_value={"output_text": "coaching reply"}
    )
    _register_fakes(producer=fake_producer)

    decision = RouteDecision(
        action="dispatch_single",
        target_agent="career_coach",
        constructed_context={},
        reasoning="test",
        confidence="high",
        primary_intent="career_coaching",
    )
    ctx = _supervisor_context()
    from app.agents.primitives.communication import CallChain

    chain = CallChain.start_root(user_id=ctx.student_id)

    result = await dispatch_single(
        decision, ctx, db=_stub_session(), chain=chain,
        fresh_ctx=_entitled_ctx(ctx.student_id),
    )

    assert result.blocked is False
    # No validation key in structured_output.
    if result.structured_output is not None:
        assert VALIDATION_OUTPUT_KEY not in result.structured_output
