"""D9 Checkpoint 3 — Supervisor, dispatch, capability registry tests.

Verifies the stop-and-review triggers from the Checkpoint 3 spec:
  • Supervisor + dispatch layer functional in isolation against
    synthetic SupervisorContext inputs
  • All 5 failure classes from Pass 3b §7.1 covered
  • Capability registry visible via test that fetches all
    registered capabilities

No live LLM calls. Supervisor's LLM is stubbed via
Supervisor._llm_override.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


def _stub_session() -> AsyncSession:
    """Mock session that satisfies AgentContext's isinstance check.

    Tests that don't actually exercise DB calls use this — the
    agents under test have uses_memory=False / uses_tools=False so
    no real session methods are invoked.
    """
    return MagicMock(spec=AsyncSession)

from app.agents.capability import (
    all_known_agent_names,
    filter_capabilities_for_user,
    get_capability,
    list_capabilities,
)
from app.agents.dispatch import (
    DEFAULT_FALLBACK_AGENT,
    dispatch_chain,
    dispatch_single,
    process_handoff,
)
from app.agents.supervisor import (
    Supervisor,
    SupervisorInput,
    _build_keyword_fallback_decision,
    _parse_route_decision,
)
from app.schemas.entitlement import (
    ActiveEntitlement,
    EntitlementContext,
    FreeTierState,
)
from app.schemas.supervisor import (
    AgentCapability,
    ChainStep,
    ConversationTurn,
    HandoffRequest,
    RateLimitState,
    RouteDecision,
    StudentSnapshot,
    SupervisorContext,
)


# ── Test fixtures ───────────────────────────────────────────────────


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


def _free_tier_ctx(user_id: uuid.UUID) -> EntitlementContext:
    return EntitlementContext(
        user_id=user_id,
        active_entitlements=[],
        free_tier=FreeTierState(
            grant_id=uuid.uuid4(),
            grant_type="signup_grace",
            granted_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=23),
            allowed_agents={"billing_support", "supervisor"},
        ),
        effective_tier="free",
        cost_budget_remaining_today_inr=Decimal("4.50"),
        cost_budget_used_today_inr=Decimal("0.50"),
        rate_limit_state=_empty_rate_limit(),
    )


def _empty_ctx(user_id: uuid.UUID) -> EntitlementContext:
    return EntitlementContext(
        user_id=user_id,
        active_entitlements=[],
        free_tier=None,
        effective_tier="standard",
        cost_budget_remaining_today_inr=Decimal("50.00"),
        cost_budget_used_today_inr=Decimal("0"),
        rate_limit_state=_empty_rate_limit(),
    )


def _supervisor_context(
    *,
    student_id: uuid.UUID | None = None,
    user_message: str = "Explain RAG",
    available_caps: list[AgentCapability] | None = None,
    cost_remaining: Decimal = Decimal("47.50"),
    snapshot: StudentSnapshot | None = None,
) -> SupervisorContext:
    student_id = student_id or uuid.uuid4()
    return SupervisorContext(
        student_id=student_id,
        request_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        actor_id=student_id,
        actor_role="student",
        user_message=user_message,
        attachments=[],
        entitlements=[],
        rate_limit_remaining=_empty_rate_limit(),
        cost_budget_remaining_today_inr=cost_remaining,
        student_snapshot=snapshot or StudentSnapshot(),
        thread_summary=None,
        recent_turns=[],
        recent_agent_actions=[],
        available_agents=available_caps or [],
        available_tools=[],
    )


# ── Capability registry ────────────────────────────────────────────


class TestCapabilityRegistry:
    def test_thirteen_declarations(self) -> None:
        caps = list_capabilities()
        assert len(caps) == 13

    def test_supervisor_and_learning_coach_available_now(self) -> None:
        caps = list_capabilities()
        names_available = {c.name for c in caps if c.available_now}
        assert "supervisor" in names_available
        assert "learning_coach" in names_available

    def test_other_specialists_not_yet_available(self) -> None:
        caps = list_capabilities()
        for c in caps:
            if c.name in ("supervisor", "learning_coach"):
                continue
            assert c.available_now is False, (
                f"{c.name} should be available_now=False until its migration"
            )

    def test_free_tier_capabilities(self) -> None:
        caps = list_capabilities()
        free_min_tier = {c.name for c in caps if c.minimum_tier == "free"}
        assert free_min_tier == {"supervisor", "billing_support", "content_ingestion"} or {
            "supervisor",
            "billing_support",
        }.issubset(free_min_tier)

    def test_get_capability_known_returns(self) -> None:
        cap = get_capability("learning_coach")
        assert cap is not None
        assert cap.name == "learning_coach"

    def test_get_capability_unknown_returns_none(self) -> None:
        assert get_capability("knowledge_graph") is None  # retired
        assert get_capability("socratic_tutor") is None  # retired
        assert get_capability("not_an_agent") is None

    def test_all_known_agent_names_excludes_retired(self) -> None:
        names = all_known_agent_names()
        # Retired/merged agents must NOT be in the registry.
        retired = {
            "socratic_tutor",
            "student_buddy",
            "adaptive_path",
            "spaced_repetition",
            "knowledge_graph",
            "code_review",
            "coding_assistant",
            "curriculum_mapper",
            "cover_letter",
            "job_match",
            "peer_matching",
            "deep_capturer",
            "community_celebrator",
            "disrupt_prevention",
            "adaptive_quiz",
        }
        assert names.isdisjoint(retired)


# ── Capability filtering by entitlement ────────────────────────────


class TestCapabilityFiltering:
    def test_standard_user_sees_all_available_now(self) -> None:
        ctx = _entitled_ctx(uuid.uuid4())
        all_caps = list_capabilities()
        available = filter_capabilities_for_user(all_caps, ctx)
        # Every available_now capability is reachable for standard tier
        expected = {c.name for c in all_caps if c.available_now}
        assert {c.name for c in available} == expected

    def test_free_tier_user_sees_only_allowed_agents(self) -> None:
        ctx = _free_tier_ctx(uuid.uuid4())
        all_caps = list_capabilities()
        available = filter_capabilities_for_user(all_caps, ctx)
        names = {c.name for c in available}
        # Free-tier user with no paid entitlement: only supervisor +
        # billing_support are reachable. billing_support is NOT
        # available_now in D9 (awaits D10), so only supervisor remains.
        # That matches the registry inventory.
        assert "learning_coach" not in names
        assert "supervisor" in names

    def test_unavailable_now_filtered_out(self) -> None:
        ctx = _entitled_ctx(uuid.uuid4())
        all_caps = list_capabilities()
        available = filter_capabilities_for_user(all_caps, ctx)
        for c in available:
            assert c.available_now is True


# ── Supervisor LLM stub helpers ─────────────────────────────────────


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _SupervisorStubLLM:
    """Stub for ChatAnthropic — returns a canned response."""

    def __init__(self, response_json: str) -> None:
        self.response_json = response_json
        self.calls: list[Any] = []

    async def ainvoke(self, messages):  # type: ignore[no-untyped-def]
        self.calls.append(messages)
        return _FakeMessage(content=self.response_json)


class _MalformedSupervisorLLM:
    """Returns junk that isn't valid JSON."""

    async def ainvoke(self, messages):  # type: ignore[no-untyped-def]
        return _FakeMessage(content="not even close to JSON")


