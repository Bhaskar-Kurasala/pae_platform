"""D12 / Pass 3c E5 — resume_reviewer agent (canonical AgenticBaseAgent).

Successor to the legacy BaseAgent resume_reviewer.py. The legacy file
stays until CP4 cutover so AGENT_REGISTRY entries remain intact.

Five primitive flags:
  uses_memory       = True   # tracks review history per student
  uses_tools        = True   # 2 read tools: capstones, exercise submissions
  uses_inter_agent  = True   # handoff_targets: portfolio_builder (optional chain)
  uses_self_eval    = False  # deferred
  uses_proactive    = False  # student-initiated only

The key differentiation from the legacy agent: every finding is
cross-referenced against the student's actual submitted work.
Generic advice ("use stronger action verbs") without a specific
evidence citation is explicitly forbidden by the prompt.
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
from app.schemas.agents.resume_reviewer import ResumeReviewerOutput

log = structlog.get_logger().bind(layer="resume_reviewer")


# ── Input schema ───────────────────────────────────────────────────


class ResumeReviewerInput(AgentInput):
    """Per Pass 3c E5 — with Supervisor shape-variability tolerance.

    resume_text is the primary required field. The Supervisor may also
    supply it inside question/task/user_message as a block of text;
    resolved via _resolved_resume_text().
    """

    model_config = ConfigDict(extra="ignore")

    # Primary field per Pass 3c E5 capability declaration.
    resume_text: str | None = Field(default=None, max_length=20_000)
    # Supervisor shape synonyms.
    question: str | None = Field(default=None, max_length=20_000)
    task: str | None = Field(default=None, max_length=20_000)
    user_message: str | None = Field(default=None, max_length=20_000)

    # Optional context.
    target_role: str | None = Field(default=None, max_length=200)
    specific_concerns: list[str] = Field(default_factory=list)

    def resolved_resume_text(self) -> str | None:
        """Pick the first populated text field containing resume content."""
        for field in (
            self.resume_text,
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
            "no inline fallback exists for resume_reviewer."
        )
    return path.read_text()


# ── The agent ──────────────────────────────────────────────────────


class ResumeReviewerAgent(AgenticBaseAgent[ResumeReviewerInput]):
    """Evidence-grounded resume review for AI engineering roles.

    Reads the student's actual capstone and exercise submissions before
    reviewing the resume. Every finding must cite a specific source from
    tool results — generic advice without evidence citations is a
    prompt-enforced failure mode.
    """

    name: ClassVar[str] = "resume_reviewer"
    description: ClassVar[str] = (
        "Reviews student resumes for AI engineering roles by cross-referencing "
        "claims against actual submitted work — capstones and exercise scores. "
        "Produces grounded assessments: unsupported claims, underrepresented "
        "accomplishments, and scored suggestions. Not generic advice."
    )
    input_schema: ClassVar[type[AgentInput]] = ResumeReviewerInput

    # Intended smart-tier model; factory routes to MiniMax-M2.7 when
    # MINIMAX_API_KEY is set. Dynamic resolution in agentic_base.execute()
    # ensures the actual model is captured in agent_actions.
    model_name: ClassVar[str] = "claude-sonnet-4-6"

    # ── Five primitive flags per Pass 3c E5 ───────────────────────
    uses_memory: ClassVar[bool] = True
    uses_tools: ClassVar[bool] = True
    uses_inter_agent: ClassVar[bool] = True
    uses_self_eval: ClassVar[bool] = False
    uses_proactive: ClassVar[bool] = False

    allowed_callers: ClassVar[tuple[str, ...]] = ()
    allowed_callees: ClassVar[tuple[str, ...]] = ("portfolio_builder",)

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
        self, input: ResumeReviewerInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Resume review path:

          1. Resolve resume_text (Supervisor synonym resolution).
          2. Call two read tools (capstones, exercise submissions).
          3. Build the prompt with resume text + evidence.
          4. Invoke LLM, parse ResumeReviewerOutput.
          5. Enforce handoff_request=None (Option B).
          6. Best-effort interaction memory write.
        """
        from app.agents.llm_factory import build_llm

        resume_text = input.resolved_resume_text()
        if resume_text is None:
            fallback = ResumeReviewerOutput(
                overall_score=0,
                headline_assessment=(
                    "No resume text was provided. "
                    "Please paste your resume and I'll review it."
                ),
                strengths=[],
                issues=[],
                unsupported_claims=[],
                underrepresented_accomplishments=[],
                suggested_changes=[],
                handoff_request=None,
            )
            payload = fallback.model_dump(mode="json")
            payload["answer"] = fallback.headline_assessment
            return payload

        # ── Tool calls (D12 CP3 Part H.1: use AgenticBaseAgent.tool_call) ──
        student_id = ctx.user_id

        capstone_data = await _safe_tool(
            self, ctx, "read_capstones",
            {"student_id": str(student_id)} if student_id else {},
        )
        submission_data = await _safe_tool(
            self, ctx, "read_top_exercise_submissions",
            {"student_id": str(student_id), "top_n": 10} if student_id else {},
        )

        # ── LLM call ──────────────────────────────────────────────
        system_prompt = _load_prompt("resume_reviewer")
        user_block = _build_user_block(
            resume_text=resume_text,
            target_role=input.target_role,
            specific_concerns=input.specific_concerns,
            capstones=capstone_data,
            submissions=submission_data,
        )

        # D12 CP3 Phase 4 (Bug 16 sibling): bumped 2048 → 8192. Same
        # rationale as career_coach.
        llm = build_llm(max_tokens=8192, tier="smart")
        response = await llm.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_block},
            ]
        )
        # BUG-CP1F fix (2026-05-09): track LLM usage so
        # _finalize_action_log can compute cost_inr. Without this,
        # agent_actions.cost_inr is 0.0 for every supervisor-
        # orchestrated invocation — invalidates D17b ITEM 1's
        # cost-tracking contract for the /agentic/* path.
        self._track_llm_usage(ctx, response)
        raw = _extract_text(response)
        output = _parse_output(raw)

        # Defense-in-depth: Option B — never ship populated handoff_request.
        output.handoff_request = None

        payload = output.model_dump(mode="json")
        payload["answer"] = _compose_answer(output)

        # Best-effort memory write.
        try:
            await self._record_interaction(
                overall_score=output.overall_score,
                headline=output.headline_assessment,
                ctx=ctx,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "resume_reviewer.memory_write_failed",
                error=str(exc),
                user_id=str(ctx.user_id) if ctx.user_id else None,
            )
            try:
                await ctx.session.rollback()
            except Exception as rollback_exc:  # noqa: BLE001
                log.error(
                    "resume_reviewer.memory_write_rollback_failed",
                    original_error=str(exc),
                    rollback_error=str(rollback_exc),
                    user_id=str(ctx.user_id) if ctx.user_id else None,
                )

        return payload

    async def _record_interaction(
        self,
        *,
        overall_score: int,
        headline: str,
        ctx: AgentContext,
    ) -> None:
        import datetime
        from app.agents.primitives.memory import MemoryStore, MemoryWrite

        store = MemoryStore(session=ctx.session)
        date_str = datetime.date.today().isoformat()
        # valence: score/100 normalised to [-0.5, 0.5] range (50 → 0.0)
        valence = (overall_score - 50) / 100.0
        await store.write(
            MemoryWrite(
                user_id=ctx.user_id,
                scope="user",
                key=f"resume_review:{date_str}",
                value={"overall_score": overall_score, "headline": headline[:300]},
                valence=valence,
            )
        )


