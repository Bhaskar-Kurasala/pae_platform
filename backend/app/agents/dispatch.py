"""D9 / Pass 3b §5 — dispatch layer: single, chain, handoff.

The Supervisor decides; the dispatch layer executes. This separation
matters for testability (Supervisor unit tests work without specialists;
dispatch unit tests work without an LLM) and for safety (every
dispatch path runs the Layer 3 entitlement re-check from Pass 3f §A.3).

Three entry points:
  • dispatch_single  — execute a single-agent decision
  • dispatch_chain   — execute a multi-step chain plan with state passing
  • process_handoff  — re-invoke the Supervisor when a specialist asks
                       to hand off to another agent

All three:
  1. Re-fetch a fresh EntitlementContext (Layer 3 race-window
     protection)
  2. Validate the target agent is registered AND available
  3. Validate the user's tier admits this agent
  4. Pre-charge cost-budget check before invoking
  5. Convert specialist output to AgentResult
  6. Surface handoff_request if the specialist returned one
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capability import filter_capabilities_for_user, get_capability
from app.agents.primitives.communication import (
    CallChain,
    call_agent,
)
from app.schemas.entitlement import EntitlementContext
from app.schemas.supervisor import (
    AgentResult,
    ChainResult,
    ChainStep,
    HandoffRequest,
    RouteDecision,
    SupervisorContext,
)

log = structlog.get_logger().bind(layer="dispatch")


# Default specialist timeout. Pass 3b §5.1 references DEFAULT_SPECIALIST_TIMEOUT_MS.
DEFAULT_SPECIALIST_TIMEOUT_MS = 30_000

# When the Supervisor decision references an unavailable agent (rate-
# limited, retired, hallucinated), we fall back to learning_coach.
# Pass 3b §7.1 Failure Class B / §7.1 Failure Class A.
DEFAULT_FALLBACK_AGENT = "learning_coach"


# Decline messages for each Layer 3 reason. Templated, not LLM-
# generated, to keep rejection latency tight.
_DECLINE_MESSAGES: dict[str, str] = {
    "agent_not_in_tier": (
        "That feature isn't included in your current plan. Browse "
        "available courses to unlock more agents."
    ),
    "agent_unavailable": (
        "That feature is temporarily unavailable. Please try again "
        "in a few minutes, or rephrase your request."
    ),
    "agent_unknown": (
        "I couldn't reach the right specialist for that request. "
        "Could you rephrase what you need?"
    ),
    "cost_exhausted": (
        "You've used today's allowance for AI agent calls. The cap "
        "resets at midnight UTC."
    ),
    "entitlement_revoked": (
        "Your subscription was just refunded — that means your "
        "access to AI agents has ended. If this was unexpected, "
        "you can browse courses to re-enroll, or contact billing."
    ),
}


def _decline_result(
    target_agent: str,
    reason: str,
) -> AgentResult:
    """Build an AgentResult representing a Layer 3 decline.

    Used when the dispatch layer rejects a Supervisor decision after
    Layer 3 re-check — the Supervisor was correct at decision time
    but state changed mid-flight (refund, rate limit, cost ceiling).
    """
    return AgentResult(
        agent_name=target_agent,
        output_text=_DECLINE_MESSAGES.get(
            reason, "Request couldn't be processed."
        ),
        blocked=True,
        block_reason=reason,
        duration_ms=0,
        cost_inr=Decimal("0"),
    )


async def _layer3_check(
    db: AsyncSession,
    user_id: uuid.UUID,
    target_agent: str,
    *,
    fresh_ctx: EntitlementContext | None = None,
) -> tuple[bool, str | None, EntitlementContext]:
    """Layer 3 fresh entitlement re-check.

    Returns (allowed, reason_if_denied, fresh_ctx). The fresh_ctx is
    either re-fetched here or passed in by the caller (for chain
    dispatches that want to share one re-check across all steps).

    Pass 3f §A.3: catches three race conditions:
      • Entitlement revoked between Supervisor decision and dispatch
      • Free-tier window expired mid-request
      • Cost ceiling crossed mid-chain
    """
    from app.services.entitlement_service import compute_active_entitlements

    if fresh_ctx is None:
        fresh_ctx = await compute_active_entitlements(db, user_id)

    # Empty context → entitlement was revoked since Layer 1 passed.
    if fresh_ctx.is_empty():
        return (False, "entitlement_revoked", fresh_ctx)

    capability = get_capability(target_agent)
    if capability is None:
        return (False, "agent_unknown", fresh_ctx)

    # Tier + allow-list check.
    allowed, reason = fresh_ctx.can_invoke(capability)
    if not allowed:
        return (False, reason or "agent_not_in_tier", fresh_ctx)

    if not capability.available_now:
        return (False, "agent_unavailable", fresh_ctx)

    # Cost-budget pre-check: would this call push us over today's
    # ceiling? Compare against the agent's typical_cost_inr; if the
    # actual call costs more, the next call hits cost_exhausted (one
    # trailing call after exhaustion is acceptable per Pass 3f §D.4).
    if (
        fresh_ctx.cost_budget_remaining_today_inr
        < capability.typical_cost_inr
    ):
        return (False, "cost_exhausted", fresh_ctx)

    return (True, None, fresh_ctx)


# ── Single-agent dispatch ──────────────────────────────────────────


async def dispatch_single(
    decision: RouteDecision,
    ctx: SupervisorContext,
    *,
    db: AsyncSession,
    chain: CallChain,
    fresh_ctx: EntitlementContext | None = None,
    fallback_on_unavailable: bool = True,
) -> AgentResult:
    """Execute a `dispatch_single` RouteDecision.

    Sequence:
      1. Layer 3 entitlement re-check (Pass 3f §A.3)
      2. Build AgentInput payload from decision.constructed_context
      3. Invoke via call_agent (D4 primitive)
      4. Convert result to AgentResult
      5. Surface handoff_request if specialist returned one

    `fallback_on_unavailable` controls behavior when Layer 3 rejects
    on `agent_unavailable` or `agent_unknown` — defaults True (fall
    back to learning_coach per Pass 3b §7.1 Failure Class A/B). Set
    False from chain dispatch where the chain plan's `on_failure`
    policy governs.
    """
    target = decision.target_agent
    if target is None:
        log.warning(
            "dispatch.single.missing_target",
            request_id=str(ctx.request_id),
        )
        if fallback_on_unavailable:
            target = DEFAULT_FALLBACK_AGENT
        else:
            return _decline_result("", "agent_unknown")

    allowed, reason, _ = await _layer3_check(
        db, ctx.student_id, target, fresh_ctx=fresh_ctx
    )

    if not allowed:
        # Decide whether to decline or fall back.
        # • entitlement_revoked / cost_exhausted: ALWAYS decline (the
        #   user genuinely can't make ANY agent call right now)
        # • agent_unavailable / agent_unknown: fall back if allowed
        if reason in ("entitlement_revoked", "cost_exhausted"):
            return _decline_result(target, reason or "unknown")
        if fallback_on_unavailable and target != DEFAULT_FALLBACK_AGENT:
            log.info(
                "dispatch.single.fallback",
                original_target=target,
                fallback=DEFAULT_FALLBACK_AGENT,
                reason=reason,
                request_id=str(ctx.request_id),
            )
            target = DEFAULT_FALLBACK_AGENT
            # Re-check the fallback under Layer 3.
            allowed, reason, _ = await _layer3_check(
                db, ctx.student_id, target, fresh_ctx=fresh_ctx
            )
            if not allowed:
                # Even the fallback is blocked — give up cleanly.
                return _decline_result(target, reason or "unknown")
        else:
            return _decline_result(target, reason or "unknown")

    # ── Invoke the specialist ──────────────────────────────────────
    payload = dict(decision.constructed_context or {})
    # Always pass through the user message and request id so
    # specialists can echo / log them.
    payload.setdefault("user_message", ctx.user_message)
    payload.setdefault("request_id", str(ctx.request_id))

    start = time.perf_counter()
    try:
        call_result = await call_agent(
            target,
            payload=payload,
            session=db,
            chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 — Pass 3b §7.1 Failure Class C
        log.warning(
            "dispatch.single.specialist_error",
            target=target,
            error=str(exc),
            error_type=type(exc).__name__,
            request_id=str(ctx.request_id),
        )
        return AgentResult(
            agent_name=target,
            output_text=(
                "I had trouble processing your request — could you try "
                "again or rephrase?"
            ),
            blocked=True,
            block_reason="specialist_error",
            duration_ms=int((time.perf_counter() - start) * 1000),
            cost_inr=Decimal("0"),
        )

    duration_ms = int((time.perf_counter() - start) * 1000)

    # Extract handoff signal if present (specialists return it via
    # AgentCallResult.output dict with a 'handoff_request' key).
    handoff_request = _extract_handoff(call_result.output)

    return AgentResult(
        agent_name=target,
        output_text=_extract_text(call_result.output),
        structured_output=_to_dict(call_result.output),
        output_summary=_extract_summary(call_result.output),
        blocked=call_result.status == "error",
        block_reason=call_result.error if call_result.status == "error" else None,
        handoff_request=handoff_request,
        duration_ms=duration_ms,
        cost_inr=Decimal("0"),  # Real cost wires through agent_actions.cost_inr
    )


def _extract_text(output: Any) -> str | None:
    """Pull a plain-text rendering out of a specialist's return value."""
    if output is None:
        return None
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("output_text", "answer", "response", "text"):
            if key in output and isinstance(output[key], str):
                return output[key]
    return None


