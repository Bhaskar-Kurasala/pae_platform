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

    # ── Chat path ──────────────────────────────────────────────────

    async def run(
        self, input: BillingSupportInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Single chat path: ground the answer in the student's
        actual records, return a BillingSupportOutput-shaped dict.

        Sequence:
          1. Recall prior billing interactions with this student
             (memory.recall on key pattern `interaction:billing_concern:*`).
          2. Read communication-tone preference if present
             (memory.recall on `pref:billing_communication_tone`).
          3. Build the LLM prompt with memory context + the question.
          4. Invoke Haiku, parse structured output against
             BillingSupportOutput.
          5. Stash the interaction back to memory at
             `interaction:billing_concern:{date}` so future turns
             can recognize repeat concerns.

        Lookup tools (lookup_order_history / lookup_active_entitlements
        / lookup_refund_status / escalate_to_human) are not called
        here — they ship in Checkpoint 3. The prompt instructs the
        LLM to call them; the LLM will not have access until then.
        For Checkpoint 2's smoke test, the agent answers from prompt
        + memory only. That degrades to "I don't have your specific
        records yet but here's general guidance" — acceptable for
        the verification path Checkpoint 2 spec describes.
        """
        memories = await self._recall_billing_memories(input, ctx)

        answer_payload = await self._call_llm(
            question=input.question,
            order_id=input.order_id,
            invoice_number=input.invoice_number,
            specific_concern=input.specific_concern,
            memories=memories,
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

    async def _call_llm(
        self,
        *,
        question: str,
        order_id: str | None,
        invoice_number: str | None,
        specific_concern: str | None,
        memories: list[dict[str, Any]],
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
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        system_prompt = _load_prompt("billing_support")
        context_block = self._build_context_block(
            order_id=order_id,
            invoice_number=invoice_number,
            specific_concern=specific_concern,
            memories=memories,
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
    ) -> str:
        """Render the optional anchors + recalled memories into a
        prose block for the LLM. Empty fields stay out of the
        rendered context (less noise = better Haiku reasoning).
        """
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

        if not parts:
            return "[No prior billing history with this student.]"
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