# ── Supervisor (parse + fallback) ──────────────────────────────────


class TestSupervisorParse:
    def test_clean_json_parses(self) -> None:
        raw = json.dumps(
            {
                "action": "dispatch_single",
                "target_agent": "learning_coach",
                "constructed_context": {"question": "x"},
                "reasoning": "Tutoring question.",
                "confidence": "high",
                "primary_intent": "tutoring_question",
            }
        )
        decision = _parse_route_decision(raw)
        assert decision is not None
        assert decision.action == "dispatch_single"

    def test_prose_wrapper_still_parses(self) -> None:
        wrapped = (
            "Here's my decision:\n\n"
            + json.dumps(
                {
                    "action": "decline",
                    "decline_reason": "out_of_scope",
                    "decline_message": "x",
                    "reasoning": "OOS.",
                    "confidence": "high",
                    "primary_intent": "out_of_scope",
                }
            )
            + "\n\nThat's the call."
        )
        decision = _parse_route_decision(wrapped)
        assert decision is not None
        assert decision.action == "decline"

    def test_invalid_returns_none(self) -> None:
        assert _parse_route_decision("totally not JSON") is None
        assert _parse_route_decision("{") is None  # unbalanced

    def test_keyword_fallback_routes_code(self) -> None:
        ctx = _supervisor_context(
            user_message="Please review my code for bugs",
            available_caps=[
                AgentCapability(
                    name="senior_engineer",
                    description="x",
                    available_now=True,
                ),
                AgentCapability(
                    name="learning_coach",
                    description="x",
                    available_now=True,
                ),
            ],
        )
        decision = _build_keyword_fallback_decision(ctx)
        assert decision.action == "dispatch_single"
        assert decision.target_agent == "senior_engineer"

    def test_keyword_fallback_routes_to_default_when_no_match(self) -> None:
        ctx = _supervisor_context(
            user_message="random words about nothing specific",
            available_caps=[
                AgentCapability(
                    name="learning_coach",
                    description="x",
                    available_now=True,
                ),
            ],
        )
        decision = _build_keyword_fallback_decision(ctx)
        assert decision.target_agent == "learning_coach"

    def test_keyword_fallback_declines_when_no_agents(self) -> None:
        ctx = _supervisor_context(
            user_message="anything",
            available_caps=[],
        )
        decision = _build_keyword_fallback_decision(ctx)
        assert decision.action == "decline"


