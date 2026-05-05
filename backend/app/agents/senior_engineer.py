"""D11 / Pass 3c E2 — senior_engineer agent (canonical AgenticBaseAgent).

Successor to three legacy BaseAgent subclasses:
  • senior_engineer.py  (legacy pair-programmer review path)
  • code_review.py      (legacy rubric-grader path)
  • coding_assistant.py (legacy debug-help path)

The merge collapses three different output shapes into one
SeniorEngineerOutput with a `mode` discriminator. Same agent class,
three branches in the prompt + three sub-shapes in the schema.

  • Five primitive flags:
      uses_memory       = True   # tracks recurring code patterns
      uses_tools        = True   # lookup_prior_submissions/_reviews + universals
      uses_inter_agent  = True   # advertises handoff_targets to Supervisor
                                 # for up-front chain construction (Option B
                                 # per docs/followups/handoff-protocol-d11-d13.md)
      uses_self_eval    = False  # high-traffic; Critic in loop deferred
      uses_proactive    = False  # student-initiated only

Sandbox tools (run_in_sandbox, run_static_analysis, run_tests) per
Pass 3d §E.3 are deferred to D14. The deployed prompt explicitly
forbids execution claims; the agent reasons about code as text only.

Cutover landed at D11 Checkpoint 4 (this file). The legacy
BaseAgent senior_engineer.py was deleted at the same commit;
this file is now the canonical AgenticBaseAgent successor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import structlog
from pydantic import ConfigDict, Field

from app.agents.agentic_base import AgentContext, AgentInput, AgenticBaseAgent
from app.schemas.agents.senior_engineer import SeniorEngineerOutput

log = structlog.get_logger().bind(layer="senior_engineer")


# ── Input schema ───────────────────────────────────────────────────


class SeniorEngineerInput(AgentInput):
    """Per Pass 3c E2 capability declaration — with input-shape
    realism layered in.

    The Supervisor's `constructed_context` dict shape is LLM-decided
    per call, not strictly enforced against `inputs_required`. The
    Pass 3c E2 spec lists `code` as the required field, but in
    practice the Supervisor commonly emits `{"question": "..."}` or
    `{"task": "..."}` for code-review-flavored requests because
    those field names appear in the supervisor.md prompt examples.

    Accommodating that reality without dropping the contract:
      - All four input-text fields (code, question, task,
        user_message) are individually optional.
      - `_resolve_input_text` (called from the agent's run path)
        picks the first populated field with `code` preferred,
        falling back to `question` → `task` → `user_message`.
      - At least one MUST be populated; the agent's run() validates
        this at entry and surfaces a structured fail-honest output
        rather than raising.

    When D13 lands and Supervisor's prompt is updated to be
    more shape-aware, this can tighten to require `code`.
    """

    model_config = ConfigDict(extra="ignore")

    # Pass 3c E2's intended primary field. Optional in v1 because
    # Supervisor doesn't reliably emit it (see class docstring).
    code: str | None = Field(default=None, max_length=20_000)
    # Supervisor commonly emits one of these for code-flavored
    # requests; the agent resolves whichever is populated to
    # _resolved_code at run-time.
    question: str | None = Field(default=None, max_length=20_000)
    task: str | None = Field(default=None, max_length=20_000)
    user_message: str | None = Field(default=None, max_length=20_000)

    problem_context: str | None = Field(default=None, max_length=4_000)
    mode: str | None = Field(
        default=None,
        max_length=40,
        description=(
            "Optional caller hint: 'pr_review', 'chat_help', or "
            "'rubric_score'. When absent the agent infers and logs "
            "the inference via log_event."
        ),
    )
    language: str | None = Field(default=None, max_length=40)
    test_results: str | None = Field(default=None, max_length=4_000)
    rubric: str | None = Field(default=None, max_length=4_000)
    request_id: str | None = Field(default=None, max_length=60)

    def resolved_code(self) -> str | None:
        """Pick the first populated input-text field.

        Order: code (Pass 3c E2 intent) > question > task >
        user_message. Returns None when all four are empty/None;
        the agent's run() handles that case with a fail-honest
        chat_help response rather than raising.
        """
        for field in (self.code, self.question, self.task, self.user_message):
            if field and field.strip():
                return field
        return None


# ── Prompt loader ──────────────────────────────────────────────────


_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Read a prompt file from the prompts directory.

    No inline fallback — the deployed prompt is load-bearing for
    correct behavior (mode discrimination, no-execution constraint,
    handoff guidance, brand identity). A missing file is a
    deployment bug, not a degraded-but-functional state.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file missing: {path}. The prompt is required; "
            "no inline fallback exists for senior_engineer."
        )
    return path.read_text()


# ── The agent ──────────────────────────────────────────────────────


class SeniorEngineerAgent(AgenticBaseAgent[SeniorEngineerInput]):
    """Code review, debugging help, and rubric scoring — three modes,
    one agent.

    Per Pass 3c E2: merged successor to code_review +
    coding_assistant + the legacy senior_engineer. v1 is LLM-only —
    sandbox tools deferred to D14. The deployed prompt forbids
    execution claims; the agent reasons about code as text.
    """

    name: ClassVar[str] = "senior_engineer"
    description: ClassVar[str] = (
        "Reviews student code with a senior engineer's voice — direct, "
        "kind, no sycophancy. Three modes: pr_review, chat_help, "
        "rubric_score. Reads prior submissions and prior reviews to "
        "track patterns. v1 LLM-only; does not execute code."
    )
    input_schema: ClassVar[type[AgentInput]] = SeniorEngineerInput

    # Intended smart-tier model; factory routes to MiniMax-M2.7 when
    # MINIMAX_API_KEY is set. Dynamic resolution in
    # agentic_base.execute() ensures the actual model is captured in
    # agent_actions per D10 Phase 1.2's _track_llm_usage wiring.
    model_name: ClassVar[str] = "claude-sonnet-4-6"

    # ── Five primitive flags per Pass 3c E2 ───────────────────────
    uses_memory: ClassVar[bool] = True
    uses_tools: ClassVar[bool] = True
    uses_inter_agent: ClassVar[bool] = True
    uses_self_eval: ClassVar[bool] = False
    uses_proactive: ClassVar[bool] = False

    # uses_inter_agent=True declares the intent to coordinate with
    # other agents; in v1 (Option B per handoff-protocol-d11-d13.md)
    # the coordination happens up-front via Supervisor's chain
    # construction reading handoff_targets from capability.py, NOT
    # post-hoc via populated handoff_request returns. allowed_callees
    # mirrors the capability declaration so the executor's
    # registered-edges check has the targets available when D13
    # flips on post-hoc handoff.
    allowed_callers: ClassVar[tuple[str, ...]] = ()
    allowed_callees: ClassVar[tuple[str, ...]] = (
        "mock_interview",
        "learning_coach",
    )

    # Tool-permission set per Pass 3d §C.1:
    #   • read:agent_memory   universal memory_recall + the two lookup tools
    #   • write:agent_memory  universal memory_write + _record_interaction
    #   • read:student_data   the two lookup tools (memory-backed reads
    #                         under user-scoped keys)
    #   • write:audit_log     log_event for mode-inference observability
    permissions: ClassVar[frozenset[str]] = frozenset(
        {
            "read:agent_memory",
            "write:agent_memory",
            "read:student_data",
            "write:audit_log",
        }
    )

    # ── Chat path ──────────────────────────────────────────────────

    async def run(
        self, input: SeniorEngineerInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Single review/help/score path:

          1. Recall prior reviews + similar prior submissions for
             this student so the LLM can reference patterns and call
             out regressions (the lookup tools live in
             tools/agent_specific/senior_engineer; this method calls
             them directly via tool_call rather than relying on
             Anthropic tool-use which isn't wired — see
             docs/followups/anthropic-tool-use-protocol.md).
          2. Resolve mode (caller-supplied or inferred); when
             inferred, emit a log_event for D17 dashboards.
          3. Build the prompt with code + problem_context + memories
             + lookup data + mode hint + the SeniorEngineerOutput
             schema instructions.
          4. Invoke the LLM. Track usage via _track_llm_usage so
             cost_inr lands in agent_actions per D10 Phase 1.2.
          5. Parse against SeniorEngineerOutput. Force
             handoff_request=None per Option B (the prompt is
             instructed to keep it null, but defense-in-depth here
             ensures D11 never ships a phantom handoff_request even
             if the LLM ignores the prompt).
          6. Stash an interaction memory at
             feedback:code_review:{date} so future invocations can
             surface the verdict + observed patterns.
        """
        resolved_code = input.resolved_code()
        if resolved_code is None:
            # No input-text field populated. Fail-honest with a
            # chat_help shape so the response is schema-valid; never
            # raise to dispatch (treated as specialist_error).
            log.warning(
                "senior_engineer.no_input_text",
                user_id=str(ctx.user_id) if ctx.user_id else None,
            )
            fallback = SeniorEngineerOutput(
                mode="chat_help",
                explanation=(
                    "I didn't see any code or question in this "
                    "request. Could you paste the code you'd like me "
                    "to review, along with what you're trying to "
                    "accomplish?"
                ),
                patterns_observed=[],
            )
            payload = fallback.model_dump(mode="json")
            payload["answer"] = self._compose_answer_text(fallback)
            return payload

        memories = await self._recall_engineering_memories(
            resolved_code=resolved_code, ctx=ctx
        )
        lookup_results = await self._gather_lookup_data(
            resolved_code=resolved_code, ctx=ctx
        )
        resolved_mode, was_inferred = self._resolve_mode(input)

        if was_inferred:
            await self._log_mode_inference(
                input=input, resolved_mode=resolved_mode, ctx=ctx
            )

        answer_payload = await self._call_llm(
            input=input,
            resolved_code=resolved_code,
            resolved_mode=resolved_mode,
            mode_was_inferred=was_inferred,
            memories=memories,
            lookup_results=lookup_results,
            ctx=ctx,
        )

        # Defense-in-depth: the prompt instructs the LLM to keep
        # handoff_request=null in v1, but if the LLM ignores that we
        # zero it out here. D11 never ships a populated
        # handoff_request; D13 can lift this guard when post-hoc
        # routing wires up.
        if answer_payload.get("handoff_request") is not None:
            log.info(
                "senior_engineer.dropped_phantom_handoff_request",
                target=str(answer_payload["handoff_request"]),
                user_id=str(ctx.user_id) if ctx.user_id else None,
            )
            answer_payload["handoff_request"] = None

        # Best-effort memory write for the interaction. Wrap in
        # asyncpg-rollback discipline per
        # docs/followups/asyncpg-rollback-discipline.md — a poisoned
        # session here would otherwise propagate and break
        # _finalize_action_log's audit write.
        try:
            await self._record_interaction(
                input=input,
                resolved_code=resolved_code,
                answer_payload=answer_payload,
                ctx=ctx,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "senior_engineer.memory_write_failed",
                error=str(exc),
                user_id=str(ctx.user_id) if ctx.user_id else None,
            )
            try:
                await ctx.session.rollback()
            except Exception as rollback_exc:  # noqa: BLE001
                log.error(
                    "senior_engineer.memory_write_rollback_failed",
                    original_error=str(exc),
                    rollback_error=str(rollback_exc),
                    user_id=str(ctx.user_id) if ctx.user_id else None,
                )

        return answer_payload

    # ── Mode inference ─────────────────────────────────────────────

    @staticmethod
    def _resolve_mode(input: SeniorEngineerInput) -> tuple[str, bool]:
        """Return (resolved_mode, was_inferred).

        Caller-supplied mode wins. When absent, infer from input
        shape:
          • rubric supplied   → rubric_score
          • problem_context   → pr_review (formal review request)
          • otherwise         → chat_help (conversational debug)
        The prompt guides the LLM to honor the resolved mode.
        """
        valid = {"pr_review", "chat_help", "rubric_score"}
        if input.mode and input.mode in valid:
            return input.mode, False

        if input.rubric:
            return "rubric_score", True
        if input.problem_context:
            return "pr_review", True
        return "chat_help", True

    async def _log_mode_inference(
        self,
        *,
        input: SeniorEngineerInput,
        resolved_mode: str,
        ctx: AgentContext,
    ) -> None:
        """Emit a log_event so D17 dashboards can chart inference
        accuracy + per-shape distribution over time. Tool failure
        here is non-blocking — the run continues either way."""
        signals: dict[str, Any] = {
            "has_problem_context": input.problem_context is not None,
            "has_rubric": input.rubric is not None,
            "has_test_results": input.test_results is not None,
            "code_length": len(input.code),
        }
        try:
            await self.tool_call(
                "log_event",
                {
                    "event_name": "senior_engineer.mode_inferred",
                    "severity": "info",
                    "properties": {
                        "inferred_mode": resolved_mode,
                        "input_shape_signals": signals,
                        "user_id": (
                            str(ctx.user_id) if ctx.user_id else None
                        ),
                    },
                },
                ctx,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "senior_engineer.log_event_failed",
                error=str(exc),
                resolved_mode=resolved_mode,
            )

    # ── Memory recall ──────────────────────────────────────────────

    async def _recall_engineering_memories(
        self,
        *,
        resolved_code: str,
        ctx: AgentContext,
    ) -> dict[str, list[dict[str, Any]]]:
        """Pull two memory shapes the prompt cares about:

          • Pattern history under senior_engineer:pattern:{slug} —
            structured recall, recency-ordered.
          • Topical recall against the submitted code — semantic, so
            the LLM sees prior submissions whose embeddings are
            close to this one.
        """
        if ctx.user_id is None:
            return {"patterns": [], "related": []}

        store = self.memory(ctx)

        patterns = await store.recall(
            "senior_engineer:pattern",
            user_id=ctx.user_id,
            agent_name=self.name,
            scope="user",
            mode="structured",
            k=10,
        )
        # Semantic match against the submitted code — surfaces prior
        # submissions whose embeddings cluster near this one. Bounded
        # to k=5 to keep prompt size manageable.
        related = await store.recall(
            resolved_code[:1500],
            user_id=ctx.user_id,
            agent_name=self.name,
            scope="user",
            mode="semantic",
            k=5,
        )

        def _project(rows: Any) -> list[dict[str, Any]]:
            return [
                {
                    "key": r.key,
                    "value": r.value,
                    "similarity": r.similarity,
                }
                for r in rows
            ]

        return {
            "patterns": _project(patterns),
            "related": _project(related),
        }

    # ── Tool dispatch ──────────────────────────────────────────────

    async def _gather_lookup_data(
        self,
        *,
        resolved_code: str,
        ctx: AgentContext,
    ) -> dict[str, Any]:
        """Call the two senior_engineer-specific lookup tools.

        Both wrap MemoryStore.recall internally and apply the
        asyncpg-rollback discipline at their boundary, so failures
        return safe defaults rather than poisoning ctx.session.

        Speculative call pattern (per
        docs/followups/anthropic-tool-use-protocol.md): we run both
        reads on every invocation rather than letting the LLM
        request them via tool-use protocol. The reads are cheap
        (memory queries against indexed columns), idempotent, and
        user-scoped — same shape as billing_support's speculative
        pattern.
        """
        if ctx.user_id is None:
            return {"prior_reviews": [], "prior_submissions": []}

        prior_reviews_result = await self.tool_call(
            "lookup_prior_reviews",
            {"student_id": str(ctx.user_id), "limit": 8},
            ctx,
        )
        prior_submissions_result = await self.tool_call(
            "lookup_prior_submissions",
            {
                "student_id": str(ctx.user_id),
                "similar_to_code": resolved_code[:2000],
                "limit": 5,
            },
            ctx,
        )

        def _safe_extract(result: Any, key: str) -> list[Any]:
            if result.status != "ok" or result.output is None:
                return []
            payload = (
                result.output.model_dump(mode="json")
                if hasattr(result.output, "model_dump")
                else result.output
            )
            return payload.get(key, []) if isinstance(payload, dict) else []

        return {
            "prior_reviews": _safe_extract(prior_reviews_result, "reviews"),
            "prior_submissions": _safe_extract(
                prior_submissions_result, "submissions"
            ),
        }

    # ── LLM call ───────────────────────────────────────────────────

    async def _call_llm(
        self,
        *,
        input: SeniorEngineerInput,
        resolved_code: str,
        resolved_mode: str,
        mode_was_inferred: bool,
        memories: dict[str, list[dict[str, Any]]],
        lookup_results: dict[str, Any],
        ctx: AgentContext,
    ) -> dict[str, Any]:
        """Invoke the smart-tier LLM, parse SeniorEngineerOutput.

        On parse failure: degrade to a safe pr_review-shaped
        SeniorEngineerOutput with a "I had trouble structuring this
        review" answer so the response is always schema-valid. Never
        raise to the caller — the dispatch_single contract treats
        raises as specialist_error which then triggers fail-honest
        paths the student sees as 500s.

        Tracks LLM usage via _track_llm_usage so
        AgenticBaseAgent._finalize_action_log writes cost_inr to
        agent_actions for the cost-ceiling view.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        system_prompt = _load_prompt("senior_engineer")
        context_block = self._build_context_block(
            input=input,
            resolved_code=resolved_code,
            resolved_mode=resolved_mode,
            mode_was_inferred=mode_was_inferred,
            memories=memories,
            lookup_results=lookup_results,
        )

        # The user block puts the resolved mode + the code in a
        # clearly-tagged shape so the LLM doesn't have to parse out
        # which file the code is in.
        user_block = (
            f"{context_block}\n\n"
            f"[Resolved mode]\n{resolved_mode}\n\n"
            f"[Code under review]\n```\n{resolved_code}\n```\n\n"
            "Respond with a single JSON object matching the "
            "SeniorEngineerOutput schema for this mode. No prose "
            "before or after."
        )
        messages: list[Any] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_block),
        ]

        llm = self._build_llm(max_tokens=2000)
        try:
            response = await llm.ainvoke(messages)
            self._track_llm_usage(ctx, response)
            raw = self._extract_text(response.content)
            parsed = self._parse_json_object(raw)
            output = SeniorEngineerOutput.model_validate(parsed)
            payload = output.model_dump(mode="json")
            # Synthesize a top-level `answer` field for the
            # dispatch layer's _extract_text projection. The output
            # schema itself doesn't carry `answer` (the three-mode
            # shape would make a single field misleading), but the
            # canonical agentic endpoint's response text needs SOME
            # readable string per call. Compose mode-appropriately.
            payload["answer"] = self._compose_answer_text(output)
            return payload
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "senior_engineer.llm_or_parse_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                resolved_mode=resolved_mode,
                user_id=str(ctx.user_id) if ctx.user_id else None,
            )
            fallback = SeniorEngineerOutput(
                mode="chat_help",
                explanation=(
                    "I had trouble structuring this review. Please "
                    "share the code again, and if the issue persists "
                    "email support@aicareeros.com so we can take a "
                    "look."
                ),
                patterns_observed=[],
            )
            payload = fallback.model_dump(mode="json")
            payload["answer"] = self._compose_answer_text(fallback)
            return payload

    # ── Memory write ───────────────────────────────────────────────

    async def _record_interaction(
        self,
        *,
        input: SeniorEngineerInput,
        resolved_code: str,
        answer_payload: dict[str, Any],
        ctx: AgentContext,
    ) -> None:
        """Write two memory rows:

          1. feedback:code_review:{date} — captures the verdict +
             headline + observed patterns so future reviews can
             surface "you fixed the bare-except since last time"
             via lookup_prior_reviews.
          2. submission:code:{date} — captures a snippet of the code
             so lookup_prior_submissions has semantic anchors. We
             cap the snippet at 1500 chars (embedding-budget) and
             store full code in the value dict's `code` field for
             the LLM to read back.
          3. senior_engineer:pattern:{slug} — one row per pattern
             the LLM observed in this submission. Valence reflects
             whether the pattern is a strength (+0.4) or weakness
             (-0.3); future invocations weight stronger memories
             more in the recall ordering.
        """
        from datetime import UTC, datetime

        from app.agents.primitives.memory import MemoryWrite

        if ctx.user_id is None:
            return

        date_bucket = datetime.now(UTC).strftime("%Y-%m-%d")
        store = self.memory(ctx)
        verdict = answer_payload.get("verdict")
        # Negative valence on request_changes; neutral-to-positive
        # otherwise. Pure approve-without-comment is a strong signal.
        if verdict == "request_changes":
            review_valence = -0.2
        elif verdict == "approve" and not answer_payload.get("comments"):
            review_valence = 0.6
        else:
            review_valence = 0.2

        await store.write(
            MemoryWrite(
                user_id=ctx.user_id,
                agent_name=self.name,
                scope="user",
                key=f"feedback:code_review:{date_bucket}",
                value={
                    "mode": answer_payload.get("mode"),
                    "verdict": verdict,
                    "headline": answer_payload.get("headline"),
                    "score": answer_payload.get("score"),
                    "patterns_observed": answer_payload.get(
                        "patterns_observed", []
                    ),
                    "next_step": answer_payload.get("next_step"),
                },
                valence=review_valence,
                confidence=0.85,
            )
        )

        await store.write(
            MemoryWrite(
                user_id=ctx.user_id,
                agent_name=self.name,
                scope="user",
                key=f"submission:code:{date_bucket}",
                value={
                    "code": resolved_code[:8000],
                    "language": input.language,
                    "problem_context": input.problem_context,
                },
                valence=0.0,
                confidence=0.85,
            )
        )

        # Per-pattern rows — one per slug the LLM emitted.
        for pattern_slug in answer_payload.get("patterns_observed", []) or []:
            if not isinstance(pattern_slug, str) or not pattern_slug:
                continue
            await store.write(
                MemoryWrite(
                    user_id=ctx.user_id,
                    agent_name=self.name,
                    scope="user",
                    key=f"senior_engineer:pattern:{pattern_slug}",
                    value={
                        "observed_at": date_bucket,
                        "context_verdict": verdict,
                    },
                    # Patterns named in a request_changes review skew
                    # negative; patterns named in an approve review
                    # are typically strengths.
                    valence=-0.3 if verdict == "request_changes" else 0.4,
                    confidence=0.75,
                )
            )

    # ── Helpers ────────────────────────────────────────────────────

    def _build_context_block(
        self,
        *,
        input: SeniorEngineerInput,
        resolved_code: str,
        resolved_mode: str,
        mode_was_inferred: bool,
        memories: dict[str, list[dict[str, Any]]],
        lookup_results: dict[str, Any],
    ) -> str:
        """Render the optional anchors + recalled memories + lookup
        results into a prose block. Empty fields stay out (less
        noise = better reasoning)."""
        import json as _json

        parts: list[str] = []
        if input.problem_context:
            parts.append(
                f"[Problem context]\n{input.problem_context}"
            )
        if input.language:
            parts.append(f"[Language]\n{input.language}")
        if input.rubric:
            parts.append(f"[Rubric]\n{input.rubric}")
        if input.test_results:
            parts.append(
                f"[Test results provided by caller]\n{input.test_results}"
            )

        if mode_was_inferred:
            parts.append(
                "[Mode inference note]\n"
                f"Caller did not specify mode; agent inferred "
                f"{resolved_mode!r} from input shape."
            )

        patterns = memories.get("patterns", [])
        if patterns:
            parts.append(
                "[Patterns previously observed in this student's code]\n"
                + "\n".join(
                    f"  - {p['key']}: {p['value']}"
                    for p in patterns
                    if p.get("value") is not None
                )
            )

        related = memories.get("related", [])
        if related:
            parts.append(
                "[Related prior submissions (semantic match)]\n"
                + "\n".join(
                    f"  - {r['key']}: {_json.dumps(r['value'])[:300]}"
                    for r in related
                )
            )

        prior_reviews = lookup_results.get("prior_reviews", [])
        if prior_reviews:
            parts.append(
                "[Prior reviews this student received from senior_engineer]\n"
                + _json.dumps(prior_reviews[:5])[:1500]
            )

        prior_submissions = lookup_results.get("prior_submissions", [])
        if prior_submissions:
            parts.append(
                "[Prior code submissions, similar to current]\n"
                + _json.dumps(prior_submissions[:3])[:1500]
            )

        return "\n\n".join(parts) if parts else "[No prior context]"

    @staticmethod
    def _compose_answer_text(output: SeniorEngineerOutput) -> str:
        """Render the SeniorEngineerOutput as the human-readable
        text the canonical agentic endpoint surfaces in `response`.

        Per-mode composition:
          • chat_help    → explanation (+ optional code_suggestion)
          • pr_review    → headline + strengths + numbered comments
                            (line + severity + message) + next_step
          • rubric_score → score line + rubric_feedback

        Dispatch layer's _extract_text reads the synthesized
        `answer` key from the dict-return; the structured output
        stays available in agent_actions.output_data for trace +
        UI rendering of the structured shape.
        """
        if output.mode == "chat_help":
            parts = [output.explanation or ""]
            if output.code_suggestion:
                parts.append(f"\n\n```\n{output.code_suggestion}\n```")
            return "".join(parts).strip()

        if output.mode == "rubric_score":
            head = (
                f"Score: {output.score}/100"
                if output.score is not None
                else "Rubric scoring complete."
            )
            return (head + "\n\n" + (output.rubric_feedback or "")).strip()

        # pr_review (default)
        parts: list[str] = []
        if output.headline:
            parts.append(output.headline)
        if output.verdict:
            parts.append(f"Verdict: {output.verdict}")
        if output.strengths:
            parts.append(
                "Strengths:\n"
                + "\n".join(f"  - {s}" for s in output.strengths)
            )
        if output.comments:
            comment_lines: list[str] = ["Comments:"]
            for c in output.comments:
                location = (
                    f"line {c.line}" if c.line is not None else "whole-file"
                )
                comment_lines.append(
                    f"  [{c.severity} @ {location}] {c.message}"
                )
                if c.suggested_change:
                    comment_lines.append(
                        f"    suggested:\n      {c.suggested_change}"
                    )
            parts.append("\n".join(comment_lines))
        if output.next_step:
            parts.append(f"Next step: {output.next_step}")
        return "\n\n".join(parts).strip() or "Review complete."

    def _build_llm(self, *, max_tokens: int = 2000) -> Any:
        """Build the LLM. Smart tier per Pass 3c E2 — code review
        benefits from depth (correctness reasoning, edge-case
        thinking) that the fast tier doesn't reliably deliver."""
        from app.agents.llm_factory import build_llm

        return build_llm(max_tokens=max_tokens, tier="smart")

    @staticmethod
    def _extract_text(content: Any) -> str:
        """Flatten LangChain content shapes (str | list[dict]) into
        the first text block. Mirrors billing_support's helper —
        per the user-memory note, MiniMax responses are list-of-dict
        with thinking blocks we have to skip."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        return str(block.get("text", ""))
                    if block.get("type") == "thinking":
                        continue
                if isinstance(block, str):
                    return block
            return ""
        return str(content)

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any]:
        """Extract the first balanced JSON object from raw text.

        Tolerant of leading/trailing prose, markdown fences, and the
        occasional explanatory paragraph the LLM sometimes emits
        despite the prompt's "JSON only" instruction.
        """
        import json as _json

        text = raw.strip()
        # Strip a leading code fence if present.
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()
        # Find the first balanced object.
        start = text.find("{")
        if start == -1:
            raise ValueError("no JSON object found in response")
        depth = 0
        in_str = False
        escape = False
        for i, ch in enumerate(text[start:], start=start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    return _json.loads(candidate)
        raise ValueError("unbalanced JSON object in response")


__all__ = ["SeniorEngineerAgent", "SeniorEngineerInput"]
