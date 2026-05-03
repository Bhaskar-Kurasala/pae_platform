"""D10 Checkpoint 2 — billing_support migration to AgenticBaseAgent.

Per Pass 3c §A.10's migration template, the new class lives at
`{name}_v2.py` during the migration and gets renamed to `{name}.py`
in Checkpoint 4 after the legacy file is deleted. The `_v2` suffix
is the cutover-period coexistence pattern: legacy `BaseAgent` lives
at `billing_support.py` (registered in `AGENT_REGISTRY`), new
`AgenticBaseAgent` lives here (registered in `_agentic_registry`
via `__init_subclass__`). The two registries are separate
namespaces; the canonical agentic endpoint resolves through
`_agentic_registry`, the legacy MOA resolves through
`AGENT_REGISTRY`. Both keep working until Checkpoint 4 retires the
legacy file.

Per Pass 3c E1 the agent declares:
  • name = "billing_support" (same as legacy — same Supervisor
    capability declaration applies; D10 Checkpoint 1 already flipped
    `available_now=True`)
  • Five primitive flags:
      uses_memory       = True   # remembers prior billing concerns
      uses_tools        = True   # calls universal + billing-specific
                                 # tools (the latter ship in Cp 3)
      uses_inter_agent  = False  # leaf agent; never hands off
      uses_self_eval    = False  # Haiku is fast; no critic in loop
      uses_proactive    = False  # student-initiated only
  • Haiku model (cheap, fast — billing Q&A is a low-cost-of-error
    domain where speed matters more than depth)
  • Output schema: BillingSupportOutput (Pass 3c E1 verbatim,
    shipped in Checkpoint 1)

Checkpoint 2 scope: agent class + canonical prompt deployed.
Checkpoint 3 will:
  • Replace the placeholder lookup-tool calls below with the four
    F.1 tools (lookup_order_history, lookup_active_entitlements,
    lookup_refund_status, escalate_to_human)
  • Hook grant_signup_grace into auth/register
  • Wire agent_actions.cost_inr in the AgenticBaseAgent.execute path

For Checkpoint 2 the lookup tools return placeholder results — the
agent reaches the LLM, the LLM produces a structured response, the
schema validates it, the dispatch layer surfaces it. Real grounded
answers come in Checkpoint 3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import structlog
from pydantic import ConfigDict, Field

from app.agents.agentic_base import AgentContext, AgentInput, AgenticBaseAgent
from app.schemas.agents.billing_support import BillingSupportOutput

log = structlog.get_logger().bind(layer="billing_support_v2")


# ── Input schema ────────────────────────────────────────────────────


class BillingSupportInput(AgentInput):
    """The student's billing question + optional anchors.

    `question` is the free-form text the student typed. Pass 3c E1
    optional inputs map to `order_id` / `invoice_number` /
    `specific_concern` — the Supervisor populates these in
    `constructed_context` when it can extract them from the user
    message; otherwise they stay None and the agent works from the
    question text alone.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    order_id: str | None = Field(default=None, max_length=120)
    invoice_number: str | None = Field(default=None, max_length=120)
    specific_concern: str | None = Field(default=None, max_length=240)
    # Dispatch layer always passes user_message + request_id (per
    # dispatch_single payload defaults). They're informational here;
    # the agent reads `question` for the actual content.
    user_message: str | None = Field(default=None, max_length=10_000)
    request_id: str | None = Field(default=None, max_length=60)


# ── Prompt loader ───────────────────────────────────────────────────


_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Read a prompt file from the prompts directory.

    Raises if the file is missing — billing_support has no
    inline-default fallback because the prompt is load-bearing for
    correct behavior (Pass 3c E1 explicitly defines hard constraints
    + handoff rules + brand identity in the prompt). A missing file
    is a deployment bug, not a degraded-but-functional state.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file missing: {path}. The prompt is required; "
            "no inline fallback exists for billing_support."
        )
    return path.read_text()


