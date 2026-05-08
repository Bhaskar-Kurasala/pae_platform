"""D14b / Pass 3c E8 — practice_curator agent (canonical AgenticBaseAgent).

D14b Checkpoint 4 cutover: net-new agent (no legacy BaseAgent file
existed). CP1 established the schema + stub; CP2 wired the prompt + 4
tool calls; CP3 verified live under MiniMax (3 phases, all clean);
CP4 promoted the file from `practice_curator_v2.py` to the canonical
`practice_curator.py` (D8 example_learning_coach net-new naming
pattern). Schema is defined in app/schemas/agents/practice_curator.py.

First v2 agent producing user-facing content directly (exercises
students consume and attempt).

Five primitive flags (per D-A, D-B, D-C locked decisions):
  uses_memory       = True   # cross-session weakness recall + recent
                             # exercises completed lookup
  uses_tools        = True   # memory_recall + D12-audited DB read tools
                             # (read_student_full_progress, etc.) — wired in CP2
  uses_inter_agent  = False  # handoff_targets is informational metadata only;
                             # orchestration layer dispatches senior_engineer
                             # post-curator, not curator itself
  uses_self_eval    = False  # D-C: no Critic loop; pedagogical quality is not
                             # what Critic measures
  uses_proactive    = False  # student-initiated only

Single-shot shape (D-A): each call generates ONE exercise. No
session_id, no multi-turn state, no memory of prior turns within a
"session". The orchestration loop (student → curator exercise → student
attempt → senior_engineer evaluation → curator next exercise) lives at
the orchestration layer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, ClassVar

import structlog

from app.agents.agentic_base import AgentContext, AgentInput, AgenticBaseAgent
from app.agents.parsing_helpers import strip_extra_fields, truncate_to_schema
from app.schemas.agents.practice_curator import (
    Exercise,
    PracticeCuratorInput,
    PracticeCuratorOutput,
)

log = structlog.get_logger().bind(layer="practice_curator")


# ── Prompt loader ──────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load practice_curator's prompt. Lands in CP2; CP1 stub returns
    a placeholder."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        # CP1 stub — full prompt with per-exercise-type sub-sections
        # lands in CP2.
        return (
            "# Practice Curator (CP1 stub)\n\n"
            "This prompt is a placeholder. The canonical prompt with "
            "per-exercise-type sub-sections lands in D14b CP2."
        )
    return path.read_text()


# ── The agent ──────────────────────────────────────────────────────


class PracticeCuratorAgent(AgenticBaseAgent[PracticeCuratorInput]):
    """Generates one personalized practice exercise per call.

    Per D-A: single-shot. Per D-B: no sandbox dependency in initial
    scope (reference-solution verification deferred). Per D-C: no
    Critic loop, no mandatory validation chain.

    CP1 stub: instantiation, capability flags, and the run() contract
    skeleton. Tool calls + prompt-driven LLM call + memory writes land
    in CP2.
    """

    name: ClassVar[str] = "practice_curator"
    description: ClassVar[str] = (
        "Generates personalized practice exercises matched to the "
        "student's current edge of mastery. Five exercise types: "
        "coding, debugging, system_design, prompt_engineering, "
        "evaluation_rubric. Reads mastery state + recent exercises "
        "from memory to calibrate difficulty and avoid repeats."
    )
    input_schema: ClassVar[type[AgentInput]] = PracticeCuratorInput

    # Intended smart-tier model; factory routes to MiniMax-M2.7 when
    # MINIMAX_API_KEY is set. Dynamic resolution in agentic_base.execute()
    # captures the actual model in agent_actions.
    model_name: ClassVar[str] = "claude-sonnet-4-6"

    # ── Five primitive flags per D-A, D-B, D-C ────────────────────
    uses_memory: ClassVar[bool] = True
    uses_tools: ClassVar[bool] = True
    # D-A: orchestration layer owns the handoff to senior_engineer
    # post-evaluation. The agent itself doesn't dispatch other agents.
    uses_inter_agent: ClassVar[bool] = False
    # D-C: no Critic loop. Critic measures structural output quality;
    # what we'd want is pedagogical quality (will this exercise help
    # the student learn?), and Critic doesn't measure that.
    uses_self_eval: ClassVar[bool] = False
    uses_proactive: ClassVar[bool] = False

    allowed_callers: ClassVar[tuple[str, ...]] = ()
    # Empty — uses_inter_agent=False so the agent never dispatches
    # other agents. handoff_targets in capability is purely
    # informational metadata for the orchestration layer.
    allowed_callees: ClassVar[tuple[str, ...]] = ()

    permissions: ClassVar[frozenset[str]] = frozenset(
        {
            "read:agent_memory",
            "write:agent_memory",
            "read:student_data",
            "write:audit_log",
        }
    )

    # ── Run path (CP1 stub — fills in at CP2) ─────────────────────

    async def run(
        self, input: PracticeCuratorInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Practice curator turn handler.

        Single-shot path per D-A:
          1. Recall pref:target_role (single key recall).
          2. Recall mock_interview:weakness:* prefix (cross-session weaknesses).
          3. Read student progress via read_student_full_progress (D12-audited).
          4. Read recent session history via read_recent_session_history
             (D12-audited; identifies recent exercise attempts to avoid repeats).
          5. Build user_block with caller constraints + student message + recall results.
          6. Call LLM with canonical prompt; extract text via dict-aware
             _extract_text; strip_extra_fields + truncate_to_schema;
             validate PracticeCuratorOutput.
          7. Defense-in-depth: only allow handoff_request when student
             message explicitly mentions evaluation. Otherwise force None.
          8. Compose answer projection.
        """
        from app.agents.llm_factory import build_llm

        student_message = input.resolved_message()

        # ── Recalls ───────────────────────────────────────────────
        target_role = await _safe_recall(
            self, ctx, query="pref:target_role", mode="structured", k=1,
        )
        weaknesses = await _safe_recall(
            self, ctx, query="mock_interview:weakness:", mode="structured", k=10,
        )

        # ── DB reads (D12-audited) ────────────────────────────────
        student_id = ctx.user_id
        progress = await _safe_tool(
            self, ctx, "read_student_full_progress",
            {"student_id": str(student_id)} if student_id else {},
        )
        session_history = await _safe_tool(
            self, ctx, "read_recent_session_history",
            # Pass `days` per the tool's input schema (not `limit`); 14
            # days covers recent activity for the avoid-repeats signal.
            {"student_id": str(student_id), "days": 14} if student_id else {},
        )

        # ── D15 CP4 — role-state grounding ─────────────────────────
        # Two reads: role identity for voice + accessible_curated_problems
        # for the bank-vs-generative D-E decision rule. The prompt's
        # decision rule fires on the latter: when accessible problems
        # match the request, SELECT from bank; when empty/no match,
        # GENERATE per D14b behavior.
        role_state = await _safe_tool(
            self, ctx, "read_student_role_state",
            {"student_id": str(student_id)} if student_id else {},
        )
        current_role_slug = (
            (role_state.get("current_role") or {}).get("slug")
            if isinstance(role_state, dict)
            else None
        )
        accessible_args: dict[str, Any] = (
            {"student_id": str(student_id)} if student_id else {}
        )
        if current_role_slug:
            accessible_args["role_slug"] = current_role_slug
        accessible_content = await _safe_tool(
            self, ctx, "read_student_accessible_content", accessible_args
        )

        # ── LLM call ──────────────────────────────────────────────
        system_prompt = _load_prompt("practice_curator")
        user_block = _build_user_block(
            student_message=student_message,
            concept_focus=input.concept_focus,
            exercise_type=input.exercise_type,
            difficulty_level=input.difficulty_level,
            target_role=target_role,
            weaknesses=weaknesses,
            progress=progress,
            session_history=session_history,
            role_state=role_state,
            accessible_content=accessible_content,
        )

        # max_tokens=8192 matches D12+D13 v2 calibration. Exercise output
        # with 5 hints + 5 visible + 5 hidden test cases + description
        # is dense; smart-tier default with MiniMax thinking-block headroom.
        llm = build_llm(max_tokens=8192, tier="smart")
        response = await llm.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_block},
            ]
        )
        self._track_llm_usage(ctx, response)
        raw = _extract_text(response)
        output = _parse_output(raw)

        # Defense-in-depth: handoff_request only when student message
        # mentions evaluation. The prompt instructs the LLM to gate on
        # this; this is the runtime backstop.
        if not _student_requested_evaluation(student_message):
            output.handoff_request = None

        # D15 CP4 / D-E backstop — set exercise.source to a non-null
        # value reflecting the bank-vs-generative decision, even when
        # the LLM omits it. Heuristic:
        #   • If accessible_curated_problems had any items AND the LLM's
        #     exercise.title matches one of those titles (case-folded
        #     equality OR substring match in either direction), tag as
        #     "curated" and copy curated_exercise_id from the matched
        #     bank entry.
        #   • Otherwise tag as "generated".
        # When the LLM populated source itself, preserve its value; the
        # backstop only fires when source is None.
        if output.exercise.source is None:
            inferred_source, inferred_id = _infer_exercise_source(
                output.exercise.title, accessible_content
            )
            output.exercise.source = inferred_source
            if inferred_id is not None:
                output.exercise.curated_exercise_id = inferred_id

        payload = output.model_dump(mode="json")
        payload["answer"] = _compose_answer(output)
        return payload