def _to_dict(output: Any) -> dict[str, Any] | None:
    """Best-effort dict projection of the specialist output."""
    if isinstance(output, dict):
        return output
    if hasattr(output, "model_dump"):
        try:
            return output.model_dump()  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            return None
    return None


def _extract_summary(output: Any) -> str | None:
    """Specialist-provided 1-sentence summary, if present.

    memory_curator (Pass 3b §3.1) writes this into agent_actions.summary
    so the Supervisor's awareness window stays cheap. Specialists
    that don't provide one will get a fallback at log time.
    """
    if isinstance(output, dict):
        s = output.get("summary") or output.get("output_summary")
        if isinstance(s, str):
            return s
    return None


def _extract_handoff(output: Any) -> HandoffRequest | None:
    """Lift a handoff_request off the specialist's output, if any."""
    if not isinstance(output, dict):
        return None
    raw = output.get("handoff_request")
    if not isinstance(raw, dict):
        return None
    try:
        return HandoffRequest.model_validate(raw)
    except Exception:  # noqa: BLE001 — bad shape, log + ignore
        log.warning(
            "dispatch.handoff.malformed",
            raw=raw,
        )
        return None


# ── Chain dispatch ──────────────────────────────────────────────────


async def dispatch_chain(
    decision: RouteDecision,
    ctx: SupervisorContext,
    *,
    db: AsyncSession,
    chain: CallChain,
) -> ChainResult:
    """Execute a chain plan step-by-step with state passing.

    Pass 3b §5.2 + §6.4:
      • Each step gets a fresh Layer 3 re-check (cost ceiling can move
        mid-chain)
      • State passing via `pass_outputs_from_steps` — prior step
        outputs are injected as `step_{N}_output` keys
      • on_failure policy per step: abort_chain / continue / fallback_to_default
      • Chain length cap is enforced upstream (Supervisor prompt's
        "max 3 steps" constraint); we don't re-validate count here
    """
    if not decision.chain_plan:
        return ChainResult(
            steps=[],
            aborted_at_step=1,
            abort_reason="empty_chain_plan",
            total_duration_ms=0,
            total_cost_inr=Decimal("0"),
        )

    chain_results: list[AgentResult] = []
    total_duration = 0
    total_cost = Decimal("0")

    for step in decision.chain_plan:
        # Build context for this step: start from the step's own
        # constructed_context, then layer in any prior-step outputs
        # the plan asks for.
        step_ctx = dict(step.constructed_context)
        for prior_idx in step.pass_outputs_from_steps:
            # 1-based step numbers; translate to 0-based list idx.
            list_idx = prior_idx - 1
            if 0 <= list_idx < len(chain_results):
                prior = chain_results[list_idx]
                step_ctx[f"step_{prior_idx}_output"] = (
                    prior.output_summary
                    or prior.output_text
                    or ""
                )

        # Build a synthetic single-dispatch decision for this step.
        step_decision = RouteDecision(
            action="dispatch_single",
            target_agent=step.target_agent,
            constructed_context=step_ctx,
            reasoning=f"chain step {step.step_number}",
            confidence="high",
            primary_intent=decision.primary_intent,
        )

        # Important: chain steps don't fall back to learning_coach
        # automatically — the chain plan's `on_failure` decides.
        result = await dispatch_single(
            step_decision,
            ctx,
            db=db,
            chain=chain,
            fallback_on_unavailable=False,
        )
        chain_results.append(result)
        total_duration += result.duration_ms
        total_cost += result.cost_inr

        # Apply on_failure policy when the step blocked.
        if result.blocked:
            policy = step.on_failure
            if policy == "abort_chain":
                return ChainResult(
                    steps=chain_results,
                    aborted_at_step=step.step_number,
                    abort_reason=result.block_reason or "step_failed",
                    total_duration_ms=total_duration,
                    total_cost_inr=total_cost,
                )
            if policy == "continue":
                # Move on; the next step gets the failed step's
                # (empty) summary.
                continue
            if policy == "fallback_to_default":
                fallback_decision = RouteDecision(
                    action="dispatch_single",
                    target_agent=DEFAULT_FALLBACK_AGENT,
                    constructed_context=step_ctx,
                    reasoning=f"fallback for step {step.step_number}",
                    confidence="medium",
                    primary_intent=decision.primary_intent,
                )
                fallback_result = await dispatch_single(
                    fallback_decision,
                    ctx,
                    db=db,
                    chain=chain,
                    fallback_on_unavailable=False,
                )
                chain_results[-1] = fallback_result  # replace failed step
                total_duration += fallback_result.duration_ms
                total_cost += fallback_result.cost_inr
                continue

    return ChainResult(
        steps=chain_results,
        aborted_at_step=None,
        abort_reason=None,
        composed_response=_compose_chain_response(chain_results),
        total_duration_ms=total_duration,
        total_cost_inr=total_cost,
    )


