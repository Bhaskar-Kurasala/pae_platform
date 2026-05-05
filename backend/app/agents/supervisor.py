"""D9 / Pass 3b — Supervisor agent.

Subclass of AgenticBaseAgent. Reads a SupervisorContext, calls Sonnet
with a structured-output contract, returns a RouteDecision.

Per Pass 3b §4.3, the model is Sonnet 4.6 (NOT Haiku). The Supervisor
reads non-trivial context, refuses with nuance, and weighs chain
tradeoffs — Haiku is unreliable on these. Cost is bounded (~5k calls/
day × ~0.40 INR = ~60k INR/month at 1k students); right cost for
orchestration quality.

Per the D9 prompt anti-pattern list:
  - uses_self_eval = False (Checkpoint 1 sign-off Q6: land dark; flip
    after Critic baseline)
  - Builds the agents list dynamically from the capability registry
    at request time (NOT hardcoded)
  - Decline is a first-class output via RouteDecision.action="decline"
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, ClassVar

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr, ValidationError

from app.agents.agentic_base import AgentContext, AgentInput, AgenticBaseAgent
from app.core.config import settings
from app.schemas.supervisor import RouteDecision, SupervisorContext

log = structlog.get_logger().bind(layer="supervisor")


_PROMPT_PATH = Path(__file__).parent / "prompts" / "supervisor.md"


# ── Input schema for the Supervisor ────────────────────────────────


class SupervisorInput(AgentInput):
    """The Supervisor's typed input.

    The orchestrator wraps a SupervisorContext (which is a richer
    aggregate type) and hands the Supervisor this trimmed shape.
    The richer context is reconstructable from `supervisor_context`
    via Pydantic; we keep it as a sub-model so the Supervisor agent
    sees one cleanly-typed object.
    """

    supervisor_context: SupervisorContext


# ── LLM build ──────────────────────────────────────────────────────


def _build_supervisor_llm() -> ChatAnthropic:
    """Sonnet (or MiniMax M2.7) with structured-output knobs.

    Distinct from app.agents.llm_factory.build_llm because we need:
      - Lower temperature (Supervisor is a router, not a creative)
      - Slightly higher max_tokens (RouteDecision JSON can be ~600 toks)
      - Standard 30s timeout (factory default)

    Provider routing mirrors build_llm: MiniMax is checked first so
    AICareerOS runs Supervisor on M2.7 when MINIMAX_API_KEY is set.
    The per-call params (temperature, max_tokens, timeout, retries)
    are preserved across both branches — only the model + key + URL
    differ. See docs/followups/asyncpg-rollback-discipline.md
    "parallel LLM client construction" entry for why this builder
    can't just delegate to build_llm() wholesale.
    """
    if settings.minimax_api_key:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=settings.minimax_model,
            anthropic_api_key=SecretStr(settings.minimax_api_key),
            base_url=settings.minimax_api_base_url,
            temperature=0.1,
            max_tokens=1500,
            timeout=30.0,
            max_retries=2,
        )
    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError(
            "Neither MINIMAX_API_KEY nor ANTHROPIC_API_KEY is set; "
            "Supervisor cannot run"
        )
    return ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",
        anthropic_api_key=SecretStr(api_key),
        temperature=0.1,  # routing is reproducible-ish; tiny variance for tie-breaks
        max_tokens=1500,  # RouteDecision JSON + reasoning fits comfortably
        timeout=30.0,
        max_retries=2,
    )


# ── The Supervisor agent ───────────────────────────────────────────


class Supervisor(AgenticBaseAgent[SupervisorInput]):
    """The Supervisor.

    AgenticBaseAgent subclass with safety wrapping happening
    automatically via the base class's execute() (see Checkpoint 3
    integration in agentic_base.py).
    """

    name: ClassVar[str] = "supervisor"
    description: ClassVar[str] = (
        "AICareerOS routing orchestrator. Decides which specialist "
        "agent or agents handle each student request. Replaces the "
        "legacy MOA."
    )
    input_schema: ClassVar[type[AgentInput]] = SupervisorInput

    # Opt-outs per Checkpoint 1 sign-off:
    # - uses_memory: False (Supervisor reads SupervisorContext.recent_agent_actions
    #   for awareness; no need for direct memory bank access in v1)
    # - uses_tools: False (read-only tools deferred to v2 per Pass 3b §8.4)
    # - uses_inter_agent: False (the Supervisor RETURNS a decision; the
    #   dispatch layer invokes specialists, not the Supervisor itself.
    #   Per Pass 3b §5: "The Supervisor decides; the dispatch layer
    #   executes. Separation matters.")
    # - uses_self_eval: False (land dark; Critic samples Supervisor
    #   decisions in production for baseline before flipping per Pass
    #   3b §10.3)
    # - uses_proactive: False (chat-only entry point; cron/webhook
    #   work happens through individual specialists)
    uses_memory: ClassVar[bool] = False
    uses_tools: ClassVar[bool] = False
    uses_inter_agent: ClassVar[bool] = False
    uses_self_eval: ClassVar[bool] = False
    uses_proactive: ClassVar[bool] = False

    # ── prompt loading (cached at instance level, not class level, so
    # tests that swap prompt files don't bleed across runs) ────────

    _prompt_cache: str | None = None

    def _load_prompt(self) -> str:
        if self._prompt_cache is None:
            self._prompt_cache = _PROMPT_PATH.read_text(encoding="utf-8")
        return self._prompt_cache

    # ── LLM hook for tests ─────────────────────────────────────────

    _llm_override: ChatAnthropic | None = None

    def _get_llm(self) -> ChatAnthropic:
        """Return the LLM client, lazily built on first use.

        Tests override `_llm_override` to inject a stubbed client
        without touching the real factory or paying API cost.
        """
        if self._llm_override is not None:
            return self._llm_override
        return _build_supervisor_llm()

    # ── core method: produce a RouteDecision ───────────────────────

    async def run(
        self, input: SupervisorInput, ctx: AgentContext  # noqa: ARG002 — ctx unused for Supervisor (no DB writes itself)
    ) -> dict[str, Any]:
        """Run the Supervisor and return a RouteDecision dict.

        Output is always a dict (not a RouteDecision instance) because
        AgenticBaseAgent.execute() wraps it in AgentResult.output —
        the dispatch layer that consumes us re-validates as
        RouteDecision so we don't double-validate here.
        """
        sup_ctx = input.supervisor_context
        prompt_template = self._load_prompt()

        # Render the agents list inline in the user message — keeps the
        # system prompt static (cacheable) and the per-request data
        # in a single user-side block.
        agents_block = _render_agents_block(sup_ctx)
        snapshot_block = _render_snapshot_block(sup_ctx)
        recent_block = _render_recent_actions_block(sup_ctx)
        thread_block = _render_thread_block(sup_ctx)

        user_message = (
            f"## Available agents\n{agents_block}\n\n"
            f"## Student snapshot\n{snapshot_block}\n\n"
            f"## Recent agent actions\n{recent_block}\n\n"
            f"## Recent conversation\n{thread_block}\n\n"
            f"## Cost budget remaining today (INR)\n"
            f"{sup_ctx.cost_budget_remaining_today_inr}\n\n"
            f"## Student message\n{sup_ctx.user_message}\n"
        )

        llm = self._get_llm()
        response = await llm.ainvoke(
            [
                SystemMessage(content=prompt_template),
                HumanMessage(content=user_message),
            ]
        )
        raw_text = _extract_text_from_response(response)

        decision = _parse_route_decision(raw_text)
        if decision is None:
            # Pass 3b §7.1 Failure Class A: malformed JSON.
            # Surface a fallback decision so the dispatch layer has
            # something to work with. The orchestrator may also choose
            # to log a Critic-style escalation.
            log.warning(
                "supervisor.malformed_response",
                request_id=str(sup_ctx.request_id),
                raw_preview=raw_text[:200] if raw_text else None,
            )
            decision = _build_keyword_fallback_decision(sup_ctx)

        return decision.model_dump()


# ── Prompt-rendering helpers ───────────────────────────────────────


def _render_agents_block(ctx: SupervisorContext) -> str:
    """Render available_agents as a compact bulleted list."""
    if not ctx.available_agents:
        return "(none — student is unentitled)"
    lines: list[str] = []
    for cap in ctx.available_agents:
        handoffs = (
            ", ".join(cap.handoff_targets) if cap.handoff_targets else "—"
        )
        lines.append(
            f"- **{cap.name}** ({cap.minimum_tier}, ~{cap.typical_cost_inr} INR, "
            f"~{cap.typical_latency_ms}ms): {cap.description} "
            f"Inputs: {cap.inputs_required or '—'}. Handoffs: {handoffs}."
        )
    return "\n".join(lines)


def _render_snapshot_block(ctx: SupervisorContext) -> str:
    """Compact projection of the StudentSnapshot for the prompt."""
    snap = ctx.student_snapshot
    parts: list[str] = []
    if snap.active_courses:
        parts.append(
            "Active courses: "
            + ", ".join(c.slug for c in snap.active_courses)
        )
    if snap.progress_summary:
        parts.append(
            f"Progress: {snap.progress_summary.weeks_active}wk active, "
            f"last session {snap.progress_summary.last_session_at}"
        )
    if snap.risk_state:
        parts.append(f"Risk state: {snap.risk_state}")
    if snap.active_goal_contract and snap.active_goal_contract.target_role:
        parts.append(f"Target role: {snap.active_goal_contract.target_role}")
    if snap.weak_concepts:
        parts.append(
            "Weak concepts: "
            + ", ".join(c.slug for c in snap.weak_concepts[:3])
        )
    if not parts:
        return "(new student — no prior activity)"
    return "\n".join(f"- {p}" for p in parts)


def _render_recent_actions_block(ctx: SupervisorContext) -> str:
    """Compact summary of recent agent actions."""
    if not ctx.recent_agent_actions:
        return "(none in window)"
    lines: list[str] = []
    for action in ctx.recent_agent_actions[:5]:  # cap at 5 for prompt budget
        lines.append(
            f"- {action.agent_name} ({action.action_type}, "
            f"{action.occurred_at:%Y-%m-%d %H:%M}): {action.summary}"
        )
    return "\n".join(lines)


def _render_thread_block(ctx: SupervisorContext) -> str:
    """Recent conversation turns, condensed."""
    if not ctx.recent_turns:
        return "(no prior turns)"
    lines: list[str] = []
    for turn in ctx.recent_turns[-5:]:  # last 5
        speaker = turn.role
        if turn.role == "assistant" and turn.agent_name:
            speaker = f"{turn.role}[{turn.agent_name}]"
        # Truncate per-turn for prompt budget
        content = turn.content[:300]
        lines.append(f"- **{speaker}**: {content}")
    return "\n".join(lines)


# ── LLM-response parsing ───────────────────────────────────────────


def _extract_text_from_response(response: Any) -> str:
    """Pull text out of a LangChain ChatAnthropic response.

    Per the LLM-response-parsing memory: flatten list-of-dict content,
    skip thinking blocks, extract the assistant text.
    """
    if response is None:
        return ""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                # Skip thinking blocks (Anthropic extended thinking).
                if block.get("type") == "thinking":
                    continue
                if "text" in block and isinstance(block["text"], str):
                    parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _parse_route_decision(raw: str) -> RouteDecision | None:
    """Extract the first balanced JSON object from raw, validate as RouteDecision.

    Same robust parsing pattern as the safety LLM classifier:
    Sonnet sometimes adds prose despite the "no prose" instruction;
    we extract the first balanced { … } block and parse.
    """
    if not raw:
        return None
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    end = -1
    for i in range(start, len(raw)):
        c = raw[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    candidate = raw[start:end]
    try:
        parsed = json.loads(candidate)
        return RouteDecision.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as exc:
        log.debug(
            "supervisor.route_decision_parse_failed",
            error=str(exc),
            candidate_preview=candidate[:200],
        )
        return None


# ── Keyword-fallback when Supervisor LLM fails ─────────────────────


# Pass 3b §7.1 Failure Class A: when the Supervisor returns malformed
# JSON twice, fall back to deterministic keyword routing. ~80% of
# common requests get adequate routing this way; the rest go to
# learning_coach as the safest default.
_KEYWORD_ROUTES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(review|debug|fix)\s+(my\s+)?code\b"), "senior_engineer"),
    (re.compile(r"(?i)\b(mock\s+interview|interview\s+practice|interview\s+prep)\b"), "mock_interview"),
    (re.compile(r"(?i)\b(career|switch\s+(to\s+)?(genai|llm|ai))\b"), "career_coach"),
    (re.compile(r"(?i)\b(resume|cv)\b"), "resume_reviewer"),
    (re.compile(r"(?i)\b(billing|refund|subscription|invoice)\b"), "billing_support"),
    (re.compile(r"(?i)\b(quiz|mcq|multiple\s+choice)\b"), "mcq_factory"),
    (re.compile(r"(?i)\b(progress|weekly\s+report|how\s+am\s+i\s+doing)\b"), "progress_report"),
    (re.compile(r"(?i)\b(portfolio|github\s+readme)\b"), "portfolio_builder"),
    (re.compile(r"(?i)\b(capstone|project\s+evaluat)\b"), "project_evaluator"),
]


def _build_keyword_fallback_decision(ctx: SupervisorContext) -> RouteDecision:
    """Deterministic fallback when the Supervisor LLM fails.

    Pass 3b §7.1 Failure Class A: keep the user's request alive even
    when the Supervisor itself is misbehaving. Falls through to
    learning_coach as the safest default.
    """
    available_names = {cap.name for cap in ctx.available_agents}
    chosen = "learning_coach"
    for pattern, agent in _KEYWORD_ROUTES:
        if pattern.search(ctx.user_message) and agent in available_names:
            chosen = agent
            break
    # If even the fallback isn't in available_agents (e.g. free tier),
    # decline gracefully.
    if chosen not in available_names:
        return RouteDecision(
            action="decline",
            decline_reason="entitlement_required",
            decline_message=(
                "Your subscription doesn't include this feature. "
                "Browse available courses to unlock more agents."
            ),
            suggested_next_action="browse_catalog",
            reasoning="Keyword fallback selected an agent not in the user's tier; declining.",
            confidence="low",
            primary_intent="clarification_needed",
        )
    return RouteDecision(
        action="dispatch_single",
        target_agent=chosen,
        constructed_context={"user_message": ctx.user_message},
        reasoning=(
            "Supervisor LLM produced malformed output; using keyword "
            f"fallback routing to {chosen}."
        ),
        confidence="low",
        primary_intent="clarification_needed",
    )


__all__ = ["Supervisor", "SupervisorInput"]