# ── Supervisor end-to-end (with stub LLM) ──────────────────────────


class TestSupervisorRun:
    @pytest.fixture
    def supervisor(self) -> Supervisor:
        sup = Supervisor()
        return sup

    async def test_run_dispatches_on_clean_response(self, supervisor: Supervisor) -> None:
        canned = json.dumps(
            {
                "action": "dispatch_single",
                "target_agent": "learning_coach",
                "constructed_context": {"question": "What is RAG?"},
                "reasoning": "Tutoring question.",
                "confidence": "high",
                "primary_intent": "tutoring_question",
            }
        )
        supervisor._llm_override = _SupervisorStubLLM(canned)  # type: ignore[assignment]

        ctx = _supervisor_context(user_message="What is RAG?")
        from app.agents.primitives.communication import CallChain
        from app.agents.agentic_base import AgentContext

        # AgentContext requires a session; tests don't actually use it
        # because the Supervisor opt-outs uses_inter_agent / uses_tools.
        # Pass a sentinel object.
        agent_ctx = AgentContext(
            user_id=ctx.student_id,
            chain=CallChain.start_root(user_id=ctx.student_id),
            session=_stub_session(),
            permissions=frozenset(),
        )
        result = await supervisor.execute(
            SupervisorInput(supervisor_context=ctx),
            agent_ctx,
        )
        assert result.output["action"] == "dispatch_single"
        assert result.output["target_agent"] == "learning_coach"

    async def test_failure_class_a_malformed_falls_back(
        self, supervisor: Supervisor
    ) -> None:
        """Pass 3b §7.1 Failure Class A — Supervisor LLM returns garbage,
        keyword fallback rescues."""
        supervisor._llm_override = _MalformedSupervisorLLM()  # type: ignore[assignment]

        ctx = _supervisor_context(
            user_message="Please review my code",
            available_caps=[
                AgentCapability(
                    name="senior_engineer",
                    description="x",
                    available_now=True,
                ),
                AgentCapability(
                    name="learning_coach",
                    description="x",
                    available_now=True,
                ),
            ],
        )
        from app.agents.primitives.communication import CallChain
        from app.agents.agentic_base import AgentContext

        agent_ctx = AgentContext(
            user_id=ctx.student_id,
            chain=CallChain.start_root(user_id=ctx.student_id),
            session=_stub_session(),
            permissions=frozenset(),
        )
        result = await supervisor.execute(
            SupervisorInput(supervisor_context=ctx),
            agent_ctx,
        )
        # The keyword fallback found "review my code" and routed to
        # senior_engineer.
        assert result.output["action"] == "dispatch_single"
        assert result.output["target_agent"] == "senior_engineer"
        assert "fallback" in result.output["reasoning"].lower()


# ── Dispatch — Pass 3b §7.1 failure classes ─────────────────────────


