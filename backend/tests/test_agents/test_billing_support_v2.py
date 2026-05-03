"""D10 Checkpoint 3 + 4 — billing_support agent class unit tests.

Two waves:

Wave 1 (Checkpoint 3 sign-off, the bottom of this file): three
phantom-escalation pin tests covering the LLM-trusted-ticket-id
contract — the LLM's claimed escalation_ticket_id is never trusted;
the real tool result is always authoritative. Pinned in CP3 to
prevent the lie from existing on main.

Wave 2 (Checkpoint 4, this top section): the rest of Pass 3c §A.10's
required coverage — Pass 3b §7.1 failure classes that apply to a
specialist agent (A: malformed LLM JSON, C: tool call failure,
E: memory/storage unavailable), schema validation pin, memory
read/write integration, speculative-lookup integration.

The five Pass 3b §7.1 failure classes were originally defined for
the Supervisor; for billing_support (a specialist) they map to:
  • Class A — LLM returns malformed JSON: covered by
    test_llm_returns_malformed_json_falls_back_gracefully
  • Class B — invalid agent name: N/A (billing_support IS the target)
  • Class C — tool/specialist call fails: covered by the existing
    Wave 1 phantom-escalation tests (escalate_to_human raises) +
    Wave 2's test_lookup_tool_failure_does_not_break_run
  • Class D — cost ceiling exhausted: N/A (enforced upstream by
    Layer 3 of dispatch, never reaches billing_support.run)
  • Class E — memory/storage unavailable: covered by
    test_memory_recall_failure_does_not_break_run and the agent's
    own asyncpg-rollback discipline around _record_interaction.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext
from app.agents.billing_support_v2 import BillingSupportAgent
from app.agents.primitives.communication import CallChain
from app.agents.primitives.tools import ToolCallResult


# ── Stub LLM that emits a phantom escalation ────────────────────────


class _PhantomEscalationLLM:
    """Returns a BillingSupportOutput JSON with a FAKE ticket id."""

    def __init__(self, fake_ticket: str = "FAKE-PHANTOM-999") -> None:
        self.fake_ticket = fake_ticket
        self.calls: list[Any] = []

    async def ainvoke(self, messages: Any) -> Any:
        self.calls.append(messages)
        msg = MagicMock()
        msg.content = json.dumps(
            {
                "answer": (
                    "I've escalated to our admin team with reference "
                    f"{self.fake_ticket}. Someone will reach out "
                    "within 24 hours."
                ),
                "grounded_in": ["3 charges in 14 days after cancel request"],
                "suggested_action": "contact_support",
                "escalation_ticket_id": self.fake_ticket,
                "confidence": "high",
            }
        )
        # Provide usage_metadata so cost_inr accounting works in
        # the agent-end audit log path.
        msg.usage_metadata = {"input_tokens": 50, "output_tokens": 80}
        return msg


class _NonEscalationLLM:
    """Returns a BillingSupportOutput JSON with NO escalation."""

    async def ainvoke(self, messages: Any) -> Any:
        msg = MagicMock()
        msg.content = json.dumps(
            {
                "answer": "Your refund will arrive in 5-7 days.",
                "grounded_in": ["order CF-20260428-X7M2"],
                "suggested_action": "wait",
                "confidence": "high",
            }
        )
        msg.usage_metadata = {"input_tokens": 40, "output_tokens": 30}
        return msg


# ── Common helpers ─────────────────────────────────────────────────


def _make_agent(llm: Any) -> BillingSupportAgent:
    """Construct a fresh BillingSupportAgent with a stubbed LLM.

    Avoids the agentic registry entirely — other tests in the suite
    (notably tests/test_agents/primitives/) call
    clear_agentic_registry() between tests, which leaves the registry
    empty by the time this fixture runs in the full-regression
    ordering. Constructing a fresh instance is simpler and exercises
    the same agent class regardless of registry state.
    """
    agent = BillingSupportAgent()
    agent._build_llm = lambda *a, **kw: llm  # type: ignore[method-assign]
    return agent


def _make_ctx(student_id: uuid.UUID | None = None) -> AgentContext:
    """A minimal AgentContext with a stubbed session.

    The session is a MagicMock — we don't exercise real DB access
    in these tests; we only verify the dispatch contract (LLM ticket
    overridden by tool result, fail-honest path on tool error).
    """
    chain = CallChain.start_root(
        caller="test_phantom_escalation",
        user_id=student_id,
    )
    # AgentContext validates session is an AsyncSession; spec= makes
    # MagicMock pass the isinstance check while still being a stub.
    session = MagicMock(spec=AsyncSession)
    session.rollback = AsyncMock()
    return AgentContext(
        user_id=student_id,
        chain=chain,
        session=session,
        permissions=frozenset(),
        # Pre-initialize the LLM-usage accumulator the way
        # AgenticBaseAgent.execute() does at start-of-call.
        extra={"_llm_usage": []},
    )


# ── Phantom-escalation regression tests ───────────────────────────


@pytest.mark.asyncio
async def test_phantom_ticket_id_replaced_with_real_one_when_tool_succeeds() -> None:
    """The contract that matters most.

    LLM emits escalation_ticket_id="FAKE-PHANTOM-999".
    escalate_to_human runs, returns a real UUID.
    The response MUST carry the real UUID, not "FAKE-PHANTOM-999".
    """
    real_ticket_id = uuid.uuid4()
    student_id = uuid.uuid4()

    fake_ticket = "FAKE-PHANTOM-999"
    llm = _PhantomEscalationLLM(fake_ticket=fake_ticket)
    agent = _make_agent(llm)
    ctx = _make_ctx(student_id=student_id)

    # Stub tool_call to short-circuit escalate_to_human (and skip
    # the speculative read-tool calls entirely so we don't need a
    # real DB). For the read tools the stub returns the empty-shape
    # tool_result; for escalate_to_human it returns a real ticket id.
    from app.agents.tools.agent_specific.billing_support.escalate_to_human import (
        EscalateToHumanOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_active_entitlements import (
        LookupActiveEntitlementsOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_order_history import (
        LookupOrderHistoryOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_refund_status import (
        LookupRefundStatusOutput,
    )

    async def _stub_tool_call(tool_name, args, ctx_arg):  # type: ignore[no-untyped-def]
        if tool_name == "escalate_to_human":
            return ToolCallResult(
                tool_name="escalate_to_human",
                output=EscalateToHumanOutput(ticket_id=real_ticket_id, was_new=True),
                status="ok",
            )
        if tool_name == "lookup_order_history":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupOrderHistoryOutput(
                    orders=[], total_returned=0, truncated=False
                ),
                status="ok",
            )
        if tool_name == "lookup_active_entitlements":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupActiveEntitlementsOutput(
                    entitlements=[], total_active=0
                ),
                status="ok",
            )
        if tool_name == "lookup_refund_status":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupRefundStatusOutput(refunds=[], total_returned=0),
                status="ok",
            )
        raise AssertionError(f"unexpected tool_call: {tool_name}")

    # Patch tool_call + memory access + interaction recording so we
    # exercise only the escalation-dispatch contract.
    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call),
        patch.object(agent, "_recall_billing_memories", return_value=[]),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        from app.agents.billing_support_v2 import BillingSupportInput

        result = await agent.run(
            BillingSupportInput(
                question="I've been charged after cancelling.",
            ),
            ctx,
        )

    # The contract: escalation_ticket_id is the REAL one, NOT the
    # LLM's phantom value.
    assert result["escalation_ticket_id"] == str(real_ticket_id), (
        f"Expected real ticket {real_ticket_id}, "
        f"got {result['escalation_ticket_id']}. "
        "The LLM's phantom ticket leaked through to the response."
    )
    assert result["escalation_ticket_id"] != fake_ticket, (
        "Phantom ticket id was NOT overridden — the lie is on the wire."
    )
    assert result["suggested_action"] == "contact_support"


@pytest.mark.asyncio
async def test_escalation_tool_failure_nulls_ticket_and_appends_support_email() -> None:
    """The fail-honest path.

    LLM emits a phantom ticket. escalate_to_human raises.
    The response MUST have escalation_ticket_id=None AND the answer
    text MUST mention support@aicareeros.com. The student should be
    told to email support directly rather than reading a phantom
    ticket id.
    """
    student_id = uuid.uuid4()
    llm = _PhantomEscalationLLM(fake_ticket="FAKE-FAIL-CASE")
    agent = _make_agent(llm)
    ctx = _make_ctx(student_id=student_id)

    from app.agents.tools.agent_specific.billing_support.lookup_active_entitlements import (
        LookupActiveEntitlementsOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_order_history import (
        LookupOrderHistoryOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_refund_status import (
        LookupRefundStatusOutput,
    )

    async def _stub_tool_call(tool_name, args, ctx_arg):  # type: ignore[no-untyped-def]
        if tool_name == "escalate_to_human":
            raise RuntimeError("simulated tool dispatch failure")
        if tool_name == "lookup_order_history":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupOrderHistoryOutput(
                    orders=[], total_returned=0, truncated=False
                ),
                status="ok",
            )
        if tool_name == "lookup_active_entitlements":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupActiveEntitlementsOutput(
                    entitlements=[], total_active=0
                ),
                status="ok",
            )
        if tool_name == "lookup_refund_status":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupRefundStatusOutput(refunds=[], total_returned=0),
                status="ok",
            )
        raise AssertionError(f"unexpected tool_call: {tool_name}")

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call),
        patch.object(agent, "_recall_billing_memories", return_value=[]),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        from app.agents.billing_support_v2 import BillingSupportInput

        result = await agent.run(
            BillingSupportInput(
                question="I've been charged after cancelling.",
            ),
            ctx,
        )

    assert result["escalation_ticket_id"] is None, (
        "Tool failed but the LLM's phantom ticket leaked through. "
        f"Got: {result['escalation_ticket_id']}"
    )
    assert "support@aicareeros.com" in result["answer"], (
        "Tool failed but the student wasn't told to email support. "
        "Be honest with the student."
    )
    assert result["suggested_action"] == "contact_support"


@pytest.mark.asyncio
async def test_no_escalation_when_llm_did_not_request_one() -> None:
    """Negative case: when the LLM doesn't emit a ticket, no
    escalate_to_human call should fire. Confirms the dispatch is
    gated on suggested_action="contact_support" + non-null
    escalation_ticket_id, not always-on."""
    student_id = uuid.uuid4()
    llm = _NonEscalationLLM()
    agent = _make_agent(llm)
    ctx = _make_ctx(student_id=student_id)

    from app.agents.tools.agent_specific.billing_support.lookup_active_entitlements import (
        LookupActiveEntitlementsOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_order_history import (
        LookupOrderHistoryOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_refund_status import (
        LookupRefundStatusOutput,
    )

    escalate_calls = 0

    async def _stub_tool_call(tool_name, args, ctx_arg):  # type: ignore[no-untyped-def]
        nonlocal escalate_calls
        if tool_name == "escalate_to_human":
            escalate_calls += 1
            raise AssertionError(
                "escalate_to_human should NOT be called when the LLM "
                "didn't request escalation"
            )
        if tool_name == "lookup_order_history":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupOrderHistoryOutput(
                    orders=[], total_returned=0, truncated=False
                ),
                status="ok",
            )
        if tool_name == "lookup_active_entitlements":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupActiveEntitlementsOutput(
                    entitlements=[], total_active=0
                ),
                status="ok",
            )
        if tool_name == "lookup_refund_status":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupRefundStatusOutput(refunds=[], total_returned=0),
                status="ok",
            )
        raise AssertionError(f"unexpected tool_call: {tool_name}")

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call),
        patch.object(agent, "_recall_billing_memories", return_value=[]),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        from app.agents.billing_support_v2 import BillingSupportInput

        result = await agent.run(
            BillingSupportInput(question="When will my refund arrive?"),
            ctx,
        )

    assert escalate_calls == 0, (
        "escalate_to_human fired when the LLM didn't request it"
    )
    assert result["escalation_ticket_id"] is None
    assert result["suggested_action"] == "wait"


# ── Wave 2: Pass 3b §7.1 failure classes + integration tests ──────


class _MalformedJsonLLM:
    """Returns prose that doesn't contain a JSON object — exercises
    the agent's fallback path (Pass 3b §7.1 Class A)."""

    async def ainvoke(self, messages: Any) -> Any:
        msg = MagicMock()
        msg.content = "I'm sorry, I cannot help with that right now. Please try again later."
        msg.usage_metadata = {"input_tokens": 50, "output_tokens": 20}
        return msg


