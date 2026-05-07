"""D13 / Pass 3c E7 — mock_interview agent (canonical AgenticBaseAgent).

D13 Checkpoint 4 cutover: this file replaced the legacy BaseAgent
mock_interview.py. The legacy file's @register-decorated class was
removed; this module now owns the canonical name. AgenticBaseAgent
registers via _agentic_registry; legacy AGENT_REGISTRY no longer
carries the agent (retirement pin in tests/test_agents/test_ws4_agents.py).

Five primitive flags:
  uses_memory       = True   # session memory + cross-session weakness tracking
  uses_tools        = True   # memory_recall, memory_write (universal)
  uses_inter_agent  = True   # handoff_targets to senior_engineer + career_coach
  uses_self_eval    = True   # exception to default — interview quality matters
                             # (per Pass 3c E7 spec). First v2 agent to flip this.
  uses_proactive    = False  # student-initiated only.

Multi-turn shape (D-1 architectural decision):
  • session_id is the binding key, lives in MockInterviewInput. Client
    passes it on follow-up turns; agent generates UUID on first turn.
  • Memory keys: mock_interview:session:{session_id} (within-session
    turn log), mock_interview:weakness:{topic} (cross-session weakness
    tracking).

Handoff shape (D-2 architectural decision):
  • Option B: handoff_request is populated ONLY on
    turn_kind="session_summary" turns. Mid-session state-preserving
    handoff is deferred. Defense-in-depth: run() forces None on every
    other turn_kind even if the LLM emitted one.
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
from app.schemas.agents.mock_interview import (
    MockInterviewInput,
    MockInterviewOutput,
)

log = structlog.get_logger().bind(layer="mock_interview")


# ── Prompt loader ──────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file missing: {path}. The prompt is required; "
            "no inline fallback exists for mock_interview."
        )
    return path.read_text()


# ── The agent ──────────────────────────────────────────────────────


class MockInterviewAgent(AgenticBaseAgent[MockInterviewInput]):
    """Mock interviews across four formats, stateful across turns via session_id.

    Per D-1: session_id lives in input/output, not in orchestrator state.
    Per D-2: handoff_request is Option B (session_summary turns only).
    Per D-3: mandatory-chain Supervisor work is out of scope for D13.
    """

    name: ClassVar[str] = "mock_interview"
    description: ClassVar[str] = (
        "Conducts mock interviews across system_design, coding, "
        "behavioral, and take_home formats. Maintains session state via "
        "session_id across multiple turns. Tracks weaknesses in memory "
        "for cross-session calibration. Suggests senior_engineer or "
        "career_coach at session close per Option B handoff."
    )
    input_schema: ClassVar[type[AgentInput]] = MockInterviewInput

    # Intended smart-tier model; factory routes to MiniMax-M2.7 when
    # MINIMAX_API_KEY is set. Dynamic resolution in agentic_base.execute()
    # captures the actual model in agent_actions.
    model_name: ClassVar[str] = "claude-sonnet-4-6"

    uses_memory: ClassVar[bool] = True
    uses_tools: ClassVar[bool] = True
    uses_inter_agent: ClassVar[bool] = True
    # First v2 agent to flip uses_self_eval=True. CP3 single-turn smoke
    # verifies the Critic loop doesn't break the agent path; deeper
    # multi-turn Critic verification deferred.
    uses_self_eval: ClassVar[bool] = True
    uses_proactive: ClassVar[bool] = False

    allowed_callers: ClassVar[tuple[str, ...]] = ()
    # D-2 Option B: handoff_request fires through Supervisor re-invocation
    # at session_summary turns; allowed_callees declares the targets for
    # forward-compat with chain-construction.
    allowed_callees: ClassVar[tuple[str, ...]] = (
        "senior_engineer", "career_coach",
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
        self, input: MockInterviewInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Mock interview turn handler.

        Path:
          1. Resolve session_id (echo input.session_id or generate UUID).
          2. Recall mock_interview:session:{session_id} (prior turn log).
          3. Recall mock_interview:weakness: prefix (cross-session weaknesses).
          4. Build user_block with mode + session_id + recalls + candidate msg.
          5. Call LLM; extract text; truncate_to_schema; validate output.
          6. Defense-in-depth: force handoff_request=None on non-summary turns.
          7. Write turn output to mock_interview:session:{session_id}.
          8. On session_summary turns, write mock_interview:weakness:{topic}
             entries with negative valence per identified weakness.
          9. Compose answer projection.
        """
        from app.agents.llm_factory import build_llm

        session_id = input.session_id or uuid.uuid4()
        candidate_msg = input.resolved_message()

        # ── Recall: prior turns within this session ───────────────
        prior_turns = await _safe_recall(
            self,
            ctx,
            query=f"mock_interview:session:{session_id}",
            mode="structured",
            k=20,
        )

        # ── Recall: cross-session weaknesses ──────────────────────
        weakness_recall = await _safe_recall(
            self,
            ctx,
            query="mock_interview:weakness:",
            mode="structured",
            k=10,
        )

        # ── LLM call ──────────────────────────────────────────────
        system_prompt = _load_prompt("mock_interview")
        user_block = _build_user_block(
            mode=input.mode,
            session_id=session_id,
            candidate_message=candidate_msg,
            target_role=input.target_role,
            difficulty_level=input.difficulty_level,
            specific_topic=input.specific_topic,
            prior_turns=prior_turns,
            weaknesses=weakness_recall,
        )

        # max_tokens=8192 matches D12 v2 calibration. The schema is
        # smaller than career_coach's but the multi-turn rubric_summary +
        # session_summary turns can produce dense output; 8192 is the
        # smart-tier default and gives MiniMax thinking-block headroom.
        llm = build_llm(max_tokens=8192, tier="smart")
        response = await llm.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_block},
            ]
        )
        self._track_llm_usage(ctx, response)
        raw = _extract_text(response)
        output = _parse_output(raw, session_id=session_id, mode=input.mode)

        # Defense-in-depth: D-2 Option B — handoff_request only on session_summary.
        if output.turn_kind != "session_summary":
            output.handoff_request = None

        payload = output.model_dump(mode="json")
        payload["answer"] = _compose_answer(output)

        # ── Memory writes (best-effort) ───────────────────────────
        try:
            await _write_session_turn(self, ctx, session_id=session_id, output=output)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "mock_interview.session_write_failed",
                error=str(exc),
                session_id=str(session_id),
                user_id=str(ctx.user_id) if ctx.user_id else None,
            )
            try:
                await ctx.session.rollback()
            except Exception as rollback_exc:  # noqa: BLE001
                log.error(
                    "mock_interview.session_write_rollback_failed",
                    original_error=str(exc),
                    rollback_error=str(rollback_exc),
                )

        if output.turn_kind == "session_summary" and output.session_summary:
            try:
                await _write_weaknesses(
                    self, ctx, weaknesses=output.session_summary.weaknesses
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "mock_interview.weakness_write_failed",
                    error=str(exc),
                    user_id=str(ctx.user_id) if ctx.user_id else None,
                )
                try:
                    await ctx.session.rollback()
                except Exception as rollback_exc:  # noqa: BLE001
                    log.error(
                        "mock_interview.weakness_write_rollback_failed",
                        original_error=str(exc),
                        rollback_error=str(rollback_exc),
                    )

        return payload


