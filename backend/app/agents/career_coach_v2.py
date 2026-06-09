"""D12 / Pass 3c E3 — career_coach agent (canonical AgenticBaseAgent).

Successor to the legacy BaseAgent career_coach.py. The legacy file
stays until CP4 cutover so AGENT_REGISTRY entries remain intact for
any in-flight sessions that rely on the legacy dispatch path.

Five primitive flags:
  uses_memory       = True   # tracks student progress, mastery signals
  uses_tools        = True   # 4 read tools: progress, contract, capstone, mastery
  uses_inter_agent  = True   # advertises handoff_targets to Supervisor for
                             # up-front chain construction (Option B per
                             # docs/followups/handoff-protocol-d11-d13.md)
  uses_self_eval    = False  # strategy calls; critic loop deferred
  uses_proactive    = False  # student-initiated only

Deferral C: read_market_signals tool is not available. The prompt
acknowledges the gap and instructs the LLM to use general industry
knowledge without inventing statistics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import structlog
from pydantic import ConfigDict, Field

from app.agents.agentic_base import AgentContext, AgentInput, AgenticBaseAgent
from app.agents.parsing_helpers import strip_extra_fields, truncate_to_schema
from app.schemas.agents.career_coach import CareerCoachOutput

log = structlog.get_logger().bind(layer="career_coach")


# ── Input schema ───────────────────────────────────────────────────


class CareerCoachInput(AgentInput):
    """Per Pass 3c E3 — with Supervisor shape-variability tolerance.

    The Supervisor may emit `{"question": "..."}` or `{"task": "..."}` or
    `{"user_message": "..."}` for career-coaching requests. We accept all
    and resolve to the first populated field.
    """

    model_config = ConfigDict(extra="ignore")

    # Primary intent field per Pass 3c E3 spec.
    specific_question: str | None = Field(default=None, max_length=4_000)
    # Supervisor shape synonyms — resolved in _resolved_question().
    question: str | None = Field(default=None, max_length=4_000)
    task: str | None = Field(default=None, max_length=4_000)
    user_message: str | None = Field(default=None, max_length=4_000)

    # Optional context fields the Supervisor may supply.
    target_role: str | None = Field(default=None, max_length=200)
    timeline_weeks: int | None = Field(default=None, ge=1, le=104)

    def resolved_question(self) -> str | None:
        """Pick first populated text field.

        Order: specific_question (intent) > question > task > user_message.
        """
        for field in (
            self.specific_question,
            self.question,
            self.task,
            self.user_message,
        ):
            if field and field.strip():
                return field
        return None


# ── Prompt loader ──────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file missing: {path}. The prompt is required; "
            "no inline fallback exists for career_coach."
        )
    return path.read_text()


# ── The agent ──────────────────────────────────────────────────────


class CareerCoachAgent(AgenticBaseAgent[CareerCoachInput]):
    """Career planning for students transitioning to AI engineering roles.

    Reads student data via four tools, grounds every assessment in actual
    progress + mastery signals, and produces a structured CareerCoachOutput.
    Does not invent market statistics (Deferral C: no read_market_signals).
    """

    name: ClassVar[str] = "career_coach"
    description: ClassVar[str] = (
        "Builds grounded career plans for students targeting production AI "
        "engineering roles. Reads actual exercise scores, capstone status, "
        "mastery signals, and goal contract. Produces structured milestone plans. "
        "Does not invent market data."
    )
    input_schema: ClassVar[type[AgentInput]] = CareerCoachInput

    # Intended smart-tier model; factory routes to MiniMax-M2.7 when
    # MINIMAX_API_KEY is set. Dynamic resolution in agentic_base.execute()
    # ensures the actual model is captured in agent_actions.
    model_name: ClassVar[str] = "claude-sonnet-4-6"

    # ── Five primitive flags per Pass 3c E3 ───────────────────────
    uses_memory: ClassVar[bool] = True
    uses_tools: ClassVar[bool] = True
    uses_inter_agent: ClassVar[bool] = True
    uses_self_eval: ClassVar[bool] = False
    uses_proactive: ClassVar[bool] = False

    # Option B: handoffs declared as Supervisor metadata only.
    # Post-hoc handoff_requests field is always [] in D12.
    allowed_callers: ClassVar[tuple[str, ...]] = ()
    allowed_callees: ClassVar[tuple[str, ...]] = (
        "study_planner",
        "resume_reviewer",
        "mock_interview",
        "portfolio_builder",
    )

    permissions: ClassVar[frozenset[str]] = frozenset(
        {
            "read:agent_memory",
            "write:agent_memory",
            "read:student_data",
            "write:audit_log",
        }
    )

    # ── Run path ──────────────────────────────────────────────────

    async def run(
        self, input: CareerCoachInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Career coaching path:

          1. Resolve the question (Supervisor shape synonym resolution).
          2. Call four read tools (progress, contract, capstone, mastery)
             to ground the response in actual student data.
          3. Build the prompt with tool results + student question.
          4. Invoke LLM, parse CareerCoachOutput.
          5. Enforce handoff_requests=[] (Option B / Deferral C defense).
          6. Best-effort memory write for the session.
        """
        from app.agents.llm_factory import build_llm

        resolved_q = input.resolved_question()
        if resolved_q is None:
            fallback = CareerCoachOutput(
                headline="Tell me what career question is on your mind.",
                current_state_assessment=(
                    "I didn't receive a specific question or goal. "
                    "Please share what you'd like to work on — "
                    "your target role, a timeline concern, or a specific skill gap."
                ),
                plan=_empty_plan(),
                immediate_concerns=[],
                milestones=[],
                suggested_next_action=(
                    "Reply with your specific career question or goal."
                ),
                handoff_requests=[],
            )
            payload = fallback.model_dump(mode="json")
            payload["answer"] = fallback.headline
            return payload

        # ── Tool calls (D12 CP3 Part H.1: use AgenticBaseAgent.tool_call) ──
        # D15 CP3 adds three role-state tools so the response is grounded
        # in the student's actual role progression + accessible content,
        # never fabricated. read_student_accessible_content is filtered to
        # the student's current role per D-E (runtime content discovery,
        # filtered to role identity, never references unfetched content).
        student_id = ctx.user_id
        progress_data = await _safe_tool(
            self, ctx, "read_student_full_progress",
            {"student_id": str(student_id)} if student_id else {},
        )
        contract_data = await _safe_tool(
            self, ctx, "read_goal_contract",
            {"student_id": str(student_id)} if student_id else {},
        )
        capstone_data = await _safe_tool(
            self, ctx, "read_capstone_status",
            {"student_id": str(student_id)} if student_id else {},
        )
        mastery_data = await _safe_tool(
            self, ctx, "read_mastery_summary",
            {"student_id": str(student_id)} if student_id else {},
        )

        # D15 CP3 — role-state grounding ─────────────────────────────
        role_state_data = await _safe_tool(
            self, ctx, "read_student_role_state",
            {"student_id": str(student_id)} if student_id else {},
        )
        # D17b/ITEM 3 — state-aware lead-in signals (Pattern 26).
        # Aggregator returns the 5 fields the prompt branches on for
        # whether/which lead-in to fire. Empty dict on failure → prompt
        # treats as "no signals warrant a lead-in" and handles the
        # question directly (graceful degradation).
        lead_in_signals_data = await _safe_tool(
            self, ctx, "read_student_lead_in_signals",
            {"student_id": str(student_id)} if student_id else {},
        )
        # Filter accessible content to the current role for the
        # default coaching path. The unfiltered union is reserved for
        # when the student asks about cross-role progression — left
        # as a future refinement; for D15 v1 the role-filtered view
        # is the canonical D-E grounding signal.
        current_role_slug = (
            (role_state_data.get("current_role") or {}).get("slug")
            if isinstance(role_state_data, dict)
            else None
        )
        accessible_args: dict[str, Any] = (
            {"student_id": str(student_id)} if student_id else {}
        )
        if current_role_slug:
            accessible_args["role_slug"] = current_role_slug
        accessible_content_data = await _safe_tool(
            self, ctx, "read_student_accessible_content", accessible_args
        )

        # Gate evaluation: target the next adjacent role (not the
        # senior_genai_engineer terminal hop directly), so the LLM
        # sees the immediate gate the student must pass next. The
        # tool raises on non-adjacent or terminal-current; _safe_tool
        # collapses to {} which the prompt builder treats as
        # "evaluation unavailable, reason from role state alone".
        next_role_slug = (
            (role_state_data.get("next_transition") or {}).get(
                "target_role_slug"
            )
            if isinstance(role_state_data, dict)
            else None
        )
        gate_eval_data: dict[str, Any] = {}
        if student_id and next_role_slug:
            gate_eval_data = await _safe_tool(
                self,
                ctx,
                "evaluate_student_against_gate",
                {
                    "student_id": str(student_id),
                    "target_role_slug": next_role_slug,
                },
            )

        # ── LLM call ──────────────────────────────────────────────
        # D17b/ITEM 3 (Path E): the LLM does NOT see lead_in_signals.
        # Lead-in composition is deterministic and happens post-LLM
        # via compose_lead_in_opener (prepended to answer below).
        # Keeping signals out of the user_block avoids the tone-
        # competition + timeout-drift issues the prompt-side approach
        # surfaced in 7-phase verification.
        system_prompt = _load_prompt("career_coach")
        user_block = _build_user_block(
            question=resolved_q,
            progress=progress_data,
            contract=contract_data,
            capstone=capstone_data,
            mastery=mastery_data,
            role_state=role_state_data,
            accessible_content=accessible_content_data,
            gate_eval=gate_eval_data,
            target_role=input.target_role,
            timeline_weeks=input.timeline_weeks,
        )

        # D12 CP3 Phase 4 (Bug 16): bumped 2048 → 8192. The expanded
        # output schema (post-Bug-15 enumeration of WeeklyFocus / ProjectRef /
        # Milestone fields) plus MiniMax thinking blocks (~38% of output)
        # consistently exceeded 2048, truncating mid-JSON. 8192 matches the
        # smart-tier default in llm_factory; MiniMax bills per consumed
        # token so the headroom doesn't change normal-case cost.
        llm = build_llm(max_tokens=8192, tier="smart")
        response = await llm.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_block},
            ]
        )
        # BUG-CP1F fix (2026-05-09): track LLM usage so
        # _finalize_action_log can compute cost_inr. See
        # docs/followups/bug-cp1f-cost-tracking-zero-on-agentic-path.md.
        self._track_llm_usage(ctx, response)
        raw = _extract_text(response)

        output = _parse_output(raw)

        # Defense-in-depth: Option B — never ship populated handoff_requests.
        output.handoff_requests = []

        payload = output.model_dump(mode="json")
        # D17b/ITEM 3 (Path E) — deterministic lead-in opener.
        # Compose from signals (already fetched above) + role-state-
        # derived next-role brief (when available) for gate-cleared
        # framing. Opener is None for healthy students; no change to
        # answer in that case.
        opener = _compose_opener_from_data(
            lead_in_signals_data, role_state_data
        )
        payload["answer"] = (
            f"{opener}\n\n{output.headline}" if opener else output.headline
        )

        # Best-effort interaction memory.
        try:
            await self._record_interaction(
                question=resolved_q, output=output, ctx=ctx
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "career_coach.memory_write_failed",
                error=str(exc),
                user_id=str(ctx.user_id) if ctx.user_id else None,
            )
            try:
                await ctx.session.rollback()
            except Exception as rollback_exc:  # noqa: BLE001
                log.error(
                    "career_coach.memory_write_rollback_failed",
                    original_error=str(exc),
                    rollback_error=str(rollback_exc),
                    user_id=str(ctx.user_id) if ctx.user_id else None,
                )

        return payload

    async def _record_interaction(
        self,
        *,
        question: str,
        output: CareerCoachOutput,
        ctx: AgentContext,
    ) -> None:
        """Write a career_plan memory for future sessions."""
        from app.agents.primitives.memory import MemoryStore, MemoryWrite
        import datetime

        store = MemoryStore(session=ctx.session)
        date_str = datetime.date.today().isoformat()
        await store.write(
            MemoryWrite(
                user_id=ctx.user_id,
                scope="user",
                key=f"career_plan:{date_str}",
                value={
                    "question": question[:500],
                    "headline": output.headline,
                    "target_role": output.plan.target_role if hasattr(output.plan, "target_role") else None,
                    "timeline_weeks": output.plan.timeline_weeks,
                    "immediate_concerns": output.immediate_concerns[:3],
                },
                valence=0.5,
            )
        )