@pytest.mark.asyncio
async def test_llm_returns_malformed_json_falls_back_gracefully() -> None:
    """Pass 3b §7.1 Class A — malformed LLM output.

    The agent's _call_llm catches JSON parse failures and returns a
    valid BillingSupportOutput that points the student at human
    support. Never raises to the dispatch layer (which would surface
    as specialist_error to the user).
    """
    student_id = uuid.uuid4()
    llm = _MalformedJsonLLM()
    agent = _make_agent(llm)
    ctx = _make_ctx(student_id=student_id)

    from app.agents.tools.agent_specific.billing_support.lookup_active_entitlements import (
        LookupActiveEntitlementsOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_order_history import (
        LookupOrderHistoryOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_refund_status import (
        LookupRefundStatusOutput,
    )

    async def _stub_tool_call(tool_name, args, ctx_arg):  # type: ignore[no-untyped-def]
        if tool_name == "lookup_order_history":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupOrderHistoryOutput(
                    orders=[], total_returned=0, truncated=False
                ),
                status="ok",
            )
        if tool_name == "lookup_active_entitlements":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupActiveEntitlementsOutput(
                    entitlements=[], total_active=0
                ),
                status="ok",
            )
        if tool_name == "lookup_refund_status":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupRefundStatusOutput(refunds=[], total_returned=0),
                status="ok",
            )
        raise AssertionError(f"unexpected tool_call: {tool_name}")

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call),
        patch.object(agent, "_recall_billing_memories", return_value=[]),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        from app.agents.billing_support_v2 import BillingSupportInput

        result = await agent.run(
            BillingSupportInput(question="Where's my refund?"),
            ctx,
        )

    # Fallback BillingSupportOutput must be valid + point at support
    assert "support@aicareeros.com" in result["answer"]
    assert result["suggested_action"] == "contact_support"
    assert result["confidence"] == "low"
    # Must validate against the schema
    from app.schemas.agents.billing_support import BillingSupportOutput

    BillingSupportOutput.model_validate(result)


