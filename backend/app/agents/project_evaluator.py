"""D14c / Pass 3c E9 — project_evaluator agent (AgenticBaseAgent).

D14c CP4 cutover: file is the canonical project_evaluator. Legacy
BaseAgent file deleted; agent class registers via _agentic_loader,
NOT via the legacy @register / AGENT_REGISTRY path. Mirrors the
D11 senior_engineer / D13 mock_interview cutover pattern.

D14c CP1 established the schema + capability + stub; CP2 wired the
prompt + 4 tool calls + dual-rail refusal logic; CP3 verified live
under MiniMax across 4 phases (rubric-grounded × 2, D-E refusal,
D-4 refusal — all clean, zero invented dimensions, zero
strip_extra_fields drops).

Single-shot per D-A: each call evaluates ONE capstone submission. No
session_id, no multi-turn state. The orchestration loop (student
submits → evaluator evaluates → portfolio_builder creates entry) lives
at the orchestration layer above the agent — handoff_targets is
informational metadata only.

Five primitive flags (per D-A, D-B, D-C locked decisions):
  uses_memory       = True   # student trajectory recall + cross-session
                             # capstone history lookup
  uses_tools        = True   # 4 DB reads (submission content, rubric,
                             # student progress, capstone status)
  uses_inter_agent  = False  # handoff_targets is informational metadata;
                             # orchestration layer dispatches D17
                             # portfolio_builder, not evaluator itself
  uses_self_eval    = False  # D-C: no Critic loop. Critic measures
                             # structural quality; evaluation domain
                             # quality (correct rubric application)
                             # needs a meta-evaluator (architectural
                             # future work; not D14c scope)
  uses_proactive    = False  # student-initiated only

Per D-E rubric-grounding (load-bearing for D14c): triple-layered
defense — (1) prompt enforces "ground every dimension score in
rubric_text from user_block, refuse evaluation if rubric_text is
empty"; (2) runtime in run() populates RUBRIC_UNAVAILABLE marker if
read_rubric_for_capstone returns empty; (3) schema-level
rubric_available bool flag explicitly indicates whether evaluation
was rubric-grounded.

Per D-4 dual-rail: NON_CAPSTONE_SUBMISSION refusal symmetric with
D-E. If read_capstone_submission_content returns is_capstone=False,
agent skips remaining DB reads (early-exit) and dispatches LLM with
refusal prompt. Mirrors D13.5 fail-loud pattern at the agent run()
boundary instead of chain construction.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, ClassVar

import structlog

from app.agents.agentic_base import AgentContext, AgentInput, AgenticBaseAgent
from app.agents.parsing_helpers import strip_extra_fields, truncate_to_schema
from app.schemas.agents.project_evaluator import (
    PortfolioEntryDraft,
    ProjectEvaluatorInput,
    ProjectEvaluatorOutput,
    TransitionGateStatus,
)

log = structlog.get_logger().bind(layer="project_evaluator")


# ── Refusal markers (D-E + D-4 dual-rail) ──────────────────────────

RUBRIC_UNAVAILABLE_MARKER = "RUBRIC_UNAVAILABLE"
NON_CAPSTONE_SUBMISSION_MARKER = "NON_CAPSTONE_SUBMISSION"


# ── Prompt loader ──────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load project_evaluator's prompt. CP1 stub returns a placeholder
    until the canonical prompt with rubric-grounding D-E section + D-4
    dual-rail refusal section lands at CP2.

    D14c CP4 cutover: file landed at canonical `project_evaluator.md`
    after the legacy BaseAgent prompt was deleted at the same commit.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        return (
            "# Project Evaluator (CP1 stub)\n\n"
            "This prompt is a placeholder. The canonical prompt with "
            "the D-E rubric-grounding enforcement section and D-4 "
            "dual-rail graceful refusal section lands in D14c CP2."
        )
    return path.read_text()


# ── The agent ──────────────────────────────────────────────────────


class ProjectEvaluatorAgent(AgenticBaseAgent[ProjectEvaluatorInput]):
    """Evaluates one capstone submission per call against the published
    rubric.

    Per D-A: single-shot. Per D-B: no sandbox dependency in initial
    scope (code-execution-based verification deferred). Per D-C: no
    Critic loop, no mandatory validation chain.

    CP1 stub: instantiation, capability flags, and run() contract
    skeleton emitting a minimal valid output. Tool calls + dual-rail
    refusal routing + prompt-driven LLM call land in CP2.
    """

    name: ClassVar[str] = "project_evaluator"
    description: ClassVar[str] = (
        "Evaluates capstone projects against the published rubric — "
        "architecture, completeness, evidence of learning, demo "
        "quality. Reads the actual rubric from exercises.rubric and "
        "grades strictly to it. Output is a structured evaluation + "
        "portfolio entry draft for D17 portfolio_builder."
    )
    input_schema: ClassVar[type[AgentInput]] = ProjectEvaluatorInput

    # Intended smart-tier model; factory routes to MiniMax-M2.7 when
    # MINIMAX_API_KEY is set. Dynamic resolution captured in agent_actions.
    model_name: ClassVar[str] = "claude-sonnet-4-6"

    # ── Five primitive flags per D-A, D-B, D-C ────────────────────
    uses_memory: ClassVar[bool] = True
    uses_tools: ClassVar[bool] = True
    # D-A: orchestration layer owns the handoff to portfolio_builder
    # (D17 work). The agent itself does not dispatch other agents.
    uses_inter_agent: ClassVar[bool] = False
    # D-C: no Critic loop. Critic measures structural quality; what
    # we'd want is rubric-application correctness (a meta-evaluator),
    # which doesn't exist. Architectural future work.
    uses_self_eval: ClassVar[bool] = False
    uses_proactive: ClassVar[bool] = False

    allowed_callers: ClassVar[tuple[str, ...]] = ()
    # uses_inter_agent=False so the agent never dispatches other agents.
    # handoff_targets in capability is informational metadata for the
    # orchestration layer.
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
        self, input: ProjectEvaluatorInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Project evaluator turn handler.

        Single-shot path per D-A:
          1. read_capstone_submission_content(project_submission_id)
             → submission row + is_capstone flag.
          2. EARLY EXIT (D-4) if found=False or is_capstone=False:
             skip remaining reads, dispatch LLM with
             NON_CAPSTONE_SUBMISSION marker → refusal output
             (rubric_available=False, dimension_scores=[],
             conservative draft, handoff_request to senior_engineer).
          3. read_rubric_for_capstone(exercise_id from submission)
             → rubric_text or None. None → RUBRIC_UNAVAILABLE marker
             in user_block (D-E).
          4. read_student_full_progress(student_id) — D12-audited.
          5. read_capstone_status(student_id) — D12-audited; prior
             capstone trajectory for context.
          6. Compose user_block; LLM call; extract text via dict-aware
             _extract_text; strip_extra_fields + truncate_to_schema;
             validate ProjectEvaluatorOutput.
          7. Defense-in-depth: if rubric_text was None at step 3,
             force rubric_available=False and dimension_scores=[] on
             the parsed output (runtime backstop for D-E).
          8. Compose answer projection.
        """
        from app.agents.llm_factory import build_llm

        student_message = input.resolved_message()
        submission_id = input.project_submission_id

        # ── Step 1: read submission ──────────────────────────────
        submission = await _safe_tool(
            self,
            ctx,
            "read_capstone_submission_content",
            {"submission_id": str(submission_id)},
        )

        # ── Step 2: D-4 early exit ───────────────────────────────
        is_capstone = bool(submission.get("is_capstone")) if submission else False
        found = bool(submission.get("found")) if submission else False
        if not found or not is_capstone:
            return await self._evaluate_refusal_path(
                ctx,
                submission_id=submission_id,
                marker=NON_CAPSTONE_SUBMISSION_MARKER,
                submission=submission,
                rubric_text=None,
                progress=None,
                prior_capstone=None,
                student_message=student_message,
                specific_concerns=input.specific_concerns,
            )

        # ── Step 3: read rubric ──────────────────────────────────
        exercise_id = submission.get("exercise_id")
        rubric = (
            await _safe_tool(
                self,
                ctx,
                "read_rubric_for_capstone",
                {"exercise_id": exercise_id},
            )
            if exercise_id
            else {}
        )
        rubric_text: str | None = rubric.get("rubric_text") if rubric else None

        # ── Steps 4 + 5: D12-audited DB reads ────────────────────
        student_id = submission.get("student_id")
        progress = (
            await _safe_tool(
                self,
                ctx,
                "read_student_full_progress",
                {"student_id": student_id} if student_id else {},
            )
            if student_id
            else {}
        )
        prior_capstone = (
            await _safe_tool(
                self,
                ctx,
                "read_capstone_status",
                {"student_id": student_id} if student_id else {},
            )
            if student_id
            else {}
        )

        # ── D15 CP4 / D-G — role state + transition gate ─────────
        # Fetched via the submission's student_id (NOT ctx.user_id, which
        # is the caller — for instructor-driven evaluations the student
        # being evaluated is identified by the submission row). Skip
        # the transition gate read when the student is at the terminal
        # role; transition_gate_status stays None in that case.
        role_state = (
            await _safe_tool(
                self,
                ctx,
                "read_student_role_state",
                {"student_id": student_id} if student_id else {},
            )
            if student_id
            else {}
        )
        gate_def: dict[str, Any] = {}
        next_role_slug: str | None = None
        current_role_slug: str | None = None
        if isinstance(role_state, dict) and role_state.get("found"):
            current = role_state.get("current_role") or {}
            current_role_slug = current.get("slug") if isinstance(current, dict) else None
            nt = role_state.get("next_transition")
            if isinstance(nt, dict):
                next_role_slug = nt.get("target_role_slug")
        if current_role_slug and next_role_slug:
            gate_def = await _safe_tool(
                self,
                ctx,
                "read_role_transition_gate",
                {
                    "from_role_slug": current_role_slug,
                    "to_role_slug": next_role_slug,
                },
            )

        # ── Step 6: LLM call ─────────────────────────────────────
        marker = (
            RUBRIC_UNAVAILABLE_MARKER
            if rubric_text is None
            else None
        )
        system_prompt = _load_prompt("project_evaluator")
        user_block = _build_user_block(
            submission_id=submission_id,
            specific_concerns=input.specific_concerns,
            student_message=student_message,
            submission=submission,
            rubric_text=rubric_text,
            rubric_marker=marker,
            capstone_marker=None,  # gate passed
            progress=progress,
            prior_capstone=prior_capstone,
            role_state=role_state,
            gate_def=gate_def,
        )

        # max_tokens=8192 — output is a multi-paragraph narrative +
        # nested DimensionScore list + PortfolioEntryDraft + 5000-char
        # narrative cap. D14b smart-tier baseline; flag at CP3 if
        # truncation surfaces.
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

        # ── Step 7: defense-in-depth D-E backstop ────────────────
        # If the rubric was unavailable, force the refusal-shape
        # invariants regardless of what the LLM produced. The prompt
        # instructs this; this is the runtime backstop matching D14b's
        # handoff-gate defense-in-depth pattern.
        if rubric_text is None:
            output.rubric_available = False
            output.dimension_scores = []
            output.handoff_request = None  # D-E refusal does not handoff

        # Symmetric defense for the "rubric was present but the LLM
        # left dimension_scores empty AND claimed rubric_available=True"
        # contradiction — load the canonical hard-stop signal.
        if output.rubric_available and not output.dimension_scores:
            output.rubric_available = False

        # ── D15 CP4 / D-G runtime backstop ───────────────────────
        # transition_gate_status is None unless ALL of:
        #   • This is the rubric-grounded path (rubric_available=True).
        #   • Student state is reachable AND non-terminal.
        #   • read_role_transition_gate returned found=True for the
        #     current → next pair.
        # When populated, force consistency: capstone_score_achieved
        # MUST equal overall_score; passes_threshold MUST equal
        # (overall_score >= capstone_threshold_required); the message
        # is regenerated to canonical shape if the LLM drifted.
        output.transition_gate_status = _enforce_gate_status(
            output=output,
            role_state=role_state,
            gate_def=gate_def,
        )

        # ── Step 8: answer projection ────────────────────────────
        payload = output.model_dump(mode="json")
        payload["answer"] = _compose_answer(output)
        return payload

    async def _evaluate_refusal_path(
        self,
        ctx: AgentContext,
        *,
        submission_id: uuid.UUID,
        marker: str,
        submission: dict[str, Any],
        rubric_text: str | None,
        progress: dict[str, Any] | None,
        prior_capstone: dict[str, Any] | None,
        student_message: str | None,
        specific_concerns: list[str],
    ) -> dict[str, Any]:
        """D-4 / D-E refusal path: dispatch LLM with refusal marker
        in user_block. The prompt's hard constraints map markers to
        structured-refusal output shape. We still call the LLM (rather
        than constructing the refusal output directly in Python) so
        that the agent's audit trail and cost accounting reflect a
        real round-trip; the prompt does the work of producing the
        canonical refusal shape.

        Runtime backstop after the call: even if the LLM ignored the
        marker, force the load-bearing invariants
        (rubric_available=False, dimension_scores=[]) so the
        contractual refusal shape is preserved.
        """
        from app.agents.llm_factory import build_llm

        system_prompt = _load_prompt("project_evaluator")
        user_block = _build_user_block(
            submission_id=submission_id,
            specific_concerns=specific_concerns,
            student_message=student_message,
            submission=submission,
            rubric_text=rubric_text,
            rubric_marker=(
                RUBRIC_UNAVAILABLE_MARKER
                if marker == RUBRIC_UNAVAILABLE_MARKER
                else None
            ),
            capstone_marker=(
                NON_CAPSTONE_SUBMISSION_MARKER
                if marker == NON_CAPSTONE_SUBMISSION_MARKER
                else None
            ),
            progress=progress or {},
            prior_capstone=prior_capstone or {},
            # D15 CP4: refusal paths have no gate context — pass empty
            # dicts so the user_block omits those sections cleanly.
            role_state={},
            gate_def={},
        )

        llm = build_llm(max_tokens=2048, tier="smart")
        response = await llm.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_block},
            ]
        )
        self._track_llm_usage(ctx, response)
        raw = _extract_text(response)
        output = _parse_output(raw)

        # Runtime backstop — load-bearing refusal invariants.
        output.rubric_available = False
        output.dimension_scores = []

        # D-E refusal: handoff_request must be null.
        # D-4 refusal: handoff_request to senior_engineer is allowed
        # and expected; we leave whatever the LLM produced (which the
        # prompt instructs to populate).
        if marker == RUBRIC_UNAVAILABLE_MARKER:
            output.handoff_request = None

        # D15 CP4 / D-G: refusal paths NEVER carry transition_gate_status.
        output.transition_gate_status = None

        payload = output.model_dump(mode="json")
        payload["answer"] = _compose_answer(output)
        return payload