# ── Helpers ───────────────────────────────────────────────────────


async def _safe_recall(
    agent: Any,
    ctx: AgentContext,
    *,
    query: str,
    mode: str,
    k: int,
) -> list[dict[str, Any]]:
    """Call memory_recall via agent.tool_call. Return list of recalled
    memory dicts (each = {id, key, value, similarity}); empty on failure.
    """
    args: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "k": k,
        "agent_name": "mock_interview",
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
        log.debug("mock_interview.recall_skipped", query=query, error=str(exc))
        return []


async def _write_session_turn(
    agent: Any,
    ctx: AgentContext,
    *,
    session_id: uuid.UUID,
    output: MockInterviewOutput,
) -> None:
    """Append this turn to mock_interview:session:{session_id}.

    Each turn writes to a turn-numbered key under the session prefix so
    structured recall can fetch all prior turns. We use the turn count
    derived from current time (microseconds) to keep keys distinct
    without an extra read; structured-recall sorts by recency.
    """
    import time

    args: dict[str, Any] = {
        "agent_name": "mock_interview",
        "scope": "user" if ctx.user_id is not None else "agent",
        "key": f"mock_interview:session:{session_id}:{int(time.time() * 1_000_000)}",
        "value": {
            "session_id": str(session_id),
            "mode": output.mode,
            "turn_kind": output.turn_kind,
            "payload": output.model_dump(mode="json"),
        },
        "valence": 0.0,
        "confidence": 1.0,
    }
    if ctx.user_id is not None:
        args["user_id"] = str(ctx.user_id)
    await agent.tool_call("memory_write", args, ctx)


async def _write_weaknesses(
    agent: Any,
    ctx: AgentContext,
    *,
    weaknesses: list[str],
) -> None:
    """On session_summary turns, write each weakness to
    mock_interview:weakness:{topic} with negative valence reflecting the
    surfaced gap. valence=-0.4 across the board for v1; more nuanced
    severity scoring lands in a follow-up.
    """
    for raw_topic in weaknesses:
        topic = raw_topic.strip().lower()
        if not topic:
            continue
        # Normalise whitespace + truncate aggressively so memory keys
        # don't blow past the 512-char limit.
        topic = re.sub(r"\s+", "_", topic)[:200]
        args: dict[str, Any] = {
            "agent_name": "mock_interview",
            "scope": "user" if ctx.user_id is not None else "agent",
            "key": f"mock_interview:weakness:{topic}",
            "value": {"topic": raw_topic, "source": "session_summary"},
            "valence": -0.4,
            "confidence": 0.7,
        }
        if ctx.user_id is not None:
            args["user_id"] = str(ctx.user_id)
        await agent.tool_call("memory_write", args, ctx)