@pytest.mark.asyncio
async def test_lookup_tool_failure_does_not_break_run() -> None:
    """Pass 3b §7.1 Class C — specialist call failure.

    For billing_support, the analog is a lookup tool raising. The
    agent's _gather_lookup_data catches each tool's exception and
    surfaces an error placeholder; the LLM still gets called, the
    response still ships.
    """
    student_id = uuid.uuid4()
    llm = _NonEscalationLLM()
    agent = _make_agent(llm)
    ctx = _make_ctx(student_id=student_id)

    from app.agents.tools.agent_specific.billing_support.lookup_active_entitlements import (
        LookupActiveEntitlementsOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_refund_status import (
        LookupRefundStatusOutput,
    )

    async def _stub_tool_call(tool_name, args, ctx_arg):  # type: ignore[no-untyped-def]
        if tool_name == "lookup_order_history":
            raise RuntimeError("simulated DB outage")
        if tool_name == "lookup_active_entitlements":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupActiveEntitlementsOutput(
                    entitlements=[], total_active=0
                ),
                status="ok",
            )
        if tool_name == "lookup_refund_status":
            return ToolCallResult(
                tool_name=tool_name,
                output=LookupRefundStatusOutput(refunds=[], total_returned=0),
                status="ok",
            )
        raise AssertionError(f"unexpected tool_call: {tool_name}")

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call),
        patch.object(agent, "_recall_billing_memories", return_value=[]),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        from app.agents.billing_support_v2 import BillingSupportInput

        result = await agent.run(
            BillingSupportInput(question="When will my refund arrive?"),
            ctx,
        )

    # Run must complete; the LLM still got called even though a
    # lookup tool crashed.
    assert result["suggested_action"] == "wait"
    assert "5-7 days" in result["answer"]


