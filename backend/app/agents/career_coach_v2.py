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
from app.agents.parsing_helpers import truncate_to_schema
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

        # ── LLM call ──────────────────────────────────────────────
        system_prompt = _load_prompt("career_coach")
        user_block = _build_user_block(
            question=resolved_q,
            progress=progress_data,
            contract=contract_data,
            capstone=capstone_data,
            mastery=mastery_data,
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
        raw = _extract_text(response)

        output = _parse_output(raw)

        # Defense-in-depth: Option B — never ship populated handoff_requests.
        output.handoff_requests = []

        payload = output.model_dump(mode="json")
        payload["answer"] = output.headline

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


def _build_user_block(
    *,
    question: str,
    progress: dict[str, Any],
    contract: dict[str, Any],
    capstone: dict[str, Any],
    mastery: dict[str, Any],
    target_role: str | None,
    timeline_weeks: int | None,
) -> str:
    parts = [f"## Student question\n\n{question}"]
    if target_role:
        parts.append(f"## Target role (caller-supplied)\n\n{target_role}")
    if timeline_weeks:
        parts.append(f"## Timeline (caller-supplied)\n\n{timeline_weeks} weeks")
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

    # D12 CP3 Phase 4 Bug 17 architectural fix — see parsing_helpers.py.
    raw_dict = json.loads(text[start : end + 1])
    truncated = truncate_to_schema(raw_dict, CareerCoachOutput)
    return CareerCoachOutput.model_validate(truncated)


def _empty_plan() -> Any:
    from app.schemas.agents.career_coach import CareerPlan
    return CareerPlan(
        timeline_weeks=0,
        weekly_focus_areas=[],
        projects_to_complete=[],
        skills_to_develop=[],
    )