# ── The agent ───────────────────────────────────────────────────────


class BillingSupportAgent(AgenticBaseAgent[BillingSupportInput]):
    """Billing, subscription, payment, refund, and receipt Q&A.

    Per Pass 3c E1: leaf agent. Never hands off. Free-tier
    accessible (so students whose subscription expired can still
    ask "what happened to my account?"). Reads actual student
    records via lookup tools (placeholder in Checkpoint 2,
    real bodies in Checkpoint 3).
    """

    name: ClassVar[str] = "billing_support"
    description: ClassVar[str] = (
        "Account, billing, and entitlement Q&A. Free-tier accessible. "
        "Reads orders, entitlements, refund status via lookup tools; "
        "escalates genuine grievances to human admin. Leaf agent — "
        "never hands off."
    )
    input_schema: ClassVar[type[AgentInput]] = BillingSupportInput
    # Haiku per Pass 3c E1 — billing Q&A is cheap-and-fast territory.
    # cost_inr in agent_actions uses this model name for the
    # estimate_cost_inr call inside AgenticBaseAgent._finalize_action_log.
    model_name: ClassVar[str] = "claude-haiku-4-5"

    # ── Five primitive flags per Pass 3c E1 ───────────────────────
    uses_memory: ClassVar[bool] = True
    uses_tools: ClassVar[bool] = True
    uses_inter_agent: ClassVar[bool] = False
    uses_self_eval: ClassVar[bool] = False
    uses_proactive: ClassVar[bool] = False

    # Leaf agent — no outbound calls. allowed_callees stays empty.
    # allowed_callers is also empty (any caller can reach us — the
    # Supervisor dispatches to us, no other agent should).
    allowed_callers: ClassVar[tuple[str, ...]] = ()
    allowed_callees: ClassVar[tuple[str, ...]] = ()

    # Tool-permission set per Pass 3d §C.1 — what this agent can do.
    # Granted access to:
    #   • read:agent_memory   for the universal memory_recall + memory_write
    #   • write:agent_memory  for the same + _record_interaction memory writes
    #   • read:student_data   for lookup_order_history / _active_entitlements /
    #                         _refund_status (the agent-specific lookup tools)
    #   • admin:escalation    for escalate_to_human (writes a tagged
    #                         student_inbox row for admin review)
    #   • write:audit_log     for the universal log_event tool
    permissions: ClassVar[frozenset[str]] = frozenset({
        "read:agent_memory",
        "write:agent_memory",
        "read:student_data",
        "admin:escalation",
        "write:audit_log",
    })

    # ── Chat path ──────────────────────────────────────────────────

    async def run(
        self, input: BillingSupportInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Single chat path: ground the answer in the student's
        actual records, return a BillingSupportOutput-shaped dict.

        Sequence (D10 Checkpoint 3):
          1. Recall prior billing interactions with this student
             (memory.recall on key pattern `interaction:billing_concern:*`).
          2. Read communication-tone preference if present
             (memory.recall on `pref:billing_communication_tone`).
          3. Speculatively call the three read-only lookup tools
             (orders, entitlements, refund status) so the LLM has
             real grounded data in its context. The tools are cheap
             (DB queries against indexed columns), so speculative
             calls are appropriate vs the LLM-driven tool-use
             protocol that would need separate Anthropic tool-call
             plumbing. The escalate_to_human tool is NOT called
             speculatively — escalation is a write side effect; the
             agent decides via the LLM's structured output whether
             to fire it (Checkpoint 4 wires the post-LLM escalation
             dispatch path).
          4. Build the LLM prompt with memory + lookup results +
             the question.
          5. Invoke Haiku; track LLM usage via _track_llm_usage so
             execute() can write cost_inr to agent_actions; parse
             structured output against BillingSupportOutput.
          6. Stash the interaction back to memory at
             `interaction:billing_concern:{date}` so future turns
             can recognize repeat concerns.
        """
        memories = await self._recall_billing_memories(input, ctx)
        lookup_results = await self._gather_lookup_data(input, ctx)

        answer_payload = await self._call_llm(
            question=input.question,
            order_id=input.order_id,
            invoice_number=input.invoice_number,
            specific_concern=input.specific_concern,
            memories=memories,
            lookup_results=lookup_results,
            ctx=ctx,
        )

        # ── Escalation dispatch (D10 Checkpoint 3 sign-off / Q4) ──
        # The prompt instructs the LLM to fire escalate_to_human and
        # populate escalation_ticket_id when it decides escalation
        # is appropriate. Anthropic tool-use is not yet wired (see
        # docs/followups/anthropic-tool-use-protocol.md), so without
        # this dispatch the LLM hallucinates a ticket_id and no real
        # student_inbox row lands — a phantom ticket is worse than a
        # crash. A student waits 24h for a response that never
        # comes.
        #
        # Fix: post-LLM dispatch. If the LLM requested escalation,
        # the host fires the tool, OVERWRITES escalation_ticket_id
        # with the real value (never trust the LLM's), and on tool
        # failure surfaces support email honestly. NEVER ship a
        # fictional ticket.
        answer_payload = await self._dispatch_escalation_if_requested(
            input=input,
            answer_payload=answer_payload,
            ctx=ctx,
        )

        # Stash the interaction. Best-effort — failure to write
        # memory must not fail the user-facing response. Same
        # asyncpg-recovery discipline as
        # agentic_snapshot_service._load_goal_contract: catching the
        # Python exception isn't enough — asyncpg poisons the
        # transaction at the protocol level, so the next statement
        # on the same session (typically the agent_call_chain INSERT
        # inside call_agent) trips PendingRollbackError unless we
        # explicitly rollback. The rollback itself is wrapped so a
        # rollback failure never shadows the original error.
        # See docs/followups/goal-contracts-schema-divergence.md for
        # the canonical write-up of this asyncpg gotcha.
        try:
            await self._record_interaction(input, answer_payload, ctx)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "billing_support_v2.memory_write_failed",
                error=str(exc),
                user_id=str(ctx.user_id) if ctx.user_id else None,
            )
            try:
                await ctx.session.rollback()
            except Exception as rollback_exc:  # noqa: BLE001
                log.error(
                    "billing_support_v2.memory_write_rollback_failed",
                    original_error=str(exc),
                    rollback_error=str(rollback_exc),
                    user_id=str(ctx.user_id) if ctx.user_id else None,
                )

        return answer_payload

    # ── Internal helpers ───────────────────────────────────────────

    async def _recall_billing_memories(
        self,
        input: BillingSupportInput,
        ctx: AgentContext,
    ) -> list[dict[str, Any]]:
        """Pull prior billing interactions + tone preference for
        this student. Two recall calls so the LLM sees both the
        durable preference (structured key match) and the related
        topical history (semantic match against the question).
        """
        if ctx.user_id is None:
            return []

        store = self.memory(ctx)
        # Structured pass: prior billing concerns by key prefix +
        # the tone preference.
        structured = await store.recall(
            "interaction:billing_concern",
            user_id=ctx.user_id,
            agent_name=self.name,
            scope="user",
            mode="structured",
            k=5,
        )
        tone = await store.recall(
            "pref:billing_communication_tone",
            user_id=ctx.user_id,
            agent_name=self.name,
            scope="user",
            mode="structured",
            k=1,
        )
        # Semantic pass against the question.
        semantic = await store.recall(
            input.question,
            user_id=ctx.user_id,
            agent_name=self.name,
            scope="user",
            mode="semantic",
            k=5,
        )
        # Dedupe by id; structured first so prefs surface at the top.
        seen: set[Any] = set()
        merged: list[Any] = []
        for row in list(tone) + list(structured) + list(semantic):
            if row.id in seen:
                continue
            seen.add(row.id)
            merged.append(row)
            if len(merged) >= 8:
                break
        return [
            {"key": row.key, "value": row.value, "similarity": row.similarity}
            for row in merged
        ]

    async def _gather_lookup_data(
        self,
        input: BillingSupportInput,
        ctx: AgentContext,
    ) -> dict[str, Any]:
        """Speculatively call the three read-only lookup tools so
        the LLM has real grounded data in its prompt context.

        Returns a dict with three sub-dicts keyed by tool name. Each
        sub-dict carries the structured output the tool returned (or
        an empty placeholder + error key on tool failure — the agent
        always proceeds to the LLM call, the LLM decides what to do
        with partial data).

        Tool calls go through self.tool_call (the executor) so they
        get audit-logged in agent_tool_calls. The executor enforces
        permissions via ctx.permissions — see the agent's
        permissions ClassVar declaration. If a permission is
        missing, the executor raises ToolPermissionError; we catch
        + log + degrade rather than failing the user-facing
        response.
        """
        if ctx.user_id is None:
            return {"orders": None, "entitlements": None, "refunds": None}

        results: dict[str, Any] = {}

        # lookup_order_history
        try:
            tool_result = await self.tool_call(
                "lookup_order_history",
                {"student_id": str(ctx.user_id), "limit": 20},
                ctx,
            )
            if tool_result.status == "ok" and tool_result.output is not None:
                results["orders"] = tool_result.output.model_dump(mode="json")
            else:
                results["orders"] = {"error": tool_result.error or "unknown"}
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "billing_support_v2.lookup_orders_failed",
                error=str(exc),
                user_id=str(ctx.user_id),
            )
            results["orders"] = {"error": str(exc)}

        # lookup_active_entitlements
        try:
            tool_result = await self.tool_call(
                "lookup_active_entitlements",
                {"student_id": str(ctx.user_id)},
                ctx,
            )
            if tool_result.status == "ok" and tool_result.output is not None:
                results["entitlements"] = tool_result.output.model_dump(mode="json")
            else:
                results["entitlements"] = {"error": tool_result.error or "unknown"}
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "billing_support_v2.lookup_entitlements_failed",
                error=str(exc),
                user_id=str(ctx.user_id),
            )
            results["entitlements"] = {"error": str(exc)}

        # lookup_refund_status (all refunds for the student)
        try:
            tool_result = await self.tool_call(
                "lookup_refund_status",
                {"student_id": str(ctx.user_id), "order_id": None},
                ctx,
            )
            if tool_result.status == "ok" and tool_result.output is not None:
                results["refunds"] = tool_result.output.model_dump(mode="json")
            else:
                results["refunds"] = {"error": tool_result.error or "unknown"}
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "billing_support_v2.lookup_refunds_failed",
                error=str(exc),
                user_id=str(ctx.user_id),
            )
            results["refunds"] = {"error": str(exc)}

        return results

    async def _call_llm(
        self,
        *,
        question: str,
        order_id: str | None,
        invoice_number: str | None,
        specific_concern: str | None,
        memories: list[dict[str, Any]],
        lookup_results: dict[str, Any],
        ctx: AgentContext,
    ) -> dict[str, Any]:
        """Invoke Haiku, parse structured output.

        The prompt instructs the LLM to return a JSON object
        matching BillingSupportOutput. We extract the first balanced
        JSON object from the response (tolerant of leading/trailing
        prose), validate against the schema, return the validated
        dict. On parse failure, return a degraded but valid
        BillingSupportOutput pointing the student at human support
        — never raise to the caller, since the Supervisor's
        dispatch_single contract treats raise-to-caller as
        specialist_error.

        Tracks LLM usage via self._track_llm_usage so
        AgenticBaseAgent._finalize_action_log can write cost_inr to
        agent_actions for the cost-ceiling enforcement.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        system_prompt = _load_prompt("billing_support")
        context_block = self._build_context_block(
            order_id=order_id,
            invoice_number=invoice_number,
            specific_concern=specific_concern,
            memories=memories,
            lookup_results=lookup_results,
        )
        user_block = (
            f"{context_block}\n\nStudent question: {question}\n\n"
            "Respond with a single JSON object matching the "
            "BillingSupportOutput schema. No prose before or after."
        )
        messages: list[Any] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_block),
        ]

        llm = self._build_llm(max_tokens=900)
        try:
            response = await llm.ainvoke(messages)
            # Track tokens for cost_inr — happens BEFORE parsing so
            # cost is recorded even on parse-failure paths.
            self._track_llm_usage(ctx, response)
            raw = self._extract_text(response.content)
            parsed = self._parse_json_object(raw)
            output = BillingSupportOutput.model_validate(parsed)
            return output.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 — fall back gracefully
            log.warning(
                "billing_support_v2.llm_or_parse_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                user_id=str(ctx.user_id) if ctx.user_id else None,
            )
            fallback = BillingSupportOutput(
                answer=(
                    "I had trouble processing your billing question. "
                    "Please email support@aicareeros.com with your "
                    "order details and we'll respond within 24 hours."
                ),
                grounded_in=[],
                suggested_action="contact_support",
                confidence="low",
            )
            return fallback.model_dump(mode="json")

    async def _dispatch_escalation_if_requested(
        self,
        *,
        input: BillingSupportInput,
        answer_payload: dict[str, Any],
        ctx: AgentContext,
    ) -> dict[str, Any]:
        """Post-LLM escalation dispatch — never ship a phantom ticket.

        Inspect the LLM's structured output. If suggested_action is
        "contact_support" AND escalation_ticket_id is non-null, the
        LLM has requested an escalation but Anthropic tool-use isn't
        wired (see docs/followups/anthropic-tool-use-protocol.md) —
        meaning no real student_inbox row landed yet. The LLM's
        ticket_id is fictional.

        We fix this by firing escalate_to_human ourselves, then
        OVERWRITING the LLM's escalation_ticket_id with the real one
        (never trust the LLM's value). On tool failure, null out the
        ticket_id and append a support email to the answer text — be
        honest with the student rather than silent.

        If the LLM didn't request escalation, no-op.

        Returns the (possibly modified) answer_payload.
        """
        # Only dispatch when the LLM both asked for support AND
        # claimed a ticket. Either condition alone is ambiguous; both
        # together is the LLM saying "I escalated this."
        suggested = answer_payload.get("suggested_action")
        llm_ticket_id = answer_payload.get("escalation_ticket_id")

        if suggested != "contact_support" or not llm_ticket_id:
            return answer_payload

        if ctx.user_id is None:
            # Can't escalate without a user. Be honest.
            log.warning(
                "billing_support_v2.escalation_skipped_no_user",
                llm_ticket_id_was=str(llm_ticket_id),
            )
            answer_payload["escalation_ticket_id"] = None
            answer_payload["answer"] = (
                str(answer_payload.get("answer", "")).rstrip()
                + "\n\nFor immediate help, please email "
                "support@aicareeros.com with your account details."
            )
            return answer_payload

        # Build the summary the admin will see in the inbox card. The
        # LLM's `answer` is what the student got; the admin needs that
        # plus the original question to triage.
        summary = (
            f"Student question: {input.question}\n\n"
            f"Agent's response to the student:\n"
            f"{answer_payload.get('answer', '')}"
        )

        try:
            tool_result = await self.tool_call(
                "escalate_to_human",
                {
                    "student_id": str(ctx.user_id),
                    "reason": "agent_initiated",
                    "summary": summary[:1900],  # tool's max_length=2000
                    # Use the LLM's claimed ticket as an idempotency
                    # key. If the same conversation re-fires, we
                    # collapse to the original real ticket.
                    "idempotency_key": str(llm_ticket_id)[:200],
                },
                ctx,
            )
        except Exception as exc:  # noqa: BLE001
            # Tool dispatch raised — be honest. Do NOT keep the LLM's
            # phantom ticket_id; null it and tell the student to use
            # the support email directly.
            log.warning(
                "billing_support_v2.escalation_dispatch_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                llm_ticket_id_was=str(llm_ticket_id),
                user_id=str(ctx.user_id),
            )
            answer_payload["escalation_ticket_id"] = None
            answer_payload["answer"] = (
                str(answer_payload.get("answer", "")).rstrip()
                + "\n\nI had trouble filing the escalation ticket "
                "automatically — please email support@aicareeros.com "
                "directly so a human can pick this up."
            )
            return answer_payload

        # Tool ran. Even an error-status result means we shouldn't
        # ship the LLM's phantom ticket — surface the support email
        # honestly.
        if tool_result.status != "ok" or tool_result.output is None:
            log.warning(
                "billing_support_v2.escalation_tool_returned_error",
                status=tool_result.status,
                error=tool_result.error,
                llm_ticket_id_was=str(llm_ticket_id),
                user_id=str(ctx.user_id),
            )
            answer_payload["escalation_ticket_id"] = None
            answer_payload["answer"] = (
                str(answer_payload.get("answer", "")).rstrip()
                + "\n\nI had trouble filing the escalation ticket "
                "automatically — please email support@aicareeros.com "
                "directly so a human can pick this up."
            )
            return answer_payload

        # Success: overwrite the LLM's claimed ticket with the real
        # one. Pydantic-typed access via the tool's output schema.
        try:
            real_ticket_id = str(tool_result.output.ticket_id)  # type: ignore[union-attr]
        except AttributeError:
            # Output didn't carry a ticket_id attribute — defensive.
            log.warning(
                "billing_support_v2.escalation_output_missing_ticket_id",
                output_repr=repr(tool_result.output)[:200],
            )
            answer_payload["escalation_ticket_id"] = None
            answer_payload["answer"] = (
                str(answer_payload.get("answer", "")).rstrip()
                + "\n\nFor immediate help, please email "
                "support@aicareeros.com with your account details."
            )
            return answer_payload

        log.info(
            "billing_support_v2.escalation_dispatched",
            real_ticket_id=real_ticket_id,
            llm_ticket_id_was=str(llm_ticket_id),
            ticket_overridden=real_ticket_id != str(llm_ticket_id),
            user_id=str(ctx.user_id),
        )
        answer_payload["escalation_ticket_id"] = real_ticket_id
        return answer_payload

    async def _record_interaction(
        self,
        input: BillingSupportInput,
        answer_payload: dict[str, Any],
        ctx: AgentContext,
    ) -> None:
        """Stash a memory row summarizing this interaction so future
        turns can recognize repeat concerns. Per Pass 3c E1's
        memory-access section: write `interaction:billing_concern:{date}`
        with valence reflecting whether the student seemed satisfied
        (escalation = unresolved frustration → negative valence).
        """
        from datetime import UTC, datetime

        from app.agents.primitives.memory import MemoryWrite

        if ctx.user_id is None:
            return

        date_bucket = datetime.now(UTC).strftime("%Y-%m-%d")
        suggested = answer_payload.get("suggested_action")
        # Negative valence when the agent had to escalate or the
        # student is in a known unresolved state; neutral otherwise.
        valence = -0.3 if suggested == "contact_support" else 0.5

        await self.memory(ctx).write(
            MemoryWrite(
                user_id=ctx.user_id,
                agent_name=self.name,
                scope="user",
                key=f"interaction:billing_concern:{date_bucket}",
                value={
                    "question": input.question[:300],
                    "answer_summary": answer_payload.get("answer", "")[:300],
                    "suggested_action": suggested,
                    "confidence": answer_payload.get("confidence"),
                    "grounded_in_count": len(
                        answer_payload.get("grounded_in", []) or []
                    ),
                },
                valence=valence,
                confidence=0.85,
            )
        )

    @staticmethod
    def _build_context_block(
        *,
        order_id: str | None,
        invoice_number: str | None,
        specific_concern: str | None,
        memories: list[dict[str, Any]],
        lookup_results: dict[str, Any],
    ) -> str:
        """Render the optional anchors + recalled memories + lookup
        results into a prose block for the LLM. Empty fields stay
        out of the rendered context (less noise = better Haiku
        reasoning).

        Lookup data is rendered as compact JSON because Haiku
        handles structured-data prompts better than verbose prose
        for tabular records like orders + refunds. Per-record fields
        are intentionally minimal — the prompt's [Hard constraints]
        section says "ground answers in actual records" and the LLM
        gets the receipt_number, status, amount + dates it needs to
        do that.
        """
        import json as _json

        parts: list[str] = []
        anchors: list[str] = []
        if order_id:
            anchors.append(f"order_id={order_id}")
        if invoice_number:
            anchors.append(f"invoice_number={invoice_number}")
        if specific_concern:
            anchors.append(f"specific_concern={specific_concern}")
        if anchors:
            parts.append("[Supervisor-supplied anchors]\n  " + "\n  ".join(anchors))

        if memories:
            parts.append(
                "[What I remember about this student's billing history]\n"
                + "\n".join(
                    f"  - {m['key']}: {m['value']}"
                    for m in memories
                    if m.get("value") is not None
                )
            )

        # Lookup results: render only the non-empty / non-error
        # sections so a student with no orders doesn't waste prompt
        # tokens on an empty array.
        orders = lookup_results.get("orders") or {}
        if isinstance(orders, dict) and orders.get("orders"):
            parts.append(
                "[Student's order history (most recent first)]\n"
                + _json.dumps(orders.get("orders", []), default=str, indent=2)
                + (
                    "\n[NOTE: order list truncated — there are more]"
                    if orders.get("truncated")
                    else ""
                )
            )

        ents = lookup_results.get("entitlements") or {}
        if isinstance(ents, dict) and ents.get("entitlements"):
            parts.append(
                "[Currently-active course entitlements]\n"
                + _json.dumps(ents.get("entitlements", []), default=str, indent=2)
            )

        refunds = lookup_results.get("refunds") or {}
        if isinstance(refunds, dict) and refunds.get("refunds"):
            parts.append(
                "[Refund history for this student]\n"
                + _json.dumps(refunds.get("refunds", []), default=str, indent=2)
            )

        if not parts:
            return "[No prior billing history or records found for this student.]"
        return "\n\n".join(parts)

    def _build_llm(self, *, max_tokens: int = 900) -> Any:
        """Build the LLM. Haiku per Pass 3c E1 — billing Q&A is
        cheap-and-fast territory; depth isn't required.
        """
        from app.agents.llm_factory import build_llm

        return build_llm(max_tokens=max_tokens, tier="fast")

    @staticmethod
    def _extract_text(content: Any) -> str:
        """Anthropic occasionally returns a list of content blocks
        (extended thinking, tool-use mid-response). Harvest the text
        parts; everything else is silently dropped.

        Per the founder's feedback_llm_response_parsing memory:
        flatten list-of-dict content, skip thinking blocks, leave
        text intact for downstream JSON extraction.
        """
        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "".join(text_parts)
        return str(content)

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any]:
        """Extract the first balanced JSON object from `raw`.

        Per the founder's feedback_llm_response_parsing memory: the
        LLM occasionally wraps the JSON in prose; we walk the string
        looking for the first `{` and accumulate until the matching
        `}` closes. Quote-aware so braces inside strings don't
        confuse the depth counter.
        """
        import json as _json

        depth = 0
        start = -1
        in_string = False
        escape_next = False
        for i, ch in enumerate(raw):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    candidate = raw[start : i + 1]
                    return _json.loads(candidate)
        raise ValueError(
            "no balanced JSON object found in LLM response; "
            "first 200 chars: " + raw[:200]
        )


__all__ = ["BillingSupportAgent", "BillingSupportInput"]