class _FakeAgenticAgent:
    """Minimal AgenticBaseAgent stand-in for dispatch tests.

    Registered into the agentic registry under a chosen name; calls
    to call_agent dispatch here. Tests can assert the call happened
    and inspect the payload received.
    """

    # Empty tuples match the AgenticBaseAgent default — any caller/callee
    # permitted. The registry's register_agentic reads these.
    allowed_callers: tuple[str, ...] = ()
    allowed_callees: tuple[str, ...] = ()

    def __init__(
        self,
        name: str,
        *,
        return_value: dict | None = None,
        raise_exception: bool = False,
    ) -> None:
        self.name = name
        self.return_value = return_value or {
            "output_text": f"response from {name}",
            "summary": f"summary from {name}",
        }
        self.raise_exception = raise_exception
        self.calls: list[dict] = []

    async def run_agentic(self, payload, chain):  # type: ignore[no-untyped-def]
        self.calls.append({"payload": payload, "chain": chain})
        if self.raise_exception:
            raise RuntimeError("simulated specialist failure")
        from app.agents.primitives.communication import AgentCallResult

        return AgentCallResult(
            callee=self.name,
            output=self.return_value,
            status="ok",
            error=None,
            duration_ms=0,
        )


class TestDispatchFailureClasses:
    """Pass 3b §7.1 — Failure Class A through E."""

    def setup_method(self) -> None:
        from app.agents.primitives.communication import (
            clear_agentic_registry,
            register_agentic,
        )

        clear_agentic_registry()
        # Re-register the supervisor so subsequent tests that build
        # one don't trip the missing-agent case.
        # (Not strictly needed for dispatch tests, but defensive.)
        from app.agents.supervisor import Supervisor  # noqa: F401

    def teardown_method(self) -> None:
        from app.agents.primitives.communication import clear_agentic_registry

        clear_agentic_registry()

    async def test_failure_class_b_invalid_target_falls_back(self) -> None:
        """Class B: Supervisor returns valid JSON but specifies a known
        but unavailable agent. Dispatch falls back to default."""
        from app.agents.primitives.communication import (
            CallChain,
            register_agentic,
        )

        # Register the fallback so it can actually be invoked.
        fake_lc = _FakeAgenticAgent("learning_coach")
        register_agentic(fake_lc)

        decision = RouteDecision(
            action="dispatch_single",
            target_agent="senior_engineer",  # in registry but available_now=False
            constructed_context={"task": "x"},
            reasoning="test",
            confidence="medium",
            primary_intent="code_review_request",
        )
        ctx = _supervisor_context()
        chain = CallChain.start_root(user_id=ctx.student_id)
        ent_ctx = _entitled_ctx(ctx.student_id)

        # Use a stub session — dispatch_single's only DB call is the
        # Layer 3 re-check which we bypass by passing fresh_ctx.
        result = await dispatch_single(
            decision,
            ctx,
            db=_stub_session(),
            chain=chain,
            fresh_ctx=ent_ctx,
        )
        # senior_engineer is unavailable → fall back to learning_coach
        assert result.agent_name == DEFAULT_FALLBACK_AGENT
        assert len(fake_lc.calls) == 1

    async def test_failure_class_b_unknown_agent_falls_back(self) -> None:
        """Class B variant: target_agent not in the registry at all."""
        from app.agents.primitives.communication import (
            CallChain,
            register_agentic,
        )

        fake_lc = _FakeAgenticAgent("learning_coach")
        register_agentic(fake_lc)

        decision = RouteDecision(
            action="dispatch_single",
            target_agent="hallucinated_agent_xyz",
            constructed_context={},
            reasoning="test",
            confidence="medium",
            primary_intent="tutoring_question",
        )
        ctx = _supervisor_context()
        chain = CallChain.start_root(user_id=ctx.student_id)
        ent_ctx = _entitled_ctx(ctx.student_id)
        result = await dispatch_single(
            decision,
            ctx,
            db=_stub_session(),
            chain=chain,
            fresh_ctx=ent_ctx,
        )
        assert result.agent_name == DEFAULT_FALLBACK_AGENT

    async def test_failure_class_c_specialist_error_returns_decline(self) -> None:
        """Class C: specialist raises; dispatch surfaces a graceful error."""
        from app.agents.primitives.communication import (
            CallChain,
            register_agentic,
        )

        # learning_coach raises
        fake_lc = _FakeAgenticAgent("learning_coach", raise_exception=True)
        register_agentic(fake_lc)

        decision = RouteDecision(
            action="dispatch_single",
            target_agent="learning_coach",
            constructed_context={},
            reasoning="test",
            confidence="high",
            primary_intent="tutoring_question",
        )
        ctx = _supervisor_context()
        chain = CallChain.start_root(user_id=ctx.student_id)
        ent_ctx = _entitled_ctx(ctx.student_id)
        result = await dispatch_single(
            decision,
            ctx,
            db=_stub_session(),
            chain=chain,
            fresh_ctx=ent_ctx,
        )
        # Specialist raised → call_agent caught, returned status=error.
        # dispatch_single surfaced that as a blocked AgentResult; the
        # exact block_reason carries the underlying error message, so
        # we assert the contract (blocked + non-empty reason) rather
        # than a specific string.
        assert result.blocked is True
        assert result.block_reason  # non-empty
        assert (
            "trouble" in (result.output_text or "").lower()
            or "fail" in (result.output_text or "").lower()
            or result.block_reason.lower().startswith("runtimeerror")
        )

    async def test_failure_class_d_cost_exhausted_declines(self) -> None:
        """Class D: cost ceiling exhausted before dispatch — Layer 3 catches."""
        from app.agents.primitives.communication import CallChain

        decision = RouteDecision(
            action="dispatch_single",
            target_agent="learning_coach",
            constructed_context={},
            reasoning="test",
            confidence="high",
            primary_intent="tutoring_question",
        )
        ctx = _supervisor_context()
        # Cost remaining below learning_coach's typical_cost_inr (3.50)
        broke_ctx = EntitlementContext(
            user_id=ctx.student_id,
            active_entitlements=[
                ActiveEntitlement(
                    entitlement_id=uuid.uuid4(),
                    user_id=ctx.student_id,
                    course_id=uuid.uuid4(),
                    course_slug="x",
                    tier="standard",
                    source="purchase",
                    granted_at=datetime.now(UTC),
                )
            ],
            free_tier=None,
            effective_tier="standard",
            cost_budget_remaining_today_inr=Decimal("0.50"),
            cost_budget_used_today_inr=Decimal("49.50"),
            rate_limit_state=_empty_rate_limit(),
        )
        chain = CallChain.start_root(user_id=ctx.student_id)
        result = await dispatch_single(
            decision,
            ctx,
            db=_stub_session(),
            chain=chain,
            fresh_ctx=broke_ctx,
        )
        assert result.blocked is True
        assert result.block_reason == "cost_exhausted"

    async def test_failure_class_e_revoked_mid_request_declines(self) -> None:
        """Class E variant: entitlement revoked between Layer 1 and dispatch.

        Caught by Layer 3's fresh re-check. The fresh_ctx has empty
        entitlements — dispatch returns entitlement_revoked.
        """
        from app.agents.primitives.communication import CallChain

        decision = RouteDecision(
            action="dispatch_single",
            target_agent="learning_coach",
            constructed_context={},
            reasoning="test",
            confidence="high",
            primary_intent="tutoring_question",
        )
        ctx = _supervisor_context()
        empty_ctx = _empty_ctx(ctx.student_id)
        chain = CallChain.start_root(user_id=ctx.student_id)
        result = await dispatch_single(
            decision,
            ctx,
            db=_stub_session(),
            chain=chain,
            fresh_ctx=empty_ctx,
        )
        assert result.blocked is True
        assert result.block_reason == "entitlement_revoked"


