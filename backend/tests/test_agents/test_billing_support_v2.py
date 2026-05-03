"""D10 Checkpoint 3 sign-off — phantom-escalation regression pin.

This file's full unit-test coverage (5 Pass 3b §7.1 failure classes,
schema validation, memory read/write) lands in Checkpoint 4 per
the migration deliverable spec. The phantom-escalation contract is
pinned NOW because committing the LLM-trusted-ticket-id behavior
and then fixing it next commit would create a git-history window
where the lie exists on main.

The contract:
  • If the LLM emits suggested_action="contact_support" AND
    escalation_ticket_id="FAKE-..." in its structured output,
    billing_support_v2 MUST dispatch escalate_to_human and replace
    the LLM's ticket id with the real student_inbox row id.
  • If escalate_to_human raises or returns an error, billing_support_v2
    MUST null the ticket_id and append a support-email fallback to
    the answer text. Be honest with the student rather than ship
    a phantom ticket.

Implemented by the `_dispatch_escalation_if_requested` helper
called from `BillingSupportAgent.run`. Tests use stub LLMs +
ToolExecutor to drive both paths deterministically without API
keys or a real Postgres.
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