# ── Helpers (CP2 will use these; pinned at signature in CP1) ──────


def _extract_text(response: Any) -> str:
    """Pull the assistant's text out of a LangChain ChatAnthropic response.

    Handles both shapes:
      • Anthropic SDK native — content blocks as objects with `.type` / `.text`
      • MiniMax Anthropic-compatible endpoint — content blocks as dicts

    Skips thinking blocks. Mirrors the D12 + D13 + D14b helper byte-for-byte
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


def _parse_output(raw: str) -> ProjectEvaluatorOutput:
    """Extract the first balanced JSON object and validate.

    Canonical D13 server-side composition:
      parsed = json.loads(text)
      stripped = strip_extra_fields(parsed, ProjectEvaluatorOutput)
      truncated = truncate_to_schema(stripped, ProjectEvaluatorOutput)
      return ProjectEvaluatorOutput.model_validate(truncated)

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
    stripped = strip_extra_fields(raw_dict, ProjectEvaluatorOutput)
    truncated = truncate_to_schema(stripped, ProjectEvaluatorOutput)
    return ProjectEvaluatorOutput.model_validate(truncated)


async def _safe_tool(
    agent: Any,
    ctx: AgentContext,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Call a registered tool via agent.tool_call; return result.output
    as dict; {} on failure. Mirrors D12 career_coach_v2 / D14b
    practice_curator helper. Failures are logged at debug — the agent's
    run() routes on the empty-dict shape rather than raising."""
    try:
        result = await agent.tool_call(tool_name, args, ctx)
        if result.output is None:
            return {}
        return result.output.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        log.debug(
            "project_evaluator.tool_skipped",
            tool=tool_name,
            error=str(exc),
        )
        return {}


def _build_user_block(
    *,
    submission_id: uuid.UUID,
    specific_concerns: list[str],
    student_message: str | None,
    submission: dict[str, Any],
    rubric_text: str | None,
    rubric_marker: str | None,
    capstone_marker: str | None,
    progress: dict[str, Any],
    prior_capstone: dict[str, Any],
    role_state: dict[str, Any],
    gate_def: dict[str, Any],
) -> str:
    """Compose the user_block the prompt consumes.

    Structure mirrors the prompt's `## ` section names exactly so the
    LLM's pattern-matching on section headers is reliable. Refusal
    markers (D-E rubric_marker, D-4 capstone_marker) appear as literal
    strings in their respective sections — the prompt's hard
    constraints recognize these by exact match.
    """
    parts: list[str] = []

    # ── Caller-supplied (always present) ─────────────────────────
    caller_block: dict[str, Any] = {
        "project_submission_id": str(submission_id),
    }
    if specific_concerns:
        caller_block["specific_concerns"] = specific_concerns
    parts.append(
        "## Caller-supplied\n\n"
        f"```json\n{json.dumps(caller_block, indent=2)}\n```"
    )

    # ── Student message ──────────────────────────────────────────
    if student_message:
        parts.append(f"## Student message\n\n{student_message}")

    # ── Capstone gate (D-4) ──────────────────────────────────────
    # ALWAYS present so the prompt has a deterministic place to look.
    if capstone_marker == NON_CAPSTONE_SUBMISSION_MARKER:
        parts.append(
            f"## Capstone gate\n\n{NON_CAPSTONE_SUBMISSION_MARKER}"
        )
    else:
        parts.append("## Capstone gate\n\nis_capstone=True")

    # ── Submission ───────────────────────────────────────────────
    if submission:
        parts.append(
            "## Submission\n\n"
            f"```json\n{json.dumps(submission, indent=2, default=str)}\n```"
        )

    # ── Rubric (D-E) ─────────────────────────────────────────────
    if rubric_marker == RUBRIC_UNAVAILABLE_MARKER:
        parts.append(f"## Rubric\n\n{RUBRIC_UNAVAILABLE_MARKER}")
    elif rubric_text:
        parts.append(f"## Rubric\n\n```json\n{rubric_text}\n```")

    # ── Recent progress ──────────────────────────────────────────
    if progress:
        parts.append(
            "## Recent progress\n\n"
            f"```json\n{json.dumps(progress, indent=2, default=str)}\n```"
        )

    # ── Prior capstone status ────────────────────────────────────
    if prior_capstone:
        parts.append(
            "## Prior capstone status\n\n"
            f"```json\n{json.dumps(prior_capstone, indent=2, default=str)}\n```"
        )

    # ── D15 CP4 / D-G: gate context (rubric-grounded path only) ──
    if role_state and role_state.get("found"):
        parts.append(
            "## Student role state\n\n"
            f"```json\n{json.dumps(role_state, indent=2, default=str)}\n```"
        )
    if gate_def and gate_def.get("found"):
        parts.append(
            "## Transition gate (current → next adjacent role)\n\n"
            f"```json\n{json.dumps(gate_def, indent=2, default=str)}\n```"
        )

    # ── Closing instruction ──────────────────────────────────────
    parts.append(
        "## Instructions\n\n"
        "Return a single JSON object matching ProjectEvaluatorOutput. "
        "No markdown fences, no preamble."
    )
    return "\n\n".join(parts)


# ── D15 CP4 / D-G runtime backstop ─────────────────────────────────


def _enforce_gate_status(
    *,
    output: ProjectEvaluatorOutput,
    role_state: dict[str, Any],
    gate_def: dict[str, Any],
) -> TransitionGateStatus | None:
    """Compute the canonical transition_gate_status from authoritative
    runtime data, ignoring whatever the LLM emitted.

    Returns None when:
      • Refusal path (rubric_available=False on output).
      • Student role state unreachable / not found.
      • Student at terminal role (no next_transition).
      • Gate definition unreachable / not found.

    Returns a populated TransitionGateStatus when all three sources
    align. The shape is reproducible given the same inputs, so
    consistency is enforced by replacing the LLM's value rather than
    asserting/raising on drift.
    """
    if not output.rubric_available:
        return None
    if not isinstance(role_state, dict) or not role_state.get("found"):
        return None
    current = role_state.get("current_role") or {}
    if not isinstance(current, dict):
        return None
    if current.get("is_terminal"):
        return None
    nt = role_state.get("next_transition") or {}
    if not isinstance(nt, dict):
        return None
    target_to_role = nt.get("target_role_slug")
    current_slug = current.get("slug")
    if not target_to_role or not current_slug:
        return None
    if not isinstance(gate_def, dict) or not gate_def.get("found"):
        return None

    threshold = float(gate_def.get("capstone_threshold", 0.0))
    score = float(output.overall_score)
    passed = score >= threshold
    msg = (
        f"this evaluation {'passes' if passed else 'does not pass'} "
        f"the gate threshold for {current_slug}→{target_to_role}; "
        f"achieved {score:.2f} vs required {threshold:.2f}"
    )
    return TransitionGateStatus(
        transition_from_role=current_slug,
        transition_to_role=target_to_role,
        capstone_threshold_required=threshold,
        capstone_score_achieved=score,
        passes_threshold=passed,
        gate_message=msg,
    )


def _compose_answer(output: ProjectEvaluatorOutput) -> str:
    """Top-level `answer` projection per the output-text-projection
    convention. Picks the most-relevant short string for chat surface.

    For the refusal paths the title already carries the disclaimer
    (e.g., 'Evaluation Pending — Rubric Unavailable'), so the projection
    surfaces it cleanly without ceremony.
    """
    title = output.portfolio_entry_draft.title
    score_pct = int(round(output.overall_score * 100))
    if not output.rubric_available:
        return title
    return f"{title} — {score_pct}/100"


__all__ = ["ProjectEvaluatorAgent"]