# ── Helpers (CP2 will use these; pinned at signature in CP1) ──────


def _extract_text(response: Any) -> str:
    """Pull the assistant's text out of a LangChain ChatAnthropic response.

    Handles both shapes:
      • Anthropic SDK native — content blocks as objects with `.type` / `.text`
      • MiniMax Anthropic-compatible endpoint — content blocks as dicts

    Skips thinking blocks. Mirrors the D12 + D13 v2 helper byte-for-byte
    to keep the Bug 10a fix consistent across v2 agents.
    """
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type")
                    if btype == "text":
                        return str(block.get("text", ""))
                    continue
                if hasattr(block, "type") and getattr(block, "type", None) == "text":
                    return getattr(block, "text", "")
                if hasattr(block, "text"):
                    return block.text
            return ""
        return str(content)
    return str(response)


def _parse_output(raw: str) -> PracticeCuratorOutput:
    """Extract the first balanced JSON object and validate.

    Canonical D13 server-side composition:
      parsed = json.loads(text)
      stripped = strip_extra_fields(parsed, PracticeCuratorOutput)
      truncated = truncate_to_schema(stripped, PracticeCuratorOutput)
      return PracticeCuratorOutput.model_validate(truncated)

    Per D13 Bug 23: under MiniMax the LLM occasionally flattens nested
    fields to the top level. strip_extra_fields drops those before
    truncate_to_schema runs.
    """
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

    raw_dict = json.loads(text[start : end + 1])
    stripped = strip_extra_fields(raw_dict, PracticeCuratorOutput)
    truncated = truncate_to_schema(stripped, PracticeCuratorOutput)
    return PracticeCuratorOutput.model_validate(truncated)