def _compose_chain_response(steps: list[AgentResult]) -> str | None:
    """Stitch chain step outputs into one user-facing response.

    Naive concatenation in v1 — Pass 3b §5.2 calls LLM-quality
    stitching opt-in (last chain step calls supervisor.compose),
    which we don't ship in D9. Each step's output_text is joined
    with a blank line; non-text steps get their summary or skip.
    """
    parts: list[str] = []
    for step in steps:
        if step.output_text:
            parts.append(step.output_text)
        elif step.output_summary:
            parts.append(step.output_summary)
    return "\n\n".join(parts) if parts else None


# ── Handoff processing ─────────────────────────────────────────────


async def process_handoff(
    handoff: HandoffRequest,
    parent_ctx: SupervisorContext,
    *,
    db: AsyncSession,
    chain: CallChain,
    depth_remaining: int = 1,
) -> AgentResult | None:
    """Re-invoke the Supervisor when a specialist requests a handoff.

    Pass 3b §5.3: dispatch does NOT blindly follow handoffs. It
    re-runs the Supervisor with the handoff context so the
    Supervisor decides whether to honor it. This prevents loops
    (the Supervisor sees the call chain via agent_call_chain and
    refuses cyclic handoffs) and cost runaway.

    `depth_remaining` caps how deep handoff chains can go in v1 —
    we ship with depth_remaining=1 (one re-invocation max). Pass 3b
    §5.3 mentions cost-runaway prevention; the depth cap is the
    cheap, deterministic version of that.

    Returns None if the depth is exhausted; caller should treat
    that as "handoff ignored" and surface the original specialist's
    output.
    """
    if depth_remaining <= 0:
        log.info(
            "dispatch.handoff.depth_exhausted",
            target=handoff.target_agent,
            reason=handoff.reason,
            request_id=str(parent_ctx.request_id),
        )
        return None

    # Validate the target is a known agent. Don't waste a Supervisor
    # call on a hallucinated handoff target.
    if get_capability(handoff.target_agent) is None:
        log.warning(
            "dispatch.handoff.unknown_target",
            target=handoff.target_agent,
            request_id=str(parent_ctx.request_id),
        )
        return None

    # For v1 we directly invoke the suggested target (no re-Supervisor
    # call). The architectural reason: D9's Supervisor doesn't have
    # tooling to introspect a handoff request structure yet, and
    # adding it expands D9 scope. Re-invocation via the Supervisor is
    # a Pass 3h follow-up — for v1, we honor mandatory handoffs and
    # decline suggested ones unless the dispatch layer's heuristics
    # OK them.
    if handoff.handoff_type == "suggested":
        log.info(
            "dispatch.handoff.suggested_declined",
            target=handoff.target_agent,
            reason=handoff.reason,
            request_id=str(parent_ctx.request_id),
            note="v1 declines suggested handoffs; mandatory only",
        )
        return None

    handoff_decision = RouteDecision(
        action="dispatch_single",
        target_agent=handoff.target_agent,
        constructed_context=dict(handoff.suggested_context),
        reasoning=f"mandatory handoff: {handoff.reason}",
        confidence="medium",
        primary_intent=f"handoff_from_specialist",
    )
    return await dispatch_single(
        handoff_decision,
        parent_ctx,
        db=db,
        chain=chain,
        fallback_on_unavailable=False,
    )


__all__ = [
    "DEFAULT_FALLBACK_AGENT",
    "DEFAULT_SPECIALIST_TIMEOUT_MS",
    "dispatch_chain",
    "dispatch_single",
    "process_handoff",
]
