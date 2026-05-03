"""D9 / Pass 3b §2 — AgenticOrchestratorService.

The replacement for AgentOrchestratorService for the new canonical
endpoint /api/v1/agentic/{flow}/chat. Sequence per Pass 3b §2:

  1. Compute SupervisorContext from request + DB + Redis snapshot
  2. Run input safety scan (Layer 1+2+3 of safety primitive)
  3. Invoke Supervisor → RouteDecision
  4. Dispatch via dispatch_single / dispatch_chain (which run Layer 3
     entitlement re-check and invoke specialists)
  5. Run output safety scan
  6. Persist conversation turn → return response

D9 Checkpoint 3 ships this service standalone — the canonical
endpoint that wires it to HTTP comes in Checkpoint 4.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capability import filter_capabilities_for_user, list_capabilities
from app.agents.dispatch import (
    dispatch_chain,
    dispatch_single,
    process_handoff,
)
from app.agents.primitives.communication import CallChain
from app.agents.primitives.safety import SafetyGate, get_default_gate
from app.agents.supervisor import Supervisor, SupervisorInput
from app.schemas.entitlement import EntitlementContext
from app.schemas.safety import SafetyVerdict
from app.schemas.supervisor import (
    AgentResult,
    AttachmentRef,
    ConversationTurn,
    EntitlementSummary,
    RouteDecision,
    SupervisorContext,
)
from app.services.agentic_snapshot_service import get_snapshot
from app.services.entitlement_service import compute_active_entitlements

log = structlog.get_logger().bind(layer="agentic_orchestrator")


class AgenticOrchestratorService:
    """The orchestration entry point for the canonical agentic endpoint.

    Stateless; each call constructs its own request_id and threads it
    through the call chain. Singleton-friendly (no per-call state on
    the instance).

    Test injection points:
      - `safety_gate`: override the SafetyGate (e.g. with a stubbed
        gate that always returns allow)
      - `supervisor_factory`: override the Supervisor instantiation
        (e.g. inject a stubbed LLM via Supervisor._llm_override)
    """

    def __init__(
        self,
        *,
        safety_gate: SafetyGate | None = None,
        supervisor: Supervisor | None = None,
    ) -> None:
        # Default singleton — safe across requests because both are
        # stateless / process-scoped (gate caches Presidio; Supervisor
        # caches its prompt). Tests pass overrides.
        self._safety_gate = safety_gate or get_default_gate()
        self._supervisor = supervisor or Supervisor()

    # ── Public entry point ──────────────────────────────────────────

    async def process_request(
        self,
        *,
        db: AsyncSession,
        student_id: uuid.UUID,
        actor_id: uuid.UUID,
        actor_role: str,
        user_message: str,
        conversation_id: uuid.UUID | None = None,
        attachments: list[AttachmentRef] | None = None,
        flow: str = "default",
        # Pre-computed entitlement context (Layer 1 already validated).
        # The dependency that computed this would normally be injected
        # by the FastAPI route; passing in lets tests skip the route.
        entitlement_ctx: EntitlementContext | None = None,
    ) -> "OrchestratorResult":
        """End-to-end agentic request handling.

        Returns OrchestratorResult — a structured response the
        endpoint serializes to JSON.
        """
        request_id = uuid.uuid4()
        conversation_id = conversation_id or uuid.uuid4()
        start = time.perf_counter()

        # Step 1: ensure we have an EntitlementContext. If the caller
        # didn't pre-compute one (Layer 1 should), do it here.
        if entitlement_ctx is None:
            entitlement_ctx = await compute_active_entitlements(db, student_id)

        # Defensive: if we got here with an empty context, the
        # canonical endpoint's Layer 1 dependency should have
        # short-circuited with 402. Mirror that decline as a structured
        # OrchestratorResult so callers that bypass the route (tests,
        # admin tools) see consistent behavior.
        if entitlement_ctx.is_empty():
            return OrchestratorResult(
                request_id=request_id,
                conversation_id=conversation_id,
                response_text=(
                    "Your AICareerOS subscription has expired or you "
                    "haven't purchased a course yet. Browse available "
                    "courses to continue."
                ),
                target_agent=None,
                blocked=True,
                block_reason="no_active_entitlement",
                duration_ms=int((time.perf_counter() - start) * 1000),
                cost_inr=Decimal("0"),
            )

        # Step 2: input safety scan.
        input_verdict = await self._safety_gate.scan_input(
            user_message,
            student_id=student_id,
            agent_name="supervisor",
        )
        if input_verdict.decision == "block":
            return OrchestratorResult(
                request_id=request_id,
                conversation_id=conversation_id,
                response_text=(
                    input_verdict.user_facing_message
                    or "Your message couldn't be processed."
                ),
                target_agent=None,
                blocked=True,
                block_reason=f"safety_input:{input_verdict.severity_max}",
                safety_verdict_in=input_verdict,
                duration_ms=int((time.perf_counter() - start) * 1000),
                cost_inr=Decimal("0"),
            )

        # If redacted, swap in the redacted text for downstream use.
        effective_message = (
            input_verdict.redacted_text
            if input_verdict.decision == "redact" and input_verdict.redacted_text
            else user_message
        )

        # Step 3: build SupervisorContext.
        sup_ctx = await self._build_supervisor_context(
            db=db,
            student_id=student_id,
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            conversation_id=conversation_id,
            user_message=effective_message,
            attachments=attachments or [],
            entitlement_ctx=entitlement_ctx,
        )

        # Step 4: invoke the Supervisor.
        sup_input = SupervisorInput(supervisor_context=sup_ctx)
        chain = CallChain.start_root(user_id=student_id, caller="orchestrator")

        # The Supervisor doesn't need a DB session for its own logic
        # but AgentContext requires one (for the inter-agent primitives
        # the Supervisor doesn't actually use — but the type contract
        # demands it).
        from app.agents.agentic_base import AgentContext as _Ctx

        sup_agent_ctx = _Ctx(
            user_id=student_id,
            chain=chain,
            session=db,
            permissions=frozenset(),
            extra={"request_id": str(request_id), "actor_role": actor_role},
        )
        sup_result = await self._supervisor.execute(sup_input, sup_agent_ctx)

        # The Supervisor's output is a RouteDecision dict (per its
        # run() contract). Validate it back into the structured type.
        try:
            decision = RouteDecision.model_validate(sup_result.output)
        except Exception as exc:  # noqa: BLE001 — defensive; supervisor.py builds a fallback already
            log.warning(
                "orchestrator.invalid_supervisor_output",
                error=str(exc),
                request_id=str(request_id),
            )
            return OrchestratorResult(
                request_id=request_id,
                conversation_id=conversation_id,
                response_text=(
                    "I had trouble routing your request — could you "
                    "rephrase?"
                ),
                target_agent=None,
                blocked=True,
                block_reason="supervisor_output_invalid",
                safety_verdict_in=input_verdict,
                duration_ms=int((time.perf_counter() - start) * 1000),
                cost_inr=Decimal("0"),
            )

        # Step 5: dispatch.
        agent_result = await self._execute_decision(
            decision=decision,
            sup_ctx=sup_ctx,
            db=db,
            chain=chain,
            entitlement_ctx=entitlement_ctx,
        )

        # Step 6: output safety scan.
        output_text = agent_result.output_text or ""
        output_verdict: SafetyVerdict | None = None
        if output_text and not agent_result.blocked:
            output_verdict = await self._safety_gate.scan_output(
                output_text,
                student_id=student_id,
                agent_name=agent_result.agent_name,
            )
            if output_verdict.decision == "block":
                # Replace the agent's output with the gate's block
                # message; keep the original logged in agent_actions.
                agent_result.output_text = (
                    output_verdict.user_facing_message
                    or "I had to stop my response."
                )
                agent_result.blocked = True
                agent_result.block_reason = (
                    f"safety_output:{output_verdict.severity_max}"
                )
            elif output_verdict.decision == "redact" and output_verdict.redacted_text:
                agent_result.output_text = output_verdict.redacted_text
                agent_result.redacted = True

        return OrchestratorResult(
            request_id=request_id,
            conversation_id=conversation_id,
            response_text=agent_result.output_text or "",
            target_agent=agent_result.agent_name,
            blocked=agent_result.blocked,
            block_reason=agent_result.block_reason,
            decision=decision,
            agent_result=agent_result,
            safety_verdict_in=input_verdict,
            safety_verdict_out=output_verdict,
            duration_ms=int((time.perf_counter() - start) * 1000),
            cost_inr=agent_result.cost_inr,
        )

    # ── Helpers ─────────────────────────────────────────────────────

    async def _build_supervisor_context(
        self,
        *,
        db: AsyncSession,
        student_id: uuid.UUID,
        actor_id: uuid.UUID,
        actor_role: str,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_message: str,
        attachments: list[AttachmentRef],
        entitlement_ctx: EntitlementContext,
    ) -> SupervisorContext:
        """Construct the SupervisorContext for one request.

        Pulls:
          - StudentSnapshot from Redis cache (5-min TTL)
          - Available capabilities, filtered by tier + entitlement
          - EntitlementSummary projection
          - Conversation thread (out of D9 scope to load full history;
            supplied empty by default — Checkpoint 4 wires the
            conversation_thread_service)
          - Recent agent actions (out of D9 scope; supplied empty)
        """
        snapshot = await get_snapshot(db, student_id)

        all_caps = list_capabilities()
        available = filter_capabilities_for_user(all_caps, entitlement_ctx)

        ent_summaries = [
            EntitlementSummary(
                course_id=e.course_id,
                course_slug=e.course_slug,
                tier=e.tier,
                granted_at=e.granted_at,
                expires_at=e.expires_at,
            )
            for e in entitlement_ctx.active_entitlements
        ]

        return SupervisorContext(
            student_id=student_id,
            request_id=request_id,
            conversation_id=conversation_id,
            actor_id=actor_id,
            actor_role=actor_role,  # type: ignore[arg-type]
            user_message=user_message,
            attachments=attachments,
            entitlements=ent_summaries,
            rate_limit_remaining=entitlement_ctx.rate_limit_state,
            cost_budget_remaining_today_inr=(
                entitlement_ctx.cost_budget_remaining_today_inr
            ),
            student_snapshot=snapshot,
            thread_summary=None,
            recent_turns=[],  # Checkpoint 4 wires conversation history loading
            recent_agent_actions=[],  # Checkpoint 4 wires the awareness window
            available_agents=available,
            available_tools=[],  # Supervisor's own read-only tools — v2
        )

    async def _execute_decision(
        self,
        *,
        decision: RouteDecision,
        sup_ctx: SupervisorContext,
        db: AsyncSession,
        chain: CallChain,
        entitlement_ctx: EntitlementContext,
    ) -> AgentResult:
        """Execute a RouteDecision via dispatch_single / dispatch_chain
        / decline message."""
        if decision.action == "decline":
            return AgentResult(
                agent_name="supervisor",
                output_text=(
                    decision.decline_message
                    or "Your request couldn't be processed."
                ),
                blocked=True,
                block_reason=f"supervisor_decline:{decision.decline_reason}",
                duration_ms=0,
                cost_inr=Decimal("0"),
            )

        if decision.action == "ask_clarification":
            questions = decision.clarification_questions or []
            text = "\n".join(f"- {q}" for q in questions)
            return AgentResult(
                agent_name="supervisor",
                output_text=(
                    "I need a bit more context before I can help:\n" + text
                ),
                blocked=False,
                duration_ms=0,
                cost_inr=Decimal("0"),
            )

        if decision.action == "escalate":
            # Pass 3b §3.2: escalate writes to student_inbox via the
            # primitives. Wiring that path into D9 is a small follow-up;
            # for v1 we surface a polite message and log.
            log.info(
                "orchestrator.escalate",
                reason=decision.escalation_reason,
                request_id=str(sup_ctx.request_id),
            )
            return AgentResult(
                agent_name="supervisor",
                output_text=(
                    "I've passed your request along to the team — "
                    "we'll follow up soon."
                ),
                blocked=False,
                duration_ms=0,
                cost_inr=Decimal("0"),
            )

        if decision.action == "dispatch_single":
            result = await dispatch_single(
                decision,
                sup_ctx,
                db=db,
                chain=chain,
                fresh_ctx=entitlement_ctx,
            )
            # Process mandatory handoff if specialist returned one.
            if result.handoff_request is not None:
                handoff_result = await process_handoff(
                    result.handoff_request,
                    sup_ctx,
                    db=db,
                    chain=chain,
                    depth_remaining=1,
                )
                if handoff_result is not None:
                    return handoff_result
            return result

        if decision.action == "dispatch_chain":
            chain_result = await dispatch_chain(
                decision,
                sup_ctx,
                db=db,
                chain=chain,
            )
            # Project the chain result back into AgentResult for the
            # caller. The composed_response is the user-facing string.
            return AgentResult(
                agent_name="chain",
                output_text=chain_result.composed_response,
                output_summary=(
                    f"chain of {len(chain_result.steps)} steps "
                    f"({'aborted' if chain_result.aborted_at_step else 'complete'})"
                ),
                blocked=chain_result.aborted_at_step is not None,
                block_reason=chain_result.abort_reason,
                duration_ms=chain_result.total_duration_ms,
                cost_inr=chain_result.total_cost_inr,
            )

        # Should be unreachable per the RouteDecision Literal type.
        log.warning(
            "orchestrator.unknown_decision_action",
            action=decision.action,
            request_id=str(sup_ctx.request_id),
        )
        return AgentResult(
            agent_name="supervisor",
            output_text="I had trouble routing that — could you rephrase?",
            blocked=True,
            block_reason="unknown_action",
            duration_ms=0,
            cost_inr=Decimal("0"),
        )


# ── Result ──────────────────────────────────────────────────────────


from pydantic import BaseModel, Field  # noqa: E402


class OrchestratorResult(BaseModel):
    """The structured response returned to the canonical endpoint."""

    request_id: uuid.UUID
    conversation_id: uuid.UUID
    response_text: str
    target_agent: str | None
    blocked: bool = False
    block_reason: str | None = None
    decision: RouteDecision | None = None
    agent_result: AgentResult | None = None
    safety_verdict_in: SafetyVerdict | None = None
    safety_verdict_out: SafetyVerdict | None = None
    duration_ms: int
    cost_inr: Decimal = Field(default_factory=lambda: Decimal("0"))


__all__ = ["AgenticOrchestratorService", "OrchestratorResult"]