# ── Chain dispatch ──────────────────────────────────────────────────


class TestChainDispatch:
    def setup_method(self) -> None:
        from app.agents.primitives.communication import clear_agentic_registry

        clear_agentic_registry()

    def teardown_method(self) -> None:
        from app.agents.primitives.communication import clear_agentic_registry

        clear_agentic_registry()

    async def test_two_step_chain_passes_state(self) -> None:
        from app.agents.primitives.communication import (
            CallChain,
            register_agentic,
        )

        fake_se = _FakeAgenticAgent(
            "senior_engineer",
            return_value={"output_text": "code is fine", "summary": "code clean"},
        )
        fake_lc = _FakeAgenticAgent(
            "learning_coach",
            return_value={"output_text": "study DI", "summary": "next: DI"},
        )
        register_agentic(fake_se)
        register_agentic(fake_lc)

        decision = RouteDecision(
            action="dispatch_chain",
            chain_plan=[
                ChainStep(
                    step_number=1,
                    target_agent="senior_engineer",
                    constructed_context={"task": "review"},
                    on_failure="abort_chain",
                ),
                ChainStep(
                    step_number=2,
                    target_agent="learning_coach",
                    constructed_context={"task": "next concept"},
                    pass_outputs_from_steps=[1],
                    on_failure="continue",
                ),
            ],
            reasoning="test",
            confidence="high",
            primary_intent="code_review_request",
        )
        ctx = _supervisor_context()
        chain = CallChain.start_root(user_id=ctx.student_id)
        ent_ctx = _entitled_ctx(ctx.student_id)

        # Two patches needed for chain dispatch:
        #
        # 1. capability.available_now: senior_engineer and learning_coach
        #    are available_now=False in the registry until their
        #    migrations land. For this test we need them to look
        #    available so the chain isn't filtered.
        #
        # 2. compute_active_entitlements: dispatch_chain → dispatch_single
        #    re-fetches a fresh EntitlementContext per step (Pass 3f §A.3
        #    Layer 3 race protection). With a MagicMock(spec=AsyncSession)
        #    the SQL execute() returns another mock; we patch the lookup
        #    function to return our pre-built ent_ctx instead.
        import app.agents.dispatch as dispatch_mod

        original_get_cap = dispatch_mod.get_capability
        original_compute = dispatch_mod.__dict__.get("compute_active_entitlements")

        def _patched_get_cap(name: str):
            cap = original_get_cap(name)
            if cap is None:
                return None
            return cap.model_copy(update={"available_now": True})

        async def _patched_compute(db, user_id):
            return ent_ctx

        dispatch_mod.get_capability = _patched_get_cap  # type: ignore[assignment]
        # Patch the import-target inside dispatch.py's _layer3_check.
        from app.services import entitlement_service as ent_svc

        original_ent_compute = ent_svc.compute_active_entitlements
        ent_svc.compute_active_entitlements = _patched_compute  # type: ignore[assignment]

        try:
            chain_result = await dispatch_chain(
                decision,
                ctx,
                db=_stub_session(),
                chain=chain,
            )
        finally:
            dispatch_mod.get_capability = original_get_cap  # type: ignore[assignment]
            ent_svc.compute_active_entitlements = original_ent_compute  # type: ignore[assignment]

        assert len(chain_result.steps) == 2
        assert chain_result.aborted_at_step is None
        # Step 2 received Step 1's summary as `step_1_output`
        step2_payload = fake_lc.calls[0]["payload"]
        assert "step_1_output" in step2_payload
        assert step2_payload["step_1_output"] == "code clean"