# ── run() helpers ──────────────────────────────────────────────────


async def _safe_recall(
    agent: Any,
    ctx: AgentContext,
    *,
    query: str,
    mode: str,
    k: int,
) -> list[dict[str, Any]]:
    """Call memory_recall via agent.tool_call. Return list of recalled
    memory dicts; empty on failure. Mirrors D13 mock_interview's helper."""
    args: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "k": k,
        "agent_name": "practice_curator",
    }
    if ctx.user_id is not None:
        args["user_id"] = str(ctx.user_id)
        args["scope"] = "user"
    try:
        result = await agent.tool_call("memory_recall", args, ctx)
        if result.output is None:
            return []
        dumped = result.output.model_dump(mode="json")
        return list(dumped.get("memories", []))
    except Exception as exc:  # noqa: BLE001
        log.debug("practice_curator.recall_skipped", query=query, error=str(exc))
        return []


async def _safe_tool(
    agent: Any, ctx: AgentContext, tool_name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Call a D12-audited DB read tool; return result.output as dict; {}
    on failure. Mirrors D12 career_coach_v2's helper."""
    try:
        result = await agent.tool_call(tool_name, args, ctx)
        if result.output is None:
            return {}
        return result.output.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        log.debug("practice_curator.tool_skipped", tool=tool_name, error=str(exc))
        return {}


def _build_user_block(
    *,
    student_message: str | None,
    concept_focus: str | None,
    exercise_type: str | None,
    difficulty_level: str | None,
    target_role: list[dict[str, Any]],
    weaknesses: list[dict[str, Any]],
    progress: dict[str, Any],
    session_history: dict[str, Any],
    role_state: dict[str, Any],
    accessible_content: dict[str, Any],
) -> str:
    parts: list[str] = []

    constraints: dict[str, Any] = {}
    if concept_focus:
        constraints["concept_focus"] = concept_focus
    if exercise_type:
        constraints["exercise_type"] = exercise_type
    if difficulty_level:
        constraints["difficulty_level"] = difficulty_level
    parts.append(
        f"## Caller-supplied constraints\n\n```json\n{json.dumps(constraints, indent=2)}\n```"
    )

    if student_message:
        parts.append(f"## Student message\n\n{student_message}")

    # D15 CP4 — role identity frames the exercise's scope; accessible
    # curated problems drive the D-E bank-vs-generative decision.
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

    # Target role.
    target_role_text: str | None = None
    if target_role:
        for row in target_role:
            value = row.get("value", {})
            if isinstance(value, dict):
                target_role_text = value.get("target_role") or value.get("role")
                if target_role_text:
                    break
    if target_role_text:
        parts.append(f"## Target role\n\n{target_role_text}")

    # Cross-session weaknesses.
    if weaknesses:
        weakness_topics = [
            row.get("value", {}).get("topic", row.get("key", ""))
            for row in weaknesses
        ]
        weakness_topics = [t for t in weakness_topics if t]
        if weakness_topics:
            parts.append(
                "## Cross-session weaknesses\n\n"
                f"```json\n{json.dumps(weakness_topics, indent=2)}\n```"
            )

    if progress:
        parts.append(
            f"## Recent progress\n\n```json\n{json.dumps(progress, indent=2)}\n```"
        )
    if session_history:
        parts.append(
            "## Recent session history\n\n"
            f"```json\n{json.dumps(session_history, indent=2)}\n```"
        )

    parts.append(
        "## Instructions\n\n"
        "Return a single JSON object matching PracticeCuratorOutput. "
        "No markdown fences, no preamble."
    )
    return "\n\n".join(parts)


# Heuristic gate for handoff_request defense-in-depth. The prompt
# instructs the LLM to set handoff_request only when the student
# explicitly requested evaluation; this runtime check enforces the
# invariant. Pattern matches D13's defense-in-depth approach to D-2.
_EVAL_REQUEST_PATTERNS = (
    "evaluate",
    "evaluation",
    "review my",
    "have it evaluated",
    "have it reviewed",
    "grade",
    "score me",
    "score my",
    "check my answer",
    "check my work",
)


def _student_requested_evaluation(student_message: str | None) -> bool:
    """True iff the student message explicitly asks for evaluation
    after the exercise. Used to gate handoff_request runtime backstop."""
    if not student_message:
        return False
    lowered = student_message.lower()
    return any(pat in lowered for pat in _EVAL_REQUEST_PATTERNS)


def _infer_exercise_source(
    exercise_title: str,
    accessible_content: dict[str, Any],
) -> tuple[str, str | None]:
    """D15 CP4 backstop — infer (source, curated_exercise_id) from
    runtime state when the LLM omitted the source field.

    Returns ("curated", <exercise_id>) when the agent's emitted title
    matches a title in accessible_curated_problems (case-folded equality
    or substring match in either direction). Returns ("generated", None)
    otherwise.

    The matching is permissive (substring) so the LLM doesn't have to
    quote the curated title byte-for-byte — paraphrased or
    role-descriptor-prefixed titles still match. False positives here
    are unlikely because the input space is constrained to the
    student's actual entitled bank for the requested role.
    """
    if not isinstance(accessible_content, dict):
        return "generated", None
    problems = accessible_content.get("accessible_curated_problems") or []
    if not isinstance(problems, list) or not problems:
        return "generated", None
    if not exercise_title:
        return "generated", None
    title_norm = exercise_title.strip().lower()
    for prob in problems:
        if not isinstance(prob, dict):
            continue
        bank_title = (prob.get("title") or "").strip()
        if not bank_title:
            continue
        bank_norm = bank_title.lower()
        if (
            title_norm == bank_norm
            or title_norm in bank_norm
            or bank_norm in title_norm
        ):
            eid = prob.get("exercise_id")
            return "curated", str(eid) if eid is not None else None
    return "generated", None


def _compose_answer(output: PracticeCuratorOutput) -> str:
    """Top-level `answer` projection per the output-text-projection
    convention. Picks the most-relevant short string for chat surface."""
    title = output.exercise.title
    minutes = output.estimated_time_minutes
    diff = output.exercise.difficulty
    return f"{title} ({diff}, ~{minutes} min)"


__all__ = ["PracticeCuratorAgent"]