def _build_user_block(
    *,
    mode: str,
    session_id: uuid.UUID,
    candidate_message: str | None,
    target_role: str | None,
    difficulty_level: str | None,
    specific_topic: str | None,
    prior_turns: list[dict[str, Any]],
    weaknesses: list[dict[str, Any]],
) -> str:
    parts = [
        f"## Mode\n\n{mode}",
        f"## Session id\n\n{session_id}",
    ]
    if candidate_message:
        parts.append(f"## Candidate message\n\n{candidate_message}")
    hints: dict[str, Any] = {}
    if target_role:
        hints["target_role"] = target_role
    if difficulty_level:
        hints["difficulty_level"] = difficulty_level
    if specific_topic:
        hints["specific_topic"] = specific_topic
    if hints:
        parts.append(
            f"## Optional hints\n\n```json\n{json.dumps(hints, indent=2)}\n```"
        )

    if prior_turns:
        # Project to the payload for the LLM (drop memory_id / similarity).
        prior_payloads = [m.get("value", {}).get("payload") for m in prior_turns]
        prior_payloads = [p for p in prior_payloads if p]
        if prior_payloads:
            parts.append(
                "## Prior turns this session\n\n"
                f"```json\n{json.dumps(prior_payloads, indent=2)}\n```"
            )
    if weaknesses:
        weakness_topics = [
            m.get("value", {}).get("topic", m.get("key", ""))
            for m in weaknesses
        ]
        weakness_topics = [t for t in weakness_topics if t]
        if weakness_topics:
            parts.append(
                "## Cross-session weaknesses\n\n"
                f"```json\n{json.dumps(weakness_topics, indent=2)}\n```"
            )

    parts.append(
        "## Instructions\n\n"
        "Return a single JSON object matching MockInterviewOutput. "
        "No markdown fences, no preamble."
    )
    return "\n\n".join(parts)


def _extract_text(response: Any) -> str:
    """Pull the assistant's text out of a LangChain ChatAnthropic response.

    Handles both shapes:
      • Anthropic SDK native — content blocks as objects with .type / .text
      • MiniMax Anthropic-compatible endpoint — content blocks as dicts

    Skips thinking blocks. Mirrors the D12 helper byte-for-byte to keep
    the Bug 10a fix consistent across v2 agents.
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


def _parse_output(
    raw: str,
    *,
    session_id: uuid.UUID,
    mode: str,
) -> MockInterviewOutput:
    """Extract the first balanced JSON object and validate.

    Defensive coercions:
      • If the LLM forgot session_id or echoed a different UUID, force ours.
      • If the LLM swapped mode (e.g., emitted 'systemDesign'), force input mode.

    These coercions defend the D-1 invariant (orchestrator owns session_id)
    and the cross-turn invariant (mode is constant per session).
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

    # Coerce invariants before truncate_to_schema so it sees the right values.
    raw_dict["session_id"] = str(session_id)
    raw_dict["mode"] = mode

    # D13 Bug 23: under MiniMax the LLM occasionally flattens nested
    # fields to the top level (e.g. emits handoff_type at the root
    # instead of nested under handoff_request). strip_extra_fields drops
    # those before truncate_to_schema runs, so model_validate sees a
    # clean dict and doesn't raise extra="forbid" errors. Canonical
    # composition: strip → truncate → validate.
    stripped = strip_extra_fields(raw_dict, MockInterviewOutput)
    truncated = truncate_to_schema(stripped, MockInterviewOutput)
    return MockInterviewOutput.model_validate(truncated)


def _compose_answer(output: MockInterviewOutput) -> str:
    """Top-level `answer` projection per the output-text-projection convention.

    Picks the most-relevant short string for each turn_kind so the chat
    surface has something readable without parsing the structured payload.
    """
    if output.turn_kind == "question" and output.question:
        return output.question.question_text
    if output.turn_kind == "evaluation" and output.evaluation:
        # Score + headline gap (or strength when no gaps).
        score = output.evaluation.score_0_to_10
        if output.evaluation.gaps:
            return f"{score}/10. Gap: {output.evaluation.gaps[0]}"
        if output.evaluation.strengths:
            return f"{score}/10. Strength: {output.evaluation.strengths[0]}"
        return f"{score}/10."
    if output.turn_kind == "feedback" and output.feedback:
        return output.feedback.overall_assessment
    if output.turn_kind == "session_summary" and output.session_summary:
        return output.session_summary.headline
    return ""


__all__ = ["MockInterviewAgent"]
