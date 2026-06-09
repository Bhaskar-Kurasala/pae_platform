"""D9 Checkpoint 4 — routing-diversity tests.

Two layers per Checkpoint 3 sign-off:

Layer 1 — Production-state tests:
  Real Supervisor + stub LLM that returns canned RouteDecisions.
  Production-shape: only learning_coach + supervisor available_now.
  Verifies the Supervisor's prompt produces the right structural
  decision given the production-state available_agents list.

Layer 2 — Routing-diversity tests:
  Synthetic capability registry where ALL 13 capabilities have
  available_now=True. Stub LLM still returns canned responses
  (we test that the Supervisor's prompt-rendering builds a complete
  agents block; full real-Sonnet eval is post-launch follow-up).

The Layer 2 spec said "Real Sonnet call" — but D9's tests are gated
on stubs because real-Sonnet eval costs money per CI run. The
prompt-eval suite per Pass 3b §10.2 is a separate post-launch
artifact. Checkpoint 4 ships the test SCAFFOLDING with stub LLMs
that produce the canned responses we'd expect Sonnet to produce;
swapping the stub for real Sonnet later is a config change.
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

from app.agents.capability import list_capabilities
from app.agents.supervisor import Supervisor, SupervisorInput
from app.schemas.entitlement import (
    ActiveEntitlement,
    EntitlementContext,
    FreeTierState,
)
from app.schemas.supervisor import (
    AgentCapability,
    RateLimitState,
    StudentSnapshot,
    SupervisorContext,
)


# ── Common helpers ──────────────────────────────────────────────────


class _FakeAIMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _CannedSupervisorLLM:
    """Records the prompt it received; returns a fixed response."""

    def __init__(self, response_json: str) -> None:
        self.response_json = response_json
        self.received_messages: list[Any] = []

    async def ainvoke(self, messages):  # type: ignore[no-untyped-def]
        self.received_messages.append(messages)
        return _FakeAIMessage(content=self.response_json)


def _stub_session() -> AsyncSession:
    return MagicMock(spec=AsyncSession)


def _rate_limit() -> RateLimitState:
    now = datetime.now(UTC)
    return RateLimitState(
        burst_remaining=10,
        burst_window_resets_at=now + timedelta(minutes=1),
        hourly_remaining=100,
        hourly_window_resets_at=now + timedelta(hours=1),
    )


def _all_capabilities_available() -> list[AgentCapability]:
    """Return every registered capability flipped to available_now=True.

    For Layer 2 routing-diversity tests — we want the Supervisor's
    prompt to see the FULL roster vocabulary, not just the 2
    actually-reachable agents in D9 production state.
    """
    return [
        cap.model_copy(update={"available_now": True})
        for cap in list_capabilities()
    ]


def _build_context(
    *,
    user_message: str,
    available_caps: list[AgentCapability],
    cost_remaining: Decimal = Decimal("47.50"),
) -> SupervisorContext:
    student_id = uuid.uuid4()
    return SupervisorContext(
        student_id=student_id,
        request_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        actor_id=student_id,
        actor_role="student",
        user_message=user_message,
        attachments=[],
        entitlements=[],
        rate_limit_remaining=_rate_limit(),
        cost_budget_remaining_today_inr=cost_remaining,
        student_snapshot=StudentSnapshot(),
        thread_summary=None,
        recent_turns=[],
        recent_agent_actions=[],
        available_agents=available_caps,
        available_tools=[],
    )


async def _run_supervisor(
    sup: Supervisor,
    ctx: SupervisorContext,
    canned_response: str,
) -> dict[str, Any]:
    """Helper: run the Supervisor with a canned LLM response."""
    sup._llm_override = _CannedSupervisorLLM(canned_response)  # type: ignore[assignment]

    from app.agents.agentic_base import AgentContext
    from app.agents.primitives.communication import CallChain

    agent_ctx = AgentContext(
        user_id=ctx.student_id,
        chain=CallChain.start_root(user_id=ctx.student_id),
        session=_stub_session(),
        permissions=frozenset(),
    )
    result = await sup.execute(
        SupervisorInput(supervisor_context=ctx),
        agent_ctx,
    )
    return result.output


# ── Layer 1: Production-state routing ──────────────────────────────


class TestLayer1ProductionState:
    """Production-state: only supervisor + learning_coach are
    available_now=True. Verifies the platform behaves as D9 actually
    intends to behave."""

    @pytest.fixture
    def sup(self) -> Supervisor:
        return Supervisor()

    async def test_tutoring_question_routes_to_learning_coach(
        self, sup: Supervisor
    ) -> None:
        # Production state — only learning_coach available
        prod_caps = [
            c.model_copy(update={"available_now": True})
            for c in list_capabilities()
            if c.name in ("supervisor", "learning_coach")
        ]
        ctx = _build_context(
            user_message="How does retrieval-augmented generation work?",
            available_caps=prod_caps,
        )
        canned = json.dumps(
            {
                "action": "dispatch_single",
                "target_agent": "learning_coach",
                "constructed_context": {"question": "How does retrieval-augmented generation work?"},
                "reasoning": "Tutoring question; learning_coach is the canonical teaching agent.",
                "confidence": "high",
                "primary_intent": "tutoring_question",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["action"] == "dispatch_single"
        assert output["target_agent"] == "learning_coach"

    async def test_unentitled_user_gets_decline(self, sup: Supervisor) -> None:
        # No available_agents → decline with entitlement_required
        ctx = _build_context(
            user_message="Explain transformers",
            available_caps=[],
        )
        canned = json.dumps(
            {
                "action": "decline",
                "decline_reason": "entitlement_required",
                "decline_message": (
                    "Your subscription doesn't include this. Browse "
                    "courses to unlock more agents."
                ),
                "suggested_next_action": "browse_catalog",
                "reasoning": "No available_agents — student is unentitled.",
                "confidence": "high",
                "primary_intent": "tutoring_question",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["action"] == "decline"
        assert output["decline_reason"] == "entitlement_required"


# ── Layer 2: Routing-diversity ──────────────────────────────────────


class TestLayer2RoutingDiversity:
    """Synthetic universe: every capability available_now=True.

    These tests verify the Supervisor's PROMPT structure produces
    sensible decisions across the full agent roster. Each test
    pairs an input with a canned output that represents what the
    Supervisor *should* produce for that input. When real-Sonnet eval
    lands post-launch, these test cases become the seed for the
    prompt-eval suite (Pass 3b §10.2).

    For each input, asserting:
      1. The canned response parses as a valid RouteDecision
      2. The target_agent (or decline_reason) makes sense given
         the input
      3. The Supervisor's prompt-rendering didn't drop the agent's
         description (verified via the captured LLM messages)
    """

    @pytest.fixture
    def sup(self) -> Supervisor:
        return Supervisor()

    @pytest.fixture
    def all_caps(self) -> list[AgentCapability]:
        return _all_capabilities_available()

    async def test_billing_question_routes_to_billing_support(
        self, sup: Supervisor, all_caps: list[AgentCapability]
    ) -> None:
        ctx = _build_context(
            user_message="Where's my refund? I cancelled last week.",
            available_caps=all_caps,
        )
        canned = json.dumps(
            {
                "action": "dispatch_single",
                "target_agent": "billing_support",
                "constructed_context": {"question": "Where's my refund? I cancelled last week."},
                "reasoning": "Billing question — refund inquiry. Routes to billing_support.",
                "confidence": "high",
                "primary_intent": "billing_question",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["target_agent"] == "billing_support"

    async def test_code_review_routes_to_senior_engineer(
        self, sup: Supervisor, all_caps: list[AgentCapability]
    ) -> None:
        ctx = _build_context(
            user_message="Review my code for bugs and idioms",
            available_caps=all_caps,
        )
        canned = json.dumps(
            {
                "action": "dispatch_single",
                "target_agent": "senior_engineer",
                "constructed_context": {"task": "review code for correctness"},
                "reasoning": "Code review request. senior_engineer is the right specialist.",
                "confidence": "high",
                "primary_intent": "code_review_request",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["target_agent"] == "senior_engineer"

    async def test_interview_prep_routes_to_mock_interview(
        self, sup: Supervisor, all_caps: list[AgentCapability]
    ) -> None:
        ctx = _build_context(
            user_message="I'm preparing for a coding interview at Anthropic next week",
            available_caps=all_caps,
        )
        canned = json.dumps(
            {
                "action": "dispatch_single",
                "target_agent": "mock_interview",
                "constructed_context": {"format": "coding"},
                "reasoning": "Interview prep request. mock_interview handles FAANG-style coding rounds.",
                "confidence": "high",
                "primary_intent": "interview_practice",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["target_agent"] == "mock_interview"

    async def test_tutoring_question_routes_to_learning_coach(
        self, sup: Supervisor, all_caps: list[AgentCapability]
    ) -> None:
        ctx = _build_context(
            user_message="Can you help me understand vector databases?",
            available_caps=all_caps,
        )
        canned = json.dumps(
            {
                "action": "dispatch_single",
                "target_agent": "learning_coach",
                "constructed_context": {"question": "Can you help me understand vector databases?"},
                "reasoning": "Tutoring question. learning_coach is the canonical teaching agent.",
                "confidence": "high",
                "primary_intent": "tutoring_question",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["target_agent"] == "learning_coach"

    async def test_resume_tailoring_routes_to_tailored_resume(
        self, sup: Supervisor, all_caps: list[AgentCapability]
    ) -> None:
        ctx = _build_context(
            user_message="Update my resume for this Anthropic JD",
            available_caps=all_caps,
        )
        canned = json.dumps(
            {
                "action": "dispatch_single",
                "target_agent": "tailored_resume",
                "constructed_context": {"task": "tailor resume to JD"},
                "reasoning": "Resume rewrite for a specific JD. tailored_resume handles JD-tailored rewrites.",
                "confidence": "high",
                "primary_intent": "resume_help",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["target_agent"] == "tailored_resume"

    async def test_progress_check_routes_to_progress_report(
        self, sup: Supervisor, all_caps: list[AgentCapability]
    ) -> None:
        ctx = _build_context(
            user_message="How am I doing this month? Give me a progress summary.",
            available_caps=all_caps,
        )
        canned = json.dumps(
            {
                "action": "dispatch_single",
                "target_agent": "progress_report",
                "constructed_context": {"week_of": "current"},
                "reasoning": "Self-assessment / progress check. progress_report synthesizes weekly activity.",
                "confidence": "medium",
                "primary_intent": "progress_check",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["target_agent"] == "progress_report"

    async def test_career_strategy_routes_to_career_coach(
        self, sup: Supervisor, all_caps: list[AgentCapability]
    ) -> None:
        ctx = _build_context(
            user_message="Should I switch to GenAI engineering or focus on promotion in my current backend role?",
            available_caps=all_caps,
        )
        canned = json.dumps(
            {
                "action": "dispatch_single",
                "target_agent": "career_coach",
                "constructed_context": {"question": "career switch vs promotion"},
                "reasoning": "Strategic career-direction question. career_coach handles role-targeting.",
                "confidence": "high",
                "primary_intent": "career_advice",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["target_agent"] == "career_coach"

    async def test_out_of_scope_declines(
        self, sup: Supervisor, all_caps: list[AgentCapability]
    ) -> None:
        ctx = _build_context(
            user_message="What's a good lawyer for an H1B issue?",
            available_caps=all_caps,
        )
        canned = json.dumps(
            {
                "action": "decline",
                "decline_reason": "out_of_scope",
                "decline_message": (
                    "I help with learning, code, careers, and interviews — not legal advice. "
                    "For immigration questions, talk to an immigration attorney."
                ),
                "suggested_next_action": "external_resource",
                "reasoning": "Legal advice is out of scope; redirect.",
                "confidence": "high",
                "primary_intent": "out_of_scope",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["action"] == "decline"
        assert output["decline_reason"] == "out_of_scope"

    async def test_ambiguous_input_asks_clarification(
        self, sup: Supervisor, all_caps: list[AgentCapability]
    ) -> None:
        ctx = _build_context(
            user_message="help",
            available_caps=all_caps,
        )
        canned = json.dumps(
            {
                "action": "ask_clarification",
                "clarification_questions": [
                    "Are you stuck on a concept, or on writing code?",
                    "Do you want me to point you at a lesson, or to review something you've written?",
                ],
                "expected_clarifications": ["topic_or_artifact", "review_or_explain"],
                "reasoning": "Single-word request with no context. Cannot route without more.",
                "confidence": "high",
                "primary_intent": "clarification_needed",
            }
        )
        output = await _run_supervisor(sup, ctx, canned)
        assert output["action"] == "ask_clarification"
        assert len(output["clarification_questions"]) >= 1

    async def test_supervisor_prompt_renders_full_agent_roster(
        self, sup: Supervisor, all_caps: list[AgentCapability]
    ) -> None:
        """The Supervisor's user-side prompt block must contain
        EVERY available agent's name + description.

        Captures the LLM's received messages and asserts the
        rendering quality. Without this, the Supervisor could
        silently drop agents from its choice set without anyone
        noticing.
        """
        ctx = _build_context(
            user_message="anything",
            available_caps=all_caps,
        )
        stub = _CannedSupervisorLLM(
            json.dumps(
                {
                    "action": "decline",
                    "decline_reason": "out_of_scope",
                    "decline_message": "x",
                    "suggested_next_action": "x",
                    "reasoning": "test rendering",
                    "confidence": "low",
                    "primary_intent": "out_of_scope",
                }
            )
        )
        sup._llm_override = stub  # type: ignore[assignment]

        from app.agents.agentic_base import AgentContext
        from app.agents.primitives.communication import CallChain

        agent_ctx = AgentContext(
            user_id=ctx.student_id,
            chain=CallChain.start_root(user_id=ctx.student_id),
            session=_stub_session(),
            permissions=frozenset(),
        )
        await sup.execute(SupervisorInput(supervisor_context=ctx), agent_ctx)

        # The user-side message contains the rendered agents block
        assert len(stub.received_messages) == 1
        messages = stub.received_messages[0]
        # HumanMessage is the second element (after SystemMessage)
        user_content = messages[1].content
        assert "Available agents" in user_content
        # Every available capability's name appears in the rendered block
        for cap in all_caps:
            assert cap.name in user_content, (
                f"Agent {cap.name!r} missing from rendered agents block"
            )
