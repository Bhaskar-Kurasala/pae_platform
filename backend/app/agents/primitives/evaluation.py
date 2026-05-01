"""Self-evaluation, retry, and escalation — Agentic OS Primitive 4.

Three pieces compose:

  Critic              — LLM-as-judge. Sends a request +
                         response pair to a small model with a
                         strict JSON output contract. Returns a
                         CriticVerdict.
  evaluate_with_retry — Orchestrator. Calls the agent, asks the
                         critic, retries once with critic reasoning
                         injected if the score < threshold, then
                         escalates after two consecutive failures.
  EscalationLimiter   — Per-agent sliding-window rate limit on the
                         admin-notification flag. Below limit:
                         notified_admin=True. Above: row still
                         lands for forensics, flag stays False.

Design choices (also noted in docs/_drafts/agentic-os-conventions.md
for D9 to surface in AGENTIC_OS.md):

  • Critic prompt is sent at temperature=0 with a JSON-only contract.
    Malformed output → score=None, passed=None, log loud. We do NOT
    default to passing. Default-to-pass means evaluation silently
    disappears the moment the critic flakes.

  • Escalation rate limit is per-agent + sliding-window (default 5
    per hour). Beyond the limit, escalations still write for the
    forensic audit; only the admin notification is suppressed. One
    broken prompt no longer drowns the real signal.

  • Self-eval is OFF by default in dev (settings.enable_self_eval
    lands in D10). Flip it on per-agent once you have baseline
    scores; that's why this primitive doesn't read the flag itself.
    Callers gate the call with `if settings.enable_self_eval:`.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives import metrics
from app.models.agent_escalation import AgentEscalation
from app.models.agent_evaluation import AgentEvaluation

log = structlog.get_logger().bind(layer="evaluation")


# ── Constants ───────────────────────────────────────────────────────


# Default per-agent escalation budget. The notification flag is
# tripped to False once an agent crosses this threshold within the
# window — escalations after that still write for forensics, but
# they don't page anyone. 5/hour is empirical: enough to surface a
# real incident, tight enough to clip a runaway loop quickly.
DEFAULT_ESCALATION_LIMIT_PER_AGENT = 5
DEFAULT_ESCALATION_WINDOW_SECONDS = 3600

# Default critic threshold and retry budget. Each agent may
# override at call time. 0.6 is the "needs work" floor; 1 retry
# means each user-facing exec triggers at most 2 critic calls.
DEFAULT_THRESHOLD = 0.6
DEFAULT_MAX_RETRIES = 1


# ── Critic protocol + verdict ───────────────────────────────────────


@runtime_checkable
class CriticLLM(Protocol):
    """Tiny protocol over "thing we hand a prompt and get text back".

    We deliberately don't depend on `langchain_anthropic.ChatAnthropic`
    directly — that lets unit tests inject a deterministic stub
    without monkeypatching the global LLM factory. The production
    Critic builds a Haiku-tier ChatAnthropic via `llm_factory` (see
    Critic.default_llm()).
    """

    async def ainvoke_text(self, prompt: str) -> str: ...


class CriticVerdict(BaseModel):
    """Strict JSON contract the critic LLM must return.

    Three sub-scores — accuracy (did the response answer the
    question), helpfulness (is it useful for the student's stated
    goal), completeness (did it cover what was asked) — plus a free-
    form reasoning string. The orchestrator computes total_score as
    the unweighted mean of whichever sub-scores were emitted; an
    agent that only scores on one dimension can just return one
    sub-score and `null` for the others.

    `extra='forbid'` is intentional: the LLM may not invent fields,
    and we want validation to reject loosely-structured responses
    (we re-prompt rather than smuggle through bogus JSON).
    """

    model_config = ConfigDict(extra="forbid")

    accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    helpful: float | None = Field(default=None, ge=0.0, le=1.0)
    complete: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=2000)


_CRITIC_SYSTEM_PROMPT = """\
You are a strict but fair evaluator of an AI agent's response.

Given the student's request and the agent's response, score the
response on three dimensions, each from 0.0 to 1.0:

  • accuracy   — does the response factually address what was asked?
  • helpful    — does it move the student toward their goal?
  • complete   — does it cover the asked-for scope, not just a slice?

Return ONLY a JSON object with these keys:
  {
    "accuracy": <float|null>,
    "helpful":  <float|null>,
    "complete": <float|null>,
    "reasoning": "<one to three sentences explaining the scores>"
  }