# ── Handoff processing ─────────────────────────────────────────────


class TestHandoff:
    def setup_method(self) -> None:
        from app.agents.primitives.communication import clear_agentic_registry

        clear_agentic_registry()

    def teardown_method(self) -> None:
        from app.agents.primitives.communication import clear_agentic_registry

        clear_agentic_registry()

    async def test_suggested_handoff_declined_in_v1(self) -> None:
        from app.agents.primitives.communication import CallChain

        handoff = HandoffRequest(
            target_agent="learning_coach",
            reason="student asked a follow-up",
            suggested_context={},
            handoff_type="suggested",
        )
        ctx = _supervisor_context()
        chain = CallChain.start_root(user_id=ctx.student_id)
        result = await process_handoff(
            handoff,
            ctx,
            db=_stub_session(),
            chain=chain,
        )
        # v1 declines suggested handoffs
        assert result is None

    async def test_unknown_target_handoff_returns_none(self) -> None:
        from app.agents.primitives.communication import CallChain

        handoff = HandoffRequest(
            target_agent="hallucinated_agent",
            reason="x",
            suggested_context={},
            handoff_type="mandatory",
        )
        ctx = _supervisor_context()
        chain = CallChain.start_root(user_id=ctx.student_id)
        result = await process_handoff(
            handoff,
            ctx,
            db=_stub_session(),
            chain=chain,
        )
        assert result is None

    async def test_depth_zero_returns_none(self) -> None:
        from app.agents.primitives.communication import CallChain

        handoff = HandoffRequest(
            target_agent="learning_coach",
            reason="x",
            suggested_context={},
            handoff_type="mandatory",
        )
        ctx = _supervisor_context()
        chain = CallChain.start_root(user_id=ctx.student_id)
        result = await process_handoff(
            handoff,
            ctx,
            db=_stub_session(),
            chain=chain,
            depth_remaining=0,
        )
        assert result is None
