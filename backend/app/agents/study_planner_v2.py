"""D12 / Pass 3c E4 — study_planner agent (canonical AgenticBaseAgent).

New agent — no legacy BaseAgent predecessor for the study_planner role
(the legacy adaptive_path.py covers a narrower version of this function
and is NOT deprecated by D12; study_planner_v2 is a new registration).

Five primitive flags:
  uses_memory       = True   # tracks session history, plan:session:* keys
  uses_tools        = True   # 6 tools: goal_contract, SRS, capstone, history,
                             # commit_plan (write), track_adherence (write)
  uses_inter_agent  = True   # handoff_targets to Supervisor (career_coach)
  uses_self_eval    = False  # plan generation; critic loop deferred
  uses_proactive    = True   # DECLARES INTENT ONLY — no @proactive decorator,
                             # no nightly_adherence_check method body.
                             # Full implementation deferred to D16.
                             # See docs/followups/study-planner-proactive-d16.md

Deferral A: @proactive(cron="0 22 * * *") nightly trigger → D16.
  The uses_proactive=True flag is the only D12 deliverable for proactive.
  D16 reads this flag to wire the nightly trigger at boot without
  having to search for the agent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, ClassVar

import structlog
from pydantic import ConfigDict, Field

from app.agents.agentic_base import AgentContext, AgentInput, AgenticBaseAgent
from app.agents.parsing_helpers import strip_extra_fields, truncate_to_schema
from app.schemas.agents.study_planner import StudyPlannerOutput

log = structlog.get_logger().bind(layer="study_planner")


# ── Input schema ───────────────────────────────────────────────────


class StudyPlannerInput(AgentInput):
    """Per Pass 3c E4 — with Supervisor shape-variability tolerance.

    Mode may be supplied by the Supervisor or inferred from input shape.
    """

    model_config = ConfigDict(extra="ignore")

    # Mode hint — optional; inferred if absent.
    mode: str | None = Field(
        default=None,
        max_length=40,
        description="One of: weekly_plan, session_plan, adherence_check. Inferred if absent.",
    )

    # Supervisor shape synonyms.
    user_message: str | None = Field(default=None, max_length=4_000)
    question: str | None = Field(default=None, max_length=4_000)
    task: str | None = Field(default=None, max_length=4_000)

    # Optional structured hints.
    week_starting: str | None = Field(default=None, max_length=20)
    session_duration_minutes: int | None = Field(default=None, ge=15, le=480)
    session_date: str | None = Field(default=None, max_length=20)

    def resolved_message(self) -> str | None:
        for field in (self.user_message, self.question, self.task):
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
            "no inline fallback exists for study_planner."
        )
    return path.read_text()


# ── The agent ──────────────────────────────────────────────────────


class StudyPlannerAgent(AgenticBaseAgent[StudyPlannerInput]):
    """Study plan generation calibrated to actual weekly hours and due dates.

    Three modes: weekly_plan, session_plan, adherence_check. Mode is
    inferred from input shape when not explicitly supplied; inference
    is logged via log_event for D17 dashboards.

    uses_proactive=True declares intent for D16's nightly adherence trigger.
    No proactive infrastructure is wired in D12.
    """

    name: ClassVar[str] = "study_planner"
    description: ClassVar[str] = (
        "Builds study plans calibrated to the student's weekly hours "
        "commitment, SRS due cards, capstone deadlines, and recent session "
        "history. Three modes: weekly plan, single-session plan, adherence "
        "check. Also used by the nightly proactive trigger (D16)."
    )
    input_schema: ClassVar[type[AgentInput]] = StudyPlannerInput

    # Intended smart-tier model; factory routes to MiniMax-M2.7 when
    # MINIMAX_API_KEY is set. Dynamic resolution in agentic_base.execute()
    # ensures the actual model is captured in agent_actions.
    model_name: ClassVar[str] = "claude-sonnet-4-6"

    # ── Five primitive flags per Pass 3c E4 ───────────────────────
    uses_memory: ClassVar[bool] = True
    uses_tools: ClassVar[bool] = True
    uses_inter_agent: ClassVar[bool] = True
    uses_self_eval: ClassVar[bool] = False
    # Declares proactive intent; D16 reads this at boot to register the
    # nightly cron. No @proactive decorator in D12 — see module docstring.
    uses_proactive: ClassVar[bool] = True

    allowed_callers: ClassVar[tuple[str, ...]] = ()
    allowed_callees: ClassVar[tuple[str, ...]] = ("career_coach",)

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
        self, input: StudyPlannerInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Study planning path:

          1. Resolve mode (caller-supplied or inferred from input shape).
          2. When inferred, emit log_event (mode_inferred) for dashboards.
          3. Call six tools to gather the student's planning state.
          4. Build the prompt with tool results + mode hint.
          5. Invoke LLM, parse StudyPlannerOutput.
          6. Enforce handoff_request=None (Option B).
          7. Commit the plan to memory via commit_plan (write tool).
        """
        from app.agents.llm_factory import build_llm

        resolved_msg = input.resolved_message()
        resolved_mode, was_inferred = self._resolve_mode(input)

        if was_inferred and resolved_msg:
            await self._log_mode_inference(
                resolved_mode=resolved_mode,
                input_signals=resolved_msg[:200],
                ctx=ctx,
            )

        # ── Tool calls (D12 CP3 Part H.1: use AgenticBaseAgent.tool_call,
        # not bespoke ToolExecutor — the canonical helper at
        # agentic_base.py:496 constructs ToolCallContext correctly) ──
        student_id = ctx.user_id

        contract_data = await _safe_tool(
            self, ctx, "study_planner_read_goal_contract",
            {"student_id": str(student_id)} if student_id else {},
        )
        srs_data = await _safe_tool(
            self, ctx, "read_due_srs_cards",
            {"student_id": str(student_id), "days_ahead": 7} if student_id else {},
        )
        capstone_data = await _safe_tool(
            self, ctx, "read_active_capstone",
            {"student_id": str(student_id)} if student_id else {},
        )
        history_data = await _safe_tool(
            self, ctx, "read_recent_session_history",
            {"student_id": str(student_id), "days": 14} if student_id else {},
        )

        # ── LLM call ──────────────────────────────────────────────
        system_prompt = _load_prompt("study_planner")
        user_block = _build_user_block(
            message=resolved_msg or "",
            mode=resolved_mode,
            contract=contract_data,
            srs=srs_data,
            capstone=capstone_data,
            history=history_data,
            week_starting=input.week_starting,
            session_date=input.session_date,
            session_duration_minutes=input.session_duration_minutes,
        )

        # D12 CP3 Phase 4 (Bug 16 sibling): bumped 1800 → 8192. Same
        # rationale as career_coach — expanded output schema + MiniMax
        # thinking blocks need headroom; MiniMax billed-per-token so
        # worst-case cost is unchanged.
        llm = build_llm(max_tokens=8192, tier="smart")
        response = await llm.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_block},
            ]
        )
        raw = _extract_text(response)
        output = _parse_output(raw)

        # Defense-in-depth: Option B.
        output.handoff_request = None

        payload = output.model_dump(mode="json")
        # Projection for dispatch._extract_text.
        payload["answer"] = _compose_answer(output)

        # ── Commit plan to memory (write path — raises on failure) ─
        await self._commit_plan(output=output, ctx=ctx)

        return payload

    @staticmethod
    def _resolve_mode(input: StudyPlannerInput) -> tuple[str, bool]:
        """Return (mode, was_inferred).

        Caller-supplied wins. Inferred from structured hints first,
        then from text keywords.
        """
        valid = {"weekly_plan", "session_plan", "adherence_check"}
        if input.mode and input.mode in valid:
            return input.mode, False

        # Structured hints are strong signals.
        if input.session_duration_minutes is not None or input.session_date:
            return "session_plan", True
        if input.week_starting:
            return "weekly_plan", True

        # Text keyword inference.
        msg = (input.user_message or input.question or input.task or "").lower()
        if any(k in msg for k in ("this week", "next week", "weekly", "schedule")):
            return "weekly_plan", True
        if any(k in msg for k in ("today", "right now", "this session", "i have")):
            return "session_plan", True
        if any(k in msg for k in ("how am i doing", "on track", "adherence", "progress")):
            return "adherence_check", True

        return "weekly_plan", True  # default

    async def _log_mode_inference(
        self,
        *,
        resolved_mode: str,
        input_signals: str,
        ctx: AgentContext,
    ) -> None:
        """Emit log_event for mode-inference observability (D17 dashboards).

        D12 CP3 Part F.1 fix: log_event tool's input schema is
        ``LogEventInput(event_name, properties, severity)`` with
        ``extra="forbid"``. Earlier shape passed event_type/agent/payload —
        all rejected silently by the broad except.

        D12 CP3 Part H.1 fix: route via self.tool_call (the canonical
        AgenticBaseAgent helper) instead of constructing a bespoke
        ToolExecutor. The bespoke construction had the wrong constructor
        kwargs and used a non-existent .call() method.
        """
        try:
            await self.tool_call(
                "log_event",
                {
                    "event_name": "study_planner.mode_inferred",
                    "properties": {
                        "inferred_mode": resolved_mode,
                        "input_signals": input_signals,
                    },
                    "severity": "info",
                },
                ctx,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("study_planner.log_mode_inference_failed", error=str(exc))

    # D12 CP3 Part F.2 — agent mode names → tool plan_type Literal.
    # Tool's Literal is "weekly" | "session" (no _plan suffix, no
    # adherence_check). Mapping lives at the agent layer rather than
    # broadening the tool Literal — the tool's contract is narrower
    # by design (memory key shape "plan:weekly:..." / "plan:session:...").
    _PLAN_TYPE_MAP: ClassVar[dict[str, str]] = {
        "weekly_plan": "weekly",
        "session_plan": "session",
    }

    async def _commit_plan(
        self, *, output: StudyPlannerOutput, ctx: AgentContext
    ) -> None:
        """Write plan to memory via commit_plan tool (write path — raises).

        adherence_check is read-only by spec (Pass 3c E4) — no plan to
        commit; skip with a log line.

        D12 CP3 Part H.1 fix: route via self.tool_call.
        """
        import datetime

        plan_type = self._PLAN_TYPE_MAP.get(output.mode)
        if plan_type is None:
            log.info(
                "study_planner.commit_plan_skipped",
                reason="adherence_check_or_unknown_mode",
                mode=output.mode,
            )
            return

        today = datetime.date.today().isoformat()

        # commit_plan raises on failure — write paths don't fail-soft.
        await self.tool_call(
            "commit_plan",
            {
                "student_id": str(ctx.user_id) if ctx.user_id else None,
                "plan_type": plan_type,
                "idempotency_key": today,
                "plan_data": output.model_dump(mode="json"),
            },
            ctx,
        )


# ── Helpers ───────────────────────────────────────────────────────


async def _safe_tool(
    agent: Any, ctx: AgentContext, tool_name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Run a read tool through agent.tool_call; convert Pydantic output to dict.

    D12 CP3 Part H.1 fix: the canonical executor returns ToolCallResult
    whose `output` is a Pydantic BaseModel (or None), not a dict. The
    prompt builder json.dumps the result, so we model_dump first.
    """
    try:
        result = await agent.tool_call(tool_name, args, ctx)
        if result.output is None:
            return {}
        return result.output.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        log.debug("study_planner.tool_skipped", tool=tool_name, error=str(exc))
        return {}


def _build_user_block(
    *,
    message: str,
    mode: str,
    contract: dict[str, Any],
    srs: dict[str, Any],
    capstone: dict[str, Any],
    history: dict[str, Any],
    week_starting: str | None,
    session_date: str | None,
    session_duration_minutes: int | None,
) -> str:
    parts = [f"## Student message\n\n{message}"]
    parts.append(f"## Resolved mode\n\n{mode}")
    if week_starting:
        parts.append(f"## Week starting\n\n{week_starting}")
    if session_date:
        parts.append(f"## Session date\n\n{session_date}")
    if session_duration_minutes:
        parts.append(f"## Session duration\n\n{session_duration_minutes} minutes")
    if contract:
        parts.append(f"## Goal contract\n\n```json\n{json.dumps(contract, indent=2)}\n```")
    if srs:
        parts.append(f"## SRS due cards\n\n```json\n{json.dumps(srs, indent=2)}\n```")
    if capstone:
        parts.append(f"## Active capstone\n\n```json\n{json.dumps(capstone, indent=2)}\n```")
    if history:
        parts.append(f"## Recent session history\n\n```json\n{json.dumps(history, indent=2)}\n```")
    parts.append(
        "## Instructions\n\n"
        "Return a single JSON object matching StudyPlannerOutput. "
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
    final answer).

    D12 CP3 Phase 2 fix (Bug 10a): the prior implementation used
    ``hasattr(block, "type")`` which silently fails on dicts and fell
    through to ``return ""`` on every MiniMax response.
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


def _parse_output(raw: str) -> StudyPlannerOutput:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
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
    # fix: strip unknown keys, then enforce string max_length, then
    # validate. Both layers are server-side coercion of LLM output
    # before Pydantic; prompt-level constraints proved unreliable
    # under MiniMax for either shape drift or length overshoot.
    raw_dict = json.loads(text[start : end + 1])
    stripped = strip_extra_fields(raw_dict, StudyPlannerOutput)
    truncated = truncate_to_schema(stripped, StudyPlannerOutput)
    return StudyPlannerOutput.model_validate(truncated)


def _compose_answer(output: StudyPlannerOutput) -> str:
    mode = output.mode
    if mode == "weekly_plan":
        blocks = getattr(output, "daily_blocks", None) or []
        total = getattr(output, "total_hours_planned", None)
        week = getattr(output, "week_starting", None)
        return (
            f"Weekly plan for {week or 'this week'}: "
            f"{len(blocks)} session blocks, {total or '?'} hours planned."
        )
    if mode == "session_plan":
        activities = getattr(output, "activities", None) or []
        duration = getattr(output, "session_duration_minutes", None)
        return (
            f"Session plan: {len(activities)} activities over "
            f"{duration or '?'} minutes."
        )
    if mode == "adherence_check":
        score = getattr(output, "adherence_score", None)
        summary = getattr(output, "summary", None) or ""
        return f"Adherence score: {score:.0%}. {summary}" if score is not None else summary
    return f"{mode} plan generated."