# ── Helpers ───────────────────────────────────────────────────────


async def _safe_tool(
    agent: Any, ctx: AgentContext, tool_name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Call a tool via agent.tool_call; return result.output as dict; {} on failure.

    D12 CP3 Part H.1 fix: route via the canonical AgenticBaseAgent.tool_call
    helper. ToolCallResult.output is a Pydantic model — model_dump it so
    the prompt builder's json.dumps gets a plain dict.
    """
    try:
        result = await agent.tool_call(tool_name, args, ctx)
        if result.output is None:
            return {}
        return result.output.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        log.debug("career_coach.tool_skipped", tool=tool_name, error=str(exc))
        return {}


def _compose_opener_from_data(
    lead_in_signals: dict[str, Any],
    role_state: dict[str, Any],
) -> str | None:
    """D17b/ITEM 3 (Path E) — bridge from tool-call dict outputs to the
    deterministic compose_lead_in_opener function.

    Reconstructs a StudentLeadInSignals instance from the aggregator
    tool's dict output (which is what _safe_tool returns), pulls the
    next-role display name + identity brief from role_state when
    present (for the gate-cleared template's enriched form), and
    delegates to compose_lead_in_opener.

    Returns None when no lead-in fires, or when lead_in_signals is
    empty/malformed (graceful degradation — no opener is the
    safe-default behavior).
    """
    if not isinstance(lead_in_signals, dict) or not lead_in_signals:
        return None

    from app.agents.primitives.lead_in_composer import compose_lead_in_opener
    from app.agents.tools.universal.read_student_lead_in_signals import (
        ReadStudentLeadInSignalsOutput,
    )

    try:
        signals = ReadStudentLeadInSignalsOutput.model_validate(
            lead_in_signals
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("career_coach.lead_in_signal_parse_failed", error=str(exc))
        return None

    # Pull next-role display name + identity brief from role_state for
    # the gate-cleared enriched template. The aggregator's
    # most_recent_transition_completed_at signals which transition
    # completed; role_state.current_role is the role they JUST
    # transitioned INTO (after the transition); so for gate-cleared
    # framing we use current_role's display_name + description as the
    # "new identity" the celebration references.
    display_name: str | None = None
    role_brief: str | None = None
    if isinstance(role_state, dict):
        current = role_state.get("current_role") or {}
        if isinstance(current, dict):
            dn = current.get("display_name")
            desc = current.get("description")
            if isinstance(dn, str) and dn:
                display_name = dn
            if isinstance(desc, str) and desc:
                # Description may be long; take the first sentence so
                # the opener stays compact.
                role_brief = desc.split(".")[0].strip() or None

    return compose_lead_in_opener(
        signals,
        agent_name="career_coach",
        role_identity_brief=role_brief,
        next_role_display_name=display_name,
    )


def _build_user_block(
    *,
    question: str,
    progress: dict[str, Any],
    contract: dict[str, Any],
    capstone: dict[str, Any],
    mastery: dict[str, Any],
    role_state: dict[str, Any],
    accessible_content: dict[str, Any],
    gate_eval: dict[str, Any],
    target_role: str | None,
    timeline_weeks: int | None,
) -> str:
    parts = [f"## Student question\n\n{question}"]
    if target_role:
        parts.append(f"## Target role (caller-supplied)\n\n{target_role}")
    if timeline_weeks:
        parts.append(f"## Timeline (caller-supplied)\n\n{timeline_weeks} weeks")
    # D15 CP3 sections come first so role identity frames every
    # downstream piece of grounding data the LLM reads.
    if role_state and role_state.get("found"):
        parts.append(
            "## Role state\n\n"
            f"```json\n{json.dumps(role_state, indent=2, default=str)}\n```"
        )
    if accessible_content and accessible_content.get("found") is not None:
        parts.append(
            "## Accessible content (filtered to current role)\n\n"
            f"```json\n{json.dumps(accessible_content, indent=2, default=str)}\n```"
        )
    if gate_eval:
        parts.append(
            "## Gate evaluation (current role → next adjacent role)\n\n"
            f"```json\n{json.dumps(gate_eval, indent=2, default=str)}\n```"
        )
    if contract:
        parts.append(f"## Goal contract\n\n```json\n{json.dumps(contract, indent=2)}\n```")
    if progress:
        parts.append(f"## Progress data\n\n```json\n{json.dumps(progress, indent=2)}\n```")
    if capstone:
        parts.append(f"## Capstone status\n\n```json\n{json.dumps(capstone, indent=2)}\n```")
    if mastery:
        parts.append(f"## Mastery summary\n\n```json\n{json.dumps(mastery, indent=2)}\n```")
    parts.append(
        "## Instructions\n\n"
        "Return a single JSON object matching CareerCoachOutput. "
        "No markdown fences, no preamble."
    )
    return "\n\n".join(parts)


def _extract_text(response: Any) -> str:
    """Pull the assistant's text out of a LangChain ChatAnthropic response.

    Handles both shapes:
      • Anthropic SDK native — content blocks as objects with `.type` / `.text`
      • MiniMax Anthropic-compatible endpoint — content blocks as dicts
        like {'type': 'text', 'text': '...'} or {'type': 'thinking', ...}

    Skips thinking blocks (extended-thinking metadata, not the assistant's
    final answer). Per docs/followups/agent-tool-call-discipline.md and
    the user-memory note on LLM response parsing.

    D12 CP3 Phase 2 fix (Bug 10a): the prior implementation used
    ``hasattr(block, "type")`` which silently fails on dicts (returns the
    `dict.type` attribute, which doesn't exist), and fell through to
    ``return ""`` on every MiniMax response.
    """
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, list):
            for block in content:
                # Dict-shape (MiniMax Anthropic-compatible endpoint).
                if isinstance(block, dict):
                    btype = block.get("type")
                    if btype == "text":
                        # Returns first text block; if MiniMax ever produces multi-text-block
                        # responses (e.g., text → thinking → text), this would only return the
                        # first. Acceptable for current MiniMax behavior; revisit if response
                        # shape changes.
                        return str(block.get("text", ""))
                    # thinking blocks: skip — internal reasoning, not the answer.
                    continue
                # Object-shape (Anthropic SDK native).
                if hasattr(block, "type") and getattr(block, "type", None) == "text":
                    return getattr(block, "text", "")
                if hasattr(block, "text"):
                    return block.text
            return ""
        return str(content)
    return str(response)


def _parse_output(raw: str) -> CareerCoachOutput:
    """Extract the first JSON object from LLM output and parse it."""
    import re

    text = raw.strip()
    # Strip fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())

    # Find first balanced { ... }.
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object in LLM output: {text[:200]}")
    depth, end = 0, -1
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        raise ValueError("Unbalanced JSON in LLM output.")

    # D12 CP3 Phase 4 Bug 17 + D13 CP3 Phase 1.8 Bug 23 architectural
    # fix — see parsing_helpers.py. Strip unknown keys (Bug 23) before
    # truncating string overshoots (Bug 17). Preventive retrofit; D12
    # never surfaced Bug 23 live but the helper is mechanical and the
    # composition is the canonical "make LLM output safe" pattern.
    raw_dict = json.loads(text[start : end + 1])
    stripped = strip_extra_fields(raw_dict, CareerCoachOutput)
    truncated = truncate_to_schema(stripped, CareerCoachOutput)
    return CareerCoachOutput.model_validate(truncated)


def _empty_plan() -> Any:
    from app.schemas.agents.career_coach import CareerPlan
    return CareerPlan(
        timeline_weeks=0,
        weekly_focus_areas=[],
        projects_to_complete=[],
        skills_to_develop=[],
    )
