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

D13.5 — mandatory validation chains (capability-driven):
  When the producer agent's capability declares
  `requires_mandatory_validation_by`, dispatch_single auto-extends to
  invoke the validator after the producer completes. Both outputs
  surface in the producer's AgentResult.structured_output under the
  validation_output key. Chain-summed timeout (sum × 1.10) wraps the
  validator call as a defense-in-depth ceiling per D-E.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capability import (
    filter_capabilities_for_user,
    get_capability,
    resolve_timeout_seconds,
)
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


# Per-agent dispatch timeout is now resolved at call_agent() via
# capability.resolve_timeout_seconds() (D12 CP3 Phase 3 — Bug 11/Bug 6).
# The legacy `DEFAULT_SPECIALIST_TIMEOUT_MS = 30_000` constant was
# defined here per Pass 3b §5.1 but never read; the resolver replaces
# it conceptually. Removed in the Phase 3 commit alongside the wrapper
# rewrite at primitives/communication.py:499-502.

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

    structured_output = _to_dict(call_result.output)

    # D13.5 — mandatory validation chain (capability-driven).
    #
    # If the producer's capability declares a mandatory validator AND
    # the producer succeeded AND we have structured output to feed the
    # adapter, auto-dispatch the validator. The validator's output
    # joins the producer's structured_output under VALIDATION_OUTPUT_KEY
    # (compositional per D-C, not gating per D-B). The validator call
    # is wrapped with the chain-summed budget remaining after the
    # producer's elapsed time as a defense-in-depth ceiling per D-E.
    #
    # Failure semantics:
    #   • Producer failed (call_result.status != "ok" or blocked):
    #     skip validation; standard producer-failure path.
    #   • Adapter raises: block with "validation_adapter_error" — fail
    #     loud per the mandatory-validation contract.
    #   • Validator times out / errors: producer's output still ships;
    #     validation_unavailable marker added to structured_output.
    producer_capability = get_capability(target)
    should_validate = (
        producer_capability is not None
        and producer_capability.requires_mandatory_validation_by is not None
        and call_result.status == "ok"
        and structured_output is not None
    )
    if should_validate:
        validation_outcome = await _run_mandatory_validation(
            producer_target=target,
            producer_capability=producer_capability,
            producer_output=call_result.output,
            producer_elapsed_seconds=time.perf_counter() - start,
            ctx=ctx,
            db=db,
            chain=chain,
            request_id=str(ctx.request_id),
        )
        if validation_outcome["block"]:
            # Adapter failure — fail loud. Producer's resume does NOT
            # reach the user when validation can't even be attempted.
            return AgentResult(
                agent_name=target,
                output_text=None,
                structured_output=structured_output,
                output_summary=_extract_summary(call_result.output),
                blocked=True,
                block_reason=validation_outcome["block_reason"],
                handoff_request=handoff_request,
                duration_ms=int((time.perf_counter() - start) * 1000),
                cost_inr=Decimal("0"),
            )
        # Compose validator output into the producer's structured output.
        # Use the canonical VALIDATION_OUTPUT_KEY so frontends can
        # distinguish primary content from validation report.
        structured_output = dict(structured_output)
        structured_output[VALIDATION_OUTPUT_KEY] = validation_outcome["payload"]

    return AgentResult(
        agent_name=target,
        output_text=_extract_text(call_result.output),
        structured_output=structured_output,
        output_summary=_extract_summary(call_result.output),
        blocked=call_result.status == "error",
        block_reason=call_result.error if call_result.status == "error" else None,
        handoff_request=handoff_request,
        duration_ms=int((time.perf_counter() - start) * 1000),
        cost_inr=Decimal("0"),  # Real cost wires through agent_actions.cost_inr
    )


# ── D13.5 mandatory validation chain helpers ──────────────────────────


# Output projection key per D-C. Frontends find the validator's output
# under producer.structured_output[VALIDATION_OUTPUT_KEY] when the chain
# auto-extended to a validator. Fixed string keeps the contract stable
# across producer/validator pairs (one canonical key, not per-pair).
VALIDATION_OUTPUT_KEY = "validation"

# Chain-summed timeout multiplier per D-E. sum(producer_timeout,
# validator_timeout) × 1.10 gives a 10% safety margin over the per-agent
# budgets without inflating the chain envelope further than necessary.
_CHAIN_TIMEOUT_MULTIPLIER = 1.10


def _resolve_chain_summed_budget(
    producer_capability: Any,
    validator_capability: Any,
) -> float:
    """Compute the outer chain-level timeout per D-E.

    sum(producer_timeout, validator_timeout) × 1.10. Returned in seconds
    as a float (asyncio.wait_for semantics).

    Per-agent timeouts INSIDE the chain stay individual: each
    `call_agent` invocation honors its own capability-derived budget.
    The summed budget is an OUTER ceiling on the validator call,
    measured against the time the producer already consumed.
    """
    producer_budget = resolve_timeout_seconds(producer_capability)
    validator_budget = resolve_timeout_seconds(validator_capability)
    return (producer_budget + validator_budget) * _CHAIN_TIMEOUT_MULTIPLIER