Rules:
  • Output JSON only. No prose before or after the object.
  • If a dimension does not apply to this response (e.g. asking
    'completeness' on a one-line celebration message), set it to
    null, not 0. Null means "not applicable", 0 means "fails".
  • Be calibrated: 0.7 is "good with caveats", 0.9 is "excellent",
    0.5 is "needs work but salvageable", 0.3 is "wrong direction".
  • `reasoning` is a short justification — not a grade rationale.
    The student never sees this; admins use it to decide whether
    to retry or escalate.
"""


_CRITIC_USER_TEMPLATE = """\
STUDENT REQUEST:
{request}

AGENT RESPONSE:
{response}
"""


@dataclass(frozen=True, slots=True)
class CriticResult:
    """Internal carrier — verdict + the parsed total score, plus
    `parsed_ok` so callers can tell apart "scored low" from "critic
    flaked"."""

    verdict: CriticVerdict | None
    total_score: float | None
    parsed_ok: bool
    raw_response: str


class Critic:
    """LLM-as-judge.

    Construct with an injected LLM (any object satisfying CriticLLM).
    Call `evaluate(request, response)` to get a CriticResult.

    The default constructor is `Critic.default()`, which builds a
    Haiku-tier ChatAnthropic via the existing `llm_factory`. That's
    the path production callers use; tests inject a stub directly.
    """

    def __init__(self, llm: CriticLLM) -> None:
        self._llm = llm

    @classmethod
    def default(cls) -> "Critic":
        """Build a Critic backed by Haiku (cheap, fast).

        Imports the LLM factory lazily so this module stays
        importable even when langchain isn't installed (e.g. early
        unit tests on a slim env).
        """
        return cls(_DefaultLLM())

    async def evaluate(
        self,
        *,
        request: str,
        response: str,
    ) -> CriticResult:
        """Send the request/response pair to the critic LLM.

        Returns a CriticResult with parsed_ok=False on any of:
          • LLM call raised
          • response wasn't valid JSON
          • JSON didn't match the CriticVerdict schema

        On parsed_ok=False we log loud and let the caller decide what
        to do — the contract is "we will not silently default-to-pass
        a flaky critic."
        """
        prompt = self._build_prompt(request=request, response=response)
        try:
            raw = await self._llm.ainvoke_text(prompt)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "critic.llm_call_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return CriticResult(
                verdict=None,
                total_score=None,
                parsed_ok=False,
                raw_response=f"<llm error: {type(exc).__name__}: {exc}>",
            )

        verdict = self._parse_verdict(raw)
        if verdict is None:
            log.warning(
                "critic.malformed_response",
                raw_preview=raw[:200] if raw else "<empty>",
            )
            return CriticResult(
                verdict=None,
                total_score=None,
                parsed_ok=False,
                raw_response=raw,
            )

        total = self._compute_total(verdict)
        return CriticResult(
            verdict=verdict,
            total_score=total,
            parsed_ok=True,
            raw_response=raw,
        )

    @staticmethod
    def _build_prompt(*, request: str, response: str) -> str:
        # Single string includes the system prompt + the user
        # template. The injected LLM is responsible for splitting
        # if its API uses chat-style messages — the contract here
        # is "string in, string out" so a unit-test stub stays
        # trivial.
        body = _CRITIC_USER_TEMPLATE.format(
            request=(request or "")[:8000],
            response=(response or "")[:8000],
        )
        return f"{_CRITIC_SYSTEM_PROMPT}\n\n{body}"

    @staticmethod
    def _parse_verdict(raw: str) -> CriticVerdict | None:
        """Extract the first JSON object from the response and
        validate against CriticVerdict. Returns None on any failure.

        The LLM is instructed to emit JSON-only, but defensive
        parsing handles the case where it leaks a leading "Sure!"
        or a trailing "Hope that helps." — find the first balanced
        { } pair, parse that.
        """
        if not raw:
            return None

        # Find first balanced JSON object via brace matching.
        first = raw.find("{")
        if first == -1:
            return None
        depth = 0
        end = -1
        for i in range(first, len(raw)):
            ch = raw[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            return None

        try:
            data = json.loads(raw[first:end])
        except json.JSONDecodeError:
            return None

        try:
            return CriticVerdict.model_validate(data)
        except ValidationError:
            return None

    @staticmethod
    def _compute_total(verdict: CriticVerdict) -> float:
        """Mean of whichever sub-scores were provided.

        Returns 0.0 only if all three are None — which we treat as
        "the critic returned a verdict but couldn't score any
        dimension", a soft fail. The orchestrator should NOT
        threshold-pass on a 0.0 total.
        """
        scores = [
            s for s in (verdict.accuracy, verdict.helpful, verdict.complete)
            if s is not None
        ]
        if not scores:
            return 0.0
        return sum(scores) / len(scores)


class _DefaultLLM:
    """Production critic LLM: Haiku at temperature=0.

    Wraps ChatAnthropic via the existing llm_factory. The factory
    already handles the API key, retry, and model selection — we
    just pin tier='fast' (Haiku) and temperature=0 so two runs
    against the same input produce the same verdict.
    """

    def __init__(self) -> None:
        self._llm: Any | None = None

    async def ainvoke_text(self, prompt: str) -> str:
        if self._llm is None:
            from app.agents.llm_factory import build_llm

            # tier="fast" → Haiku. Pin temperature=0 for determinism;
            # max_tokens=400 is plenty for the critic's JSON object
            # plus reasoning string.
            self._llm = build_llm(max_tokens=400, tier="fast", temperature=0.0)

        from langchain_core.messages import HumanMessage

        # The critic sees one message; system content is folded into
        # the prompt body so the protocol stays string-in / string-out.
        response = await self._llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            # Anthropic occasionally returns a list of content blocks
            # when thinking is enabled. We only care about the text
            # parts.
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "".join(text_parts)
        return str(content)


# ── Escalation rate limiter ────────────────────────────────────────


class EscalationLimiter:
    """Per-agent sliding-window rate limit on admin notifications.

    Process-local in-memory implementation. A multi-worker deploy
    will see slightly higher effective limits (each worker carries
    its own deque), but the hard cap on notifications is still tight
    enough to prevent a flood. A redis-backed implementation is a
    future swap behind the same API.

    The limiter ONLY governs the `notified_admin` flag. Escalation
    rows themselves are written unconditionally — they're the audit
    trail.
    """

    def __init__(
        self,
        *,
        limit_per_agent: int = DEFAULT_ESCALATION_LIMIT_PER_AGENT,
        window_seconds: int = DEFAULT_ESCALATION_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = max(0, limit_per_agent)
        self._window = window_seconds
        self._clock = clock
        # agent_name → deque of monotonic-second timestamps for
        # *notified* (not just written) escalations within the
        # current window.
        self._buckets: dict[str, deque[float]] = {}

    def should_notify(self, agent_name: str) -> bool:
        """Return True iff the next escalation should set
        notified_admin=True.

        Side effect: when True, the timestamp is recorded so the
        next call counts against the budget. When False, the bucket
        is unchanged — over-quota escalations don't perpetually
        extend their own quota.
        """
        if self._limit <= 0:
            return False
        now = self._clock()
        bucket = self._buckets.setdefault(agent_name, deque())
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._limit:
            return False
        bucket.append(now)
        return True

    def reset(self, agent_name: str | None = None) -> None:
        """Test helper — clears the bucket for one agent or all."""
        if agent_name is None:
            self._buckets.clear()
        else:
            self._buckets.pop(agent_name, None)


# Process-local singleton. The limiter is stateful and per-process;
# AgenticBaseAgent (D7) reads from this. Tests can monkeypatch the
# module attribute or call `.reset()`.
escalation_limiter = EscalationLimiter()


# ── AgentResult + retry orchestrator ───────────────────────────────


@dataclass(slots=True)
class AgentResult:
    """What `evaluate_with_retry` returns.

    Carries the final output, the latest score, the critic's
    reasoning (handy for surfacing into admin views), the number of
    retries actually consumed, and an `escalated` flag.

    `evaluation_ids` lists every agent_evaluations row written
    during this call — typically 1 (single attempt passed) or 2
    (one retry). Useful for forensic queries that want the score
    progression across attempts.
    """

    output: Any
    score: float | None
    reasoning: str | None
    retry_count: int = 0
    escalated: bool = False
    evaluation_ids: list[uuid.UUID] = field(default_factory=list)
    escalation_id: uuid.UUID | None = None
    notified_admin: bool = False


# Type alias: the agent function we evaluate. Takes optional
# critic-feedback context (None on first attempt, the critic's
# reasoning on retry) and returns the agent's response.
AgentCoroFactory = Callable[[str | None], Awaitable[Any]]


async def evaluate_with_retry(
    *,
    agent_name: str,
    request: str,
    coro_factory: AgentCoroFactory,
    session: AsyncSession,
    critic: Critic | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    max_retries: int = DEFAULT_MAX_RETRIES,
    user_id: uuid.UUID | None = None,
    call_chain_id: uuid.UUID | None = None,
    limiter: EscalationLimiter | None = None,
) -> AgentResult:
    """Run an agent, critique it, retry with feedback, escalate on fail.

    Flow:
      1. Call `coro_factory(None)` — first attempt.
      2. Critic evaluates request + response.
      3. Score >= threshold → return AgentResult ok.
      4. Score < threshold AND budget remains → call
         `coro_factory(critic_reasoning)` so the agent can refine
         with feedback. Goto 2.
      5. Budget exhausted → write agent_escalations row, return
         AgentResult(escalated=True). Best attempt is preserved
         in `output`.

    The orchestrator is critic-tolerant: a critic that returns
    parsed_ok=False produces score=None for the attempt, which
    fails the threshold check (None is not >= 0.6). The retry path
    fires; the agent gets one more shot. If the critic flakes both
    times, we escalate with `reasoning="critic returned malformed
    JSON across N attempts"` so the admin sees the real issue.

    `coro_factory(critic_feedback)` is the caller's hook to inject
    feedback into the next attempt's prompt. The first call passes
    None; retries pass the critic's reasoning string. Caller
    decides how (if at all) to surface that into the agent's prompt.
    """
    critic = critic or Critic.default()
    limiter = limiter or escalation_limiter
    attempts: list[tuple[Any, CriticResult]] = []

    last_feedback: str | None = None
    for attempt_num in range(1, max_retries + 2):  # +1 first attempt + retries
        try:
            output = await coro_factory(last_feedback)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "evaluate.agent_call_failed",
                agent=agent_name,
                attempt=attempt_num,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            # The agent itself raised — record a failed evaluation
            # row so the admin dashboard sees the attempt happened.
            verdict_score = None
            verdict_reasoning = (
                f"agent raised {type(exc).__name__}: {exc}"
            )
            await _write_evaluation_row(
                session=session,
                agent_name=agent_name,
                user_id=user_id,
                call_chain_id=call_chain_id,
                attempt_number=attempt_num,
                verdict=None,
                total_score=verdict_score,
                threshold=threshold,
                passed=False,
                critic_reasoning=verdict_reasoning,
            )
            attempts.append(
                (
                    None,
                    CriticResult(
                        verdict=None,
                        total_score=None,
                        parsed_ok=False,
                        raw_response=verdict_reasoning,
                    ),
                )
            )
            last_feedback = verdict_reasoning
            metrics.AGENT_EVAL_SCORE_HISTOGRAM.labels(agent=agent_name).observe(
                0.0
            )
            continue

        critic_result = await critic.evaluate(
            request=request,
            response=_to_str(output),
        )
        score = critic_result.total_score
        passed = (
            critic_result.parsed_ok
            and score is not None
            and score >= threshold
        )
        evaluation_id = await _write_evaluation_row(
            session=session,
            agent_name=agent_name,
            user_id=user_id,
            call_chain_id=call_chain_id,
            attempt_number=attempt_num,
            verdict=critic_result.verdict,
            total_score=score if score is not None else 0.0,
            threshold=threshold,
            passed=passed,
            critic_reasoning=(
                critic_result.verdict.reasoning
                if critic_result.verdict is not None
                else f"critic flaked: {critic_result.raw_response[:300]}"
            ),
        )
        attempts.append((output, critic_result))
        if score is not None:
            metrics.AGENT_EVAL_SCORE_HISTOGRAM.labels(agent=agent_name).observe(
                score
            )

        if passed:
            log.info(
                "evaluate.passed",
                agent=agent_name,
                attempt=attempt_num,
                score=score,
                threshold=threshold,
            )
            return AgentResult(
                output=output,
                score=score,
                reasoning=(
                    critic_result.verdict.reasoning
                    if critic_result.verdict is not None
                    else None
                ),
                retry_count=attempt_num - 1,
                escalated=False,
                evaluation_ids=[evaluation_id]
                if evaluation_id is not None
                else [],
            )

        log.info(
            "evaluate.failed",
            agent=agent_name,
            attempt=attempt_num,
            score=score,
            threshold=threshold,
            parsed_ok=critic_result.parsed_ok,
        )
        # Feed the critic's reasoning to the next attempt so the
        # agent can refine. If the critic flaked, last_feedback is
        # the raw response — better than nothing but the next
        # attempt likely still fails.
        last_feedback = (
            critic_result.verdict.reasoning
            if critic_result.verdict is not None
            else critic_result.raw_response[:1000]
        )

    # Retry budget exhausted. Pick the best attempt by score (None
    # treated as worse than 0) and escalate.
    best_output, best_critic = max(
        (a for a in attempts if a[0] is not None),
        key=lambda a: (a[1].total_score or -1.0),
        default=(None, attempts[-1][1] if attempts else CriticResult(
            verdict=None, total_score=None, parsed_ok=False, raw_response=""
        )),
    )
    best_score = best_critic.total_score
    best_reasoning = (
        best_critic.verdict.reasoning
        if best_critic.verdict is not None
        else f"critic could not produce a verdict across {len(attempts)} attempts"
    )

    notify = limiter.should_notify(agent_name)
    escalation_id = await _write_escalation_row(
        session=session,
        agent_name=agent_name,
        user_id=user_id,
        call_chain_id=call_chain_id,
        reason=(
            f"eval below {threshold} after {len(attempts)} attempts; "
            f"best score = {best_score}"
        ),
        best_attempt={
            "output": _to_jsonable(best_output),
            "score": best_score,
            "reasoning": best_reasoning,
            "attempts": len(attempts),
        },
        notified_admin=notify,
    )

    log.warning(
        "evaluate.escalated",
        agent=agent_name,
        attempts=len(attempts),
        best_score=best_score,
        notified_admin=notify,
    )

    return AgentResult(
        output=best_output,
        score=best_score,
        reasoning=best_reasoning,
        retry_count=max_retries,
        escalated=True,
        evaluation_ids=[],  # written incrementally above; not collected here
        escalation_id=escalation_id,
        notified_admin=notify,
    )


# ── DB helpers ──────────────────────────────────────────────────────


async def _write_evaluation_row(
    *,
    session: AsyncSession,
    agent_name: str,
    user_id: uuid.UUID | None,
    call_chain_id: uuid.UUID | None,
    attempt_number: int,
    verdict: CriticVerdict | None,
    total_score: float,
    threshold: float,
    passed: bool,
    critic_reasoning: str,
) -> uuid.UUID | None:
    """Insert one agent_evaluations row. Returns its id."""
    try:
        row = AgentEvaluation(
            agent_name=agent_name,
            user_id=user_id,
            call_chain_id=call_chain_id,
            attempt_number=attempt_number,
            accuracy_score=verdict.accuracy if verdict else None,
            helpful_score=verdict.helpful if verdict else None,
            complete_score=verdict.complete if verdict else None,
            total_score=max(0.0, min(1.0, total_score)),
            threshold=threshold,
            passed=passed,
            critic_reasoning=critic_reasoning[:2000] if critic_reasoning else None,
        )
        session.add(row)
        await session.flush()
        return row.id
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "evaluate.write_evaluation_failed",
            error=str(exc),
            agent=agent_name,
        )
        return None


async def _write_escalation_row(
    *,
    session: AsyncSession,
    agent_name: str,
    user_id: uuid.UUID | None,
    call_chain_id: uuid.UUID | None,
    reason: str,
    best_attempt: dict[str, Any],
    notified_admin: bool,
) -> uuid.UUID | None:
    """Insert one agent_escalations row."""
    try:
        row = AgentEscalation(
            agent_name=agent_name,
            user_id=user_id,
            call_chain_id=call_chain_id,
            reason=reason[:2000],
            best_attempt=best_attempt,
            notified_admin=notified_admin,
        )
        session.add(row)
        await session.flush()
        return row.id
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "evaluate.write_escalation_failed",
            error=str(exc),
            agent=agent_name,
        )
        return None


def _to_str(value: Any) -> str:
    """Best-effort string coercion for the critic prompt body."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _to_jsonable(value: Any) -> dict[str, Any] | None | str:
    """Coerce arbitrary output into JSONB-safe shape for storage."""
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return value
    return repr(value)


__all__ = [
    "AgentCoroFactory",
    "AgentResult",
    "Critic",
    "CriticLLM",
    "CriticResult",
    "CriticVerdict",
    "DEFAULT_ESCALATION_LIMIT_PER_AGENT",
    "DEFAULT_ESCALATION_WINDOW_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_THRESHOLD",
    "EscalationLimiter",
    "escalation_limiter",
    "evaluate_with_retry",
]