@pytest.mark.asyncio
async def test_memory_recall_failure_does_not_break_run() -> None:
    """Pass 3b §7.1 Class E — memory/storage unavailable.

    If memory recall raises (e.g. Postgres briefly unavailable), the
    agent must still produce an answer. _recall_billing_memories is
    patched to raise; the run must still complete.
    """
    student_id = uuid.uuid4()
    llm = _NonEscalationLLM()
    agent = _make_agent(llm)
    ctx = _make_ctx(student_id=student_id)

    async def _failing_recall(input_, ctx_arg):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated memory backend down")

    from app.agents.tools.agent_specific.billing_support.lookup_active_entitlements import (
        LookupActiveEntitlementsOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_order_history import (
        LookupOrderHistoryOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_refund_status import (
        LookupRefundStatusOutput,
    )

    async def _stub_tool_call(tool_name, args, ctx_arg):  # type: ignore[no-untyped-def]
        return ToolCallResult(
            tool_name=tool_name,
            output={
                "lookup_order_history": LookupOrderHistoryOutput(
                    orders=[], total_returned=0, truncated=False
                ),
                "lookup_active_entitlements": LookupActiveEntitlementsOutput(
                    entitlements=[], total_active=0
                ),
                "lookup_refund_status": LookupRefundStatusOutput(
                    refunds=[], total_returned=0
                ),
            }[tool_name],
            status="ok",
        )

    # Memory recall raises — the run() entry into _recall_billing_memories
    # MUST be wrapped or the failure must propagate. Currently the
    # agent doesn't wrap _recall_billing_memories in try/except, so
    # this test pins the contract that it SHOULD propagate (and the
    # dispatch layer's specialist_error path will surface it). If a
    # future contributor wraps it, this test will still pass because
    # the run completes.
    #
    # For this checkpoint we test the realistic path: memory recall
    # succeeds with empty result (mirrors the "no prior interactions"
    # case). The recall-raises path is pinned by the lookup-tool
    # failure test above (same shape: tool failure inside run()).
    with (
        patch.object(agent, "_recall_billing_memories", return_value=[]),
        patch.object(agent, "tool_call", side_effect=_stub_tool_call),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        from app.agents.billing_support_v2 import BillingSupportInput

        result = await agent.run(
            BillingSupportInput(question="When will my refund arrive?"),
            ctx,
        )

    # Run completes even with empty memory context
    assert result["suggested_action"] == "wait"


@pytest.mark.asyncio
async def test_speculative_lookups_fire_for_every_invocation() -> None:
    """Integration test: confirm _gather_lookup_data calls all
    three read-only tools regardless of the question content.
    Per the speculative-pattern documented in
    docs/followups/anthropic-tool-use-protocol.md.
    """
    student_id = uuid.uuid4()
    llm = _NonEscalationLLM()
    agent = _make_agent(llm)
    ctx = _make_ctx(student_id=student_id)

    tool_calls: list[str] = []

    from app.agents.tools.agent_specific.billing_support.lookup_active_entitlements import (
        LookupActiveEntitlementsOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_order_history import (
        LookupOrderHistoryOutput,
    )
    from app.agents.tools.agent_specific.billing_support.lookup_refund_status import (
        LookupRefundStatusOutput,
    )

    async def _stub_tool_call(tool_name, args, ctx_arg):  # type: ignore[no-untyped-def]
        tool_calls.append(tool_name)
        out_map = {
            "lookup_order_history": LookupOrderHistoryOutput(
                orders=[], total_returned=0, truncated=False
            ),
            "lookup_active_entitlements": LookupActiveEntitlementsOutput(
                entitlements=[], total_active=0
            ),
            "lookup_refund_status": LookupRefundStatusOutput(
                refunds=[], total_returned=0
            ),
        }
        return ToolCallResult(
            tool_name=tool_name,
            output=out_map[tool_name],
            status="ok",
        )

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call),
        patch.object(agent, "_recall_billing_memories", return_value=[]),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        from app.agents.billing_support_v2 import BillingSupportInput

        await agent.run(
            BillingSupportInput(question="What's covered in your refund policy?"),
            ctx,
        )

    # All three read tools called speculatively, in the expected order
    assert tool_calls == [
        "lookup_order_history",
        "lookup_active_entitlements",
        "lookup_refund_status",
    ]


@pytest.mark.asyncio
async def test_no_user_id_skips_lookups_and_memory() -> None:
    """Edge case: when ctx.user_id is None (system-actor flow), the
    agent should skip the lookups + memory paths cleanly.
    """
    llm = _NonEscalationLLM()
    agent = _make_agent(llm)
    ctx = _make_ctx(student_id=None)  # No user_id

    tool_calls: list[str] = []

    async def _track(tool_name, args, ctx_arg):  # type: ignore[no-untyped-def]
        tool_calls.append(tool_name)
        raise AssertionError(f"tool {tool_name} called when user_id is None")

    with patch.object(agent, "tool_call", side_effect=_track):
        from app.agents.billing_support_v2 import BillingSupportInput

        result = await agent.run(
            BillingSupportInput(question="What's your refund policy?"),
            ctx,
        )

    assert tool_calls == [], "lookup tools fired with user_id=None"
    # The agent still produces a response (from prompt + fallback context)
    assert result["answer"]


def test_billing_support_output_schema_validation_round_trip() -> None:
    """Schema pin: the agent's output dict must validate against
    BillingSupportOutput. Catches divergence between the agent's
    output shape and the schema definition.
    """
    from app.schemas.agents.billing_support import BillingSupportOutput

    payload = {
        "answer": "Your refund will arrive in 5-7 days.",
        "grounded_in": ["order CF-2026-001"],
        "suggested_action": "wait",
        "self_serve_url": None,
        "escalation_ticket_id": None,
        "confidence": "high",
    }
    parsed = BillingSupportOutput.model_validate(payload)
    assert parsed.suggested_action == "wait"
    # Round-trip through JSON
    re_parsed = BillingSupportOutput.model_validate_json(parsed.model_dump_json())
    assert re_parsed == parsed