async def _run_mandatory_validation(
    *,
    producer_target: str,
    producer_capability: Any,
    producer_output: Any,
    producer_elapsed_seconds: float,
    ctx: SupervisorContext,
    db: AsyncSession,
    chain: CallChain,
    request_id: str,
) -> dict[str, Any]:
    """Run the mandatory validator after the producer completes.

    Returns one of three shapes:
      • {"block": True,  "block_reason": str}
            adapter raised; producer's output is NOT shipped (fail-loud).
      • {"block": False, "payload": dict}
            validator ran; payload is either the validator's structured
            output or a validation_unavailable marker.

    See _run_mandatory_validation's caller for how `payload` lands in
    the producer's structured_output under VALIDATION_OUTPUT_KEY.
    """
    validator_name = producer_capability.requires_mandatory_validation_by
    adapter = producer_capability.validation_input_adapter

    if adapter is None:
        # Capability declared a validator but no adapter — configuration
        # error. Fail loud rather than ship un-validated content.
        log.error(
            "dispatch.validation.adapter_missing",
            producer=producer_target,
            validator=validator_name,
            request_id=request_id,
        )
        return {
            "block": True,
            "block_reason": "validation_adapter_missing",
        }

    validator_capability = get_capability(validator_name)
    if validator_capability is None:
        log.error(
            "dispatch.validation.validator_unknown",
            producer=producer_target,
            validator=validator_name,
            request_id=request_id,
        )
        # Validator not registered — capability typo or registry drift.
        # Treat as best-effort failure (validation_unavailable), don't
        # block the producer's output.
        return {
            "block": False,
            "payload": _validation_unavailable_marker(
                validator_name, "validator_not_registered"
            ),
        }

    # Compute the chain-summed budget and remaining time for the
    # validator (accounting for what the producer already consumed).
    chain_budget = _resolve_chain_summed_budget(
        producer_capability, validator_capability
    )
    remaining_for_validator = chain_budget - producer_elapsed_seconds
    if remaining_for_validator <= 0:
        log.warning(
            "dispatch.validation.budget_exhausted",
            producer=producer_target,
            validator=validator_name,
            chain_budget_s=chain_budget,
            producer_elapsed_s=producer_elapsed_seconds,
            request_id=request_id,
        )
        return {
            "block": False,
            "payload": _validation_unavailable_marker(
                validator_name, "chain_budget_exhausted"
            ),
        }

    log.info(
        "agentic.chain_timeout_resolved",
        producer=producer_target,
        validator=validator_name,
        chain_budget_seconds=round(chain_budget, 2),
        multiplier=_CHAIN_TIMEOUT_MULTIPLIER,
        producer_elapsed_seconds=round(producer_elapsed_seconds, 2),
        validator_remaining_seconds=round(remaining_for_validator, 2),
        request_id=request_id,
    )

    # ── Adapter ──────────────────────────────────────────────────────
    # Adapter takes the producer's structured output (the LLM's parsed
    # response, materialised as a Pydantic model when run() returned
    # one). call_result.output may be a dict (from .model_dump()); if
    # so, hydrate to the producer's output type before calling adapter.
    try:
        adapted_input = adapter(producer_output)
    except Exception as exc:  # noqa: BLE001 — fail loud per D-B/D-E
        log.error(
            "dispatch.validation.adapter_error",
            producer=producer_target,
            validator=validator_name,
            error=str(exc),
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        return {
            "block": True,
            "block_reason": "validation_adapter_error",
        }

    # ── Validator dispatch (wrapped in chain-summed budget) ──────────
    # Build the validator's payload from the adapted input. AgentInput
    # subclasses serialize cleanly via model_dump; the validator's
    # run_agentic accepts dict payloads.
    try:
        validator_payload: dict[str, Any] = (
            adapted_input.model_dump()
            if hasattr(adapted_input, "model_dump")
            else dict(adapted_input)
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "dispatch.validation.payload_dump_failed",
            producer=producer_target,
            validator=validator_name,
            error=str(exc),
            request_id=request_id,
        )
        return {
            "block": True,
            "block_reason": "validation_adapter_error",
        }

    validator_payload.setdefault("user_message", ctx.user_message)
    validator_payload.setdefault("request_id", request_id)

    try:
        validator_result = await asyncio.wait_for(
            call_agent(
                validator_name,
                payload=validator_payload,
                session=db,
                chain=chain,
            ),
            timeout=remaining_for_validator,
        )
    except asyncio.TimeoutError:
        log.warning(
            "dispatch.validation.timeout",
            producer=producer_target,
            validator=validator_name,
            timeout_s=round(remaining_for_validator, 2),
            request_id=request_id,
        )
        return {
            "block": False,
            "payload": _validation_unavailable_marker(
                validator_name, "validator_timeout"
            ),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "dispatch.validation.error",
            producer=producer_target,
            validator=validator_name,
            error=str(exc),
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        return {
            "block": False,
            "payload": _validation_unavailable_marker(
                validator_name, "validator_error"
            ),
        }

    if validator_result.status != "ok":
        log.warning(
            "dispatch.validation.validator_blocked",
            producer=producer_target,
            validator=validator_name,
            status=validator_result.status,
            error=validator_result.error,
            request_id=request_id,
        )
        return {
            "block": False,
            "payload": _validation_unavailable_marker(
                validator_name, "validator_blocked"
            ),
        }

    log.info(
        "dispatch.validation.complete",
        producer=producer_target,
        validator=validator_name,
        request_id=request_id,
    )
    return {
        "block": False,
        "payload": _to_dict(validator_result.output) or {},
    }


def _validation_unavailable_marker(
    validator_name: str, reason: str
) -> dict[str, Any]:
    """Structured marker the frontend sees when validation couldn't run.

    Producer's output still ships (D-B compositional semantics for the
    validator-failed branch); this marker tells the frontend that the
    validation report is unavailable and why. Distinct from the
    fail-loud adapter-error path, which blocks the producer entirely.
    """
    return {
        "validation_unavailable": True,
        "validator": validator_name,
        "reason": reason,
    }


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
    "dispatch_chain",
    "dispatch_single",
    "process_handoff",
]