# ── Helpers ───────────────────────────────────────────────────────


async def _safe_tool(
    agent: Any, ctx: AgentContext, tool_name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """D12 CP3 Part H.1 fix: route via AgenticBaseAgent.tool_call;
    convert Pydantic output to dict for the prompt builder."""
    try:
        result = await agent.tool_call(tool_name, args, ctx)
        if result.output is None:
            return {}
        return result.output.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        log.debug("resume_reviewer.tool_skipped", tool=tool_name, error=str(exc))
        return {}


def _build_user_block(
    *,
    resume_text: str,
    target_role: str | None,
    specific_concerns: list[str],
    capstones: dict[str, Any],
    submissions: dict[str, Any],
) -> str:
    parts = [f"## Resume to review\n\n{resume_text}"]
    if target_role:
        parts.append(f"## Target role\n\n{target_role}")
    if specific_concerns:
        concerns_str = "\n".join(f"- {c}" for c in specific_concerns)
        parts.append(f"## Specific concerns\n\n{concerns_str}")
    if capstones:
        parts.append(f"## Student capstones (evidence)\n\n```json\n{json.dumps(capstones, indent=2)}\n```")
    if submissions:
        parts.append(f"## Top exercise submissions (evidence)\n\n```json\n{json.dumps(submissions, indent=2)}\n```")
    parts.append(
        "## Instructions\n\n"
        "Return a single JSON object matching ResumeReviewerOutput. "
        "No markdown fences, no preamble. Every finding must cite specific "
        "evidence from the capstones or submissions above."
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


def _parse_output(raw: str) -> ResumeReviewerOutput:
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
    # fix — see parsing_helpers.py. Strip unknown keys then truncate
    # length overshoots; canonical "make LLM output safe" composition.
    raw_dict = json.loads(text[start : end + 1])
    stripped = strip_extra_fields(raw_dict, ResumeReviewerOutput)
    truncated = truncate_to_schema(stripped, ResumeReviewerOutput)
    return ResumeReviewerOutput.model_validate(truncated)


def _compose_answer(output: ResumeReviewerOutput) -> str:
    score = output.overall_score
    headline = output.headline_assessment
    n_issues = len(output.issues or [])
    n_under = len(output.underrepresented_accomplishments or [])
    return (
        f"Resume score: {score}/100. {headline} "
        f"({n_issues} issues, {n_under} underrepresented accomplishments)"
    )
