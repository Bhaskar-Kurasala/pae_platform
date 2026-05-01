"""Reference agentic agent — Learning Coach.

This file is the canonical template a future agent author copies
and modifies. It is also the production Learning Coach: the real
agent that replaces (eventually retires) socratic_tutor,
student_buddy, adaptive_path, spaced_repetition, and
knowledge_graph from the legacy registry.

Three entry points, each demonstrating different primitives in
their natural context:

  1. `run(input, ctx)` — the chat path. Student asks a question.
     We recall what we know about them from memory, ground the
     answer in real course content via tool calls, deliver a
     Socratic-discipline reply, and stash any newly-observed
     preferences back into memory.

     Primitives shown: memory (recall + write), tools
     (search_course_content, get_student_state).

  2. `run_nightly_check(user_id, ctx)` — proactive cron-fired
     sweep. For each student, we read their state, check whether
     any mastery decayed below threshold, and either schedule a
     review or call the (hypothetical) Code Mentor agent to
     review a stalled capstone. Critic verifies the nudge isn't
     a generic mass-mail.

     Primitives shown: inter-agent (call_agent), self-eval
     (uses_self_eval=True is set on the proactive method ONLY,
     not on the chat path — see `_proactive_self_eval` below).

  3. `run_on_github_push(payload, ctx)` — webhook-triggered
     when the student pushes to a tracked repo. We acknowledge
     the milestone with an inbox card and update mastery if the
     push closed a known capstone.

     Primitives shown: webhook → @on_event registration, tool
     (send_student_message + update_mastery), memory (record
     "shipped X on date Y" so future questions can ground in
     the student's own work).

Why one agent and not three: in production these three flows
share state. The student who asked a question this morning
(chat path) is the same one whose capstone push fires tonight
(webhook). Memory written in path 1 is recalled in path 3. The
single-agent design is what lets the Coach feel like a coach
across days, not a stateless responder per turn.

Why this is "ready" rather than "stub": every prompt, every
tool call, every memory key is what a production deploy will
ship. The tools themselves (recall_memory, search_course_content,
etc.) have stub bodies today (D3); when those bodies land, this
agent's behaviour upgrades automatically. No code changes here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import structlog
from pydantic import ConfigDict, Field

from app.agents.agentic_base import AgentContext, AgentInput, AgenticBaseAgent
from app.agents.primitives.evaluation import AgentResult
from app.agents.primitives.memory import MemoryWrite
from app.agents.primitives.proactive import on_event, proactive

log = structlog.get_logger().bind(layer="learning_coach")


# ── Input shapes ────────────────────────────────────────────────────


class LearningCoachInput(AgentInput):
    """Chat-path input: the student's question + optional course
    anchor.

    `question` is the free-form text the student typed.
    `lesson_id` and `course_id` are optional anchors that let us
    scope the RAG search; when omitted, the search is global.
    `style` reflects student preference (set in their profile;
    we read from memory if not supplied)."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    lesson_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    style: str = "concise"


class _NightlyCheckInput(AgentInput):
    """Proactive cron-path input — built by the runner.

    Per-user fan-out: one of these per active student per night."""

    model_config = ConfigDict(extra="forbid")

    cron: str
    scheduled_for: str  # iso-8601


class _GitHubPushInput(AgentInput):
    """Webhook-path input — built by the @on_event handler.

    Carries the relevant slice of the GitHub push payload, not the
    raw 30-key event body."""

    model_config = ConfigDict(extra="forbid")

    repo: str
    commit_sha: str
    pusher_login: str
    branch: str
    files_changed: list[str] = Field(default_factory=list)


# ── Prompt files ────────────────────────────────────────────────────


_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Read a prompt file by name. Falls back to an inline default
    when the file is absent so the agent boots in environments
    where the prompts directory isn't synced (e.g. minimal CI
    images). Production runs always have the files."""
    path = _PROMPTS_DIR / f"{name}.md"
    if path.exists():
        return path.read_text()
    return _INLINE_DEFAULTS.get(name, "")


# Inline-default copies of the prompts — used as a fallback when
# the .md file isn't on disk. Keeping them here means the agent
# is fully self-contained in this single .py file (D8 is the
# "documentation in code" reference; copying this file gives you
# a working agent without hunting for prompt assets).
_INLINE_DEFAULTS: dict[str, str] = {
    "learning_coach_chat": (
        "You are the Learning Coach for a production AI engineering platform. "
        "Your students are working professionals reskilling toward GenAI roles.\n\n"
        "Style: Socratic. You guide with questions, not lectures. Every response "
        "should contain at least one question that nudges the student to a deeper "
        "level of understanding. Direct answers are reserved for definitions and "
        "factual lookups; explanations are scaffolded.\n\n"
        "Available context (from the platform):\n"
        "  • What you remember about this student (from memory).\n"
        "  • Their current course progress and skill mastery.\n"
        "  • Relevant excerpts from course content (search_course_content).\n\n"
        "If the student asks for code, explain the *why* before showing the *what*. "
        "If they ask 'just give me the answer', honour the request but follow up "
        "with one question that surfaces what they're missing."
    ),
    "learning_coach_nightly": (
        "You are the Learning Coach checking in on a student overnight. Generate "
        "a SHORT (50-120 word) personal nudge based on:\n"
        "  • What you remember about this student.\n"
        "  • Their current progress (lessons completed, mastery deltas).\n"
        "  • The slip pattern that triggered this check.\n\n"
        "Do NOT write a generic re-engagement email. The nudge must reference "
        "something specific to this student — a project they mentioned, a "
        "concept they were stuck on, a milestone they hit last week.\n\n"
        "Output the nudge text only — no greetings, no signature."
    ),
}


# ── The agent ───────────────────────────────────────────────────────


@proactive(
    agent_name="learning_coach",
    cron="0 9 * * *",
    per_user=True,
    description="Daily morning check-in on each active student.",
)
@on_event(
    "github.push",
    agent_name="learning_coach",
)
class LearningCoach(AgenticBaseAgent[LearningCoachInput]):
    """The reference Learning Coach.

    Subclass this if you want a Coach variant for a specific cohort
    (e.g. EnterpriseLeaderCoach with `name = "enterprise_coach"`);
    most agents will be standalone copies of this template.

    Note the layered class-level config:
      • uses_memory + uses_tools + uses_inter_agent: True (defaults)
      • uses_self_eval: False (default; we override on the proactive
        path inline, see _proactive_self_eval)
      • uses_proactive: True (we want the cron + webhook paths to
        be discoverable; the boot ordering in celery_app.py reads
        the @proactive decorator above)
    """

    name: ClassVar[str] = "learning_coach"
    description: ClassVar[str] = (
        "Replaces socratic_tutor / student_buddy / adaptive_path / "
        "spaced_repetition / knowledge_graph. Stateful coach across "
        "chat, cron, and webhook entry points."
    )
    input_schema: ClassVar[type[AgentInput]] = LearningCoachInput
    uses_proactive: ClassVar[bool] = True
    # We turn self-eval ON for the proactive nudge path (where a
    # generic mass-mail is the failure mode the critic catches).
    # The chat path runs without self-eval (latency-sensitive,
    # students see typing indicators). Per-method tuning is done
    # by checking ctx.extra inside the method, not by overriding
    # the class flag — see `run_nightly_check` below.
    uses_self_eval: ClassVar[bool] = False

    # Optional: explicitly name who can call us. Empty allow-list =
    # any caller. The Coach is intentionally permissive — other
    # agents that want to delegate "explain this concept to the
    # student" should be able to do so without paperwork.
    allowed_callers: ClassVar[tuple[str, ...]] = ()
    allowed_callees: ClassVar[tuple[str, ...]] = (
        # When the student asks about their own code submission,
        # we delegate to the Code Mentor — it has the tools that
        # actually compile and run code. Listed here so a future
        # CodeMentor.allowed_callers check authorizes this hop.
        "code_mentor",
    )

    # ── Chat path ──────────────────────────────────────────────────

    async def run(
        self, input: LearningCoachInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Daily chat — student asks a question, we answer Socratically.

        Sequence:
          1. Recall what we know about the student (memory).
          2. Read their current state from the platform (tool).
          3. Search course content for grounding (tool).
          4. Build the prompt with all three signals + the question.
          5. Invoke the LLM, return the response.
          6. Stash any new preference observations back to memory.
        """
        memories = await self._recall_student_memories(input.question, ctx)
        student_state = await self._fetch_student_state(ctx)
        course_excerpts = await self._search_relevant_content(input, ctx)

        answer = await self._answer_socratically(
            input=input,
            student_state=student_state,
            memories=memories,
            course_excerpts=course_excerpts,
            ctx=ctx,
        )

        # Observation-driven memory write: if the student told us
        # something durable about themselves ("I'm dyslexic", "I
        # prefer code-first explanations"), capture it. The
        # detector is a simple keyword match today; a future
        # version will ask the LLM to extract preferences as a
        # structured field, but the API here doesn't change.
        await self._maybe_record_preference(input, ctx)

        return {
            "answer": answer,
            "memories_used": len(memories),
            "had_course_grounding": bool(course_excerpts),
        }

    # ── Proactive cron path ────────────────────────────────────────

    async def run_nightly_check(
        self,
        user_id: uuid.UUID,
        ctx: AgentContext,
    ) -> AgentResult:
        """Nightly per-student sweep, fired by the proactive runner.

        Detects whether the student is slipping (mastery drop, no
        recent activity, capstone stalled) and either:
          • Posts a personalized inbox nudge.
          • Calls the Code Mentor agent if a capstone is stuck.

        This is the path where self-eval EARNS its keep — generic
        nudges are the failure mode, and the critic catches them.
        We invoke `evaluate_with_retry` directly (instead of going
        through `execute()` with `uses_self_eval=True`) so the
        chat path stays critic-free.
        """
        from app.agents.primitives.evaluation import (
            DEFAULT_MAX_RETRIES,
            DEFAULT_THRESHOLD,
            evaluate_with_retry,
        )

        student_state = await self._fetch_student_state(
            ctx.model_copy(update={"user_id": user_id})
        )
        slip_pattern = self._detect_slip(student_state)
        if slip_pattern is None:
            log.info("nightly.no_slip", user_id=str(user_id))
            return AgentResult(
                output={"action": "no_action_needed"},
                score=None,
                reasoning=None,
                retry_count=0,
                escalated=False,
            )

        # If the slip is "capstone stalled", delegate to Code Mentor
        # via inter-agent call. Code Mentor has the tools that can
        # actually read the PR, run the code, etc. We pass enough
        # context that it doesn't need to re-fetch what we know.
        if slip_pattern == "capstone_stalled":
            mentor_result = await self.call(
                "code_mentor",
                payload={
                    "user_id": str(user_id),
                    "trigger": "capstone_stalled_24h",
                    "student_summary": (
                        student_state.get("snapshot", {})
                        if student_state
                        else {}
                    ),
                },
                ctx=ctx.model_copy(update={"user_id": user_id}),
            )
            return AgentResult(
                output={
                    "action": "delegated_to_code_mentor",
                    "mentor_status": mentor_result.status,
                },
                score=None,
                reasoning=None,
                retry_count=0,
                escalated=False,
            )

        # Otherwise, draft a personalised nudge. The critic checks
        # that the nudge references something specific to this
        # student — generic mass-mails get a low score and trigger
        # a retry with the critic's feedback.
        memories = await self._recall_student_memories(
            "personal context for nightly nudge", ctx
        )

        async def _draft(feedback: str | None) -> str:
            return await self._draft_nightly_nudge(
                user_id=user_id,
                slip_pattern=slip_pattern,
                memories=memories,
                student_state=student_state,
                critic_feedback=feedback,
                ctx=ctx,
            )

        request_str = (
            f"Draft a nightly nudge for user_id={user_id}, slip={slip_pattern}, "
            f"with {len(memories)} memory rows of personal context."
        )
        result = await evaluate_with_retry(
            agent_name=self.name,
            request=request_str,
            coro_factory=_draft,
            session=ctx.session,
            critic=self._critic(),
            threshold=DEFAULT_THRESHOLD,
            max_retries=DEFAULT_MAX_RETRIES,
            user_id=user_id,
            call_chain_id=ctx.chain.root_id,
            limiter=self._limiter(),
        )

        # If the nudge passed eval, post it. Escalated nudges are
        # held for admin review (the audit row carries the best
        # attempt).
        if not result.escalated:
            await self._post_inbox_nudge(
                user_id=user_id,
                body=str(result.output or ""),
                slip_pattern=slip_pattern,
                ctx=ctx,
            )
        return result

    # ── Webhook path ───────────────────────────────────────────────

    async def run_on_github_push(
        self,
        payload: _GitHubPushInput,
        ctx: AgentContext,
    ) -> dict[str, Any]:
        """Triggered when the student pushes to a tracked repo.

        We acknowledge the milestone with an inbox card and stash
        a memory row so the next chat can reference it ("nice work
        shipping the retry decorator yesterday — let's talk about
        backoff strategies").
        """
        # Memory write: durable record that the student shipped X.
        # The chat path's `_recall_student_memories` will surface
        # this when the student asks anything related.
        if ctx.user_id is not None:
            await self.memory(ctx).write(
                MemoryWrite(
                    user_id=ctx.user_id,
                    agent_name=self.name,
                    scope="user",
                    key=f"shipped:{payload.repo}:{payload.commit_sha[:8]}",
                    value={
                        "repo": payload.repo,
                        "branch": payload.branch,
                        "files_changed": payload.files_changed[:20],
                        "shipped_at": datetime.now(UTC).isoformat(),
                    },
                    valence=0.6,  # mildly positive — a push is forward motion
                    confidence=1.0,
                )
            )

        # Inbox card. Idempotency: keyed on commit_sha so a redelivery
        # doesn't post twice (the @on_event boundary already dedups
        # at agent_proactive_runs, but the inbox card has its own
        # idempotency surface).
        if ctx.user_id is not None:
            sent = await self.tool_call(
                "send_student_message",
                {
                    "user_id": str(ctx.user_id),
                    "kind": "celebration",
                    "title": f"Shipped to {payload.repo}",
                    "body": (
                        f"Saw your push to `{payload.branch}` — "
                        f"{len(payload.files_changed)} file(s) changed. "
                        f"When you're ready, ask me anything about it."
                    ),
                    "idempotency_key": f"push:{payload.commit_sha}",
                },
                ctx,
            )
        else:
            sent = None

        return {
            "memory_written": ctx.user_id is not None,
            "inbox_status": sent.status if sent else "skipped_no_user",
        }

    # ── Internal helpers ───────────────────────────────────────────

    async def _recall_student_memories(
        self,
        query: str,
        ctx: AgentContext,
    ) -> list[dict[str, Any]]:
        """Recall up to 5 memories for this student bound to the
        coach's scope.

        We do TWO recall calls: one structured (substring match
        across all keys this coach has stored — surfaces durable
        preferences like `accessibility:dyslexic` and milestones
        like `shipped:repo:sha`), one semantic (embedding
        similarity to the query — surfaces related conversation
        memories). We dedupe by id and return up to k.

        Why both: structured catches "who is this student?" facts
        (preferences, accessibility, shipped artifacts) regardless
        of what they're asking. Semantic catches "what's relevant
        to *this* question?" topical memories. The chat path needs
        both — a generic recall against `query` alone misses the
        personality dossier."""
        if ctx.user_id is None:
            return []
        store = self.memory(ctx)
        # Structured pass: pull recent memories regardless of the
        # query string. Empty string acts as a "match anything"
        # against the coach's stored keys, sorted by recency.
        structured = await store.recall(
            "",  # match any key
            user_id=ctx.user_id,
            agent_name=self.name,
            scope="user",
            mode="structured",
            k=5,
        )
        # Semantic pass: query-relevant context.
        semantic = await store.recall(
            query,
            user_id=ctx.user_id,
            agent_name=self.name,
            scope="user",
            mode="semantic",
            k=5,
        )
        # Dedupe by id, structured first (preferences appear at
        # the top of the dossier).
        seen: set[Any] = set()
        merged: list[Any] = []
        for row in list(structured) + list(semantic):
            if row.id in seen:
                continue
            seen.add(row.id)
            merged.append(row)
            if len(merged) >= 5:
                break
        return [
            {
                "key": row.key,
                "value": row.value,
                "similarity": row.similarity,
            }
            for row in merged
        ]

    async def _fetch_student_state(self, ctx: AgentContext) -> dict[str, Any]:
        """Wrap `get_student_state` so the agent's main flow doesn't
        special-case the stub-error path. When the tool returns
        status='error' (today's stub behaviour), we treat it as
        "no state available" and continue. Production behaviour
        (status='ok' with real data) drops in unchanged."""
        if ctx.user_id is None:
            return {}
        result = await self.tool_call(
            "get_student_state",
            {"user_id": str(ctx.user_id)},
            ctx,
        )
        if result.status != "ok" or result.output is None:
            return {}
        try:
            return result.output.model_dump(mode="json")  # type: ignore[union-attr]
        except AttributeError:
            return dict(result.output) if isinstance(result.output, dict) else {}

    async def _search_relevant_content(
        self,
        input: LearningCoachInput,
        ctx: AgentContext,
    ) -> list[dict[str, Any]]:
        """RAG search. Empty list when the tool isn't available yet
        (the agent then answers from prompt + memory only — degraded
        but not broken)."""
        result = await self.tool_call(
            "search_course_content",
            {
                "query": input.question,
                "course_id": str(input.course_id) if input.course_id else None,
                "lesson_id": str(input.lesson_id) if input.lesson_id else None,
                "k": 3,
            },
            ctx,
        )
        if result.status != "ok" or result.output is None:
            return []
        try:
            hits = result.output.model_dump(mode="json")["hits"]  # type: ignore[union-attr]
        except (AttributeError, KeyError):
            return []
        return list(hits or [])

    async def _answer_socratically(
        self,
        *,
        input: LearningCoachInput,
        student_state: dict[str, Any],
        memories: list[dict[str, Any]],
        course_excerpts: list[dict[str, Any]],
        ctx: AgentContext,
    ) -> str:
        """Build the prompt and invoke the LLM. The prompt has four
        slots — system, student state, memory, course excerpts —
        plus the student's question. Order matters: state and
        memory before excerpts so the LLM treats course content
        as one input among many, not the only input."""
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.agents.llm_factory import build_llm

        system_prompt = _load_prompt("learning_coach_chat")
        context_block = self._build_context_block(
            student_state=student_state,
            memories=memories,
            course_excerpts=course_excerpts,
            style=input.style,
        )
        messages: list[Any] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{context_block}\n\nStudent: {input.question}"),
        ]

        llm = self._build_llm(max_tokens=1024)
        response = await llm.ainvoke(messages)
        return self._extract_text(response.content)

    async def _draft_nightly_nudge(
        self,
        *,
        user_id: uuid.UUID,
        slip_pattern: str,
        memories: list[dict[str, Any]],
        student_state: dict[str, Any],
        critic_feedback: str | None,
        ctx: AgentContext,
    ) -> str:
        """Draft the nightly nudge body. When the critic has run
        and rejected a previous draft, `critic_feedback` carries
        the rejection reasoning; we inject it so the next attempt
        has a chance to address it."""
        from langchain_core.messages import HumanMessage, SystemMessage

        system_prompt = _load_prompt("learning_coach_nightly")
        context_block = self._build_context_block(
            student_state=student_state,
            memories=memories,
            course_excerpts=[],
            style="warm_short",
        )
        feedback_line = (
            f"\n\nThe previous draft was rejected by the quality critic. "
            f"Reasoning: {critic_feedback}\n"
            f"Address the critique in your next draft."
            if critic_feedback
            else ""
        )
        messages: list[Any] = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=(
                    f"Slip pattern: {slip_pattern}\n"
                    f"{context_block}{feedback_line}"
                )
            ),
        ]
        llm = self._build_llm(max_tokens=300)
        response = await llm.ainvoke(messages)
        return self._extract_text(response.content)

    async def _post_inbox_nudge(
        self,
        *,
        user_id: uuid.UUID,
        body: str,
        slip_pattern: str,
        ctx: AgentContext,
    ) -> None:
        """Post the (critic-approved) nudge to the student inbox.

        Idempotency key includes the date so a re-fire of the
        same nightly cron doesn't post twice. The proactive layer
        also dedups via agent_proactive_runs, but inbox-side dedup
        is a belt-and-suspenders against bugs in the layer above."""
        date_bucket = datetime.now(UTC).strftime("%Y%m%d")
        await self.tool_call(
            "send_student_message",
            {
                "user_id": str(user_id),
                "kind": "nudge",
                "title": "A note from your Learning Coach",
                "body": body,
                "idempotency_key": f"nightly:{slip_pattern}:{date_bucket}:{user_id}",
            },
            ctx,
        )

    async def _maybe_record_preference(
        self,
        input: LearningCoachInput,
        ctx: AgentContext,
    ) -> None:
        """Naive preference detector. The student saying "I'm
        dyslexic" or "I learn better from code" is durable signal;
        we capture it so future turns can adjust style.

        A future iteration runs an LLM extraction step here. The
        memory write API doesn't change — only the detection
        logic improves."""
        if ctx.user_id is None:
            return
        text = (input.question or "").lower()
        triggers: list[tuple[str, str]] = [
            ("dyslexic", "accessibility:dyslexic"),
            ("learn better from code", "preferred_style:code_first"),
            ("explain like i'm five", "preferred_style:eli5"),
            ("i'm a junior", "experience_level:junior"),
            ("i'm a senior", "experience_level:senior"),
        ]
        for needle, key in triggers:
            if needle in text:
                await self.memory(ctx).write(
                    MemoryWrite(
                        user_id=ctx.user_id,
                        agent_name=self.name,
                        scope="user",
                        key=key,
                        value={
                            "observed_at": datetime.now(UTC).isoformat(),
                            "raw_phrase": needle,
                            "source_question": input.question[:240],
                        },
                        valence=0.0,
                        confidence=0.85,
                    )
                )

    @staticmethod
    def _detect_slip(student_state: dict[str, Any]) -> str | None:
        """Map a state snapshot to a slip-pattern label, or None
        when the student is on track. Same pattern names the
        retention engine uses (paid_silent, capstone_stalled,
        streak_broken, …) so admin dashboards stay coherent
        across triggers."""
        snap = student_state.get("snapshot") if student_state else None
        if not snap:
            return None
        days_idle = snap.get("days_since_last_login")
        progress = snap.get("overall_progress_pct")
        if isinstance(days_idle, (int, float)) and days_idle > 7:
            return "streak_broken"
        if (
            isinstance(progress, (int, float))
            and 0 < progress < 50
            and isinstance(days_idle, (int, float))
            and days_idle > 3
        ):
            return "capstone_stalled"
        return None

    @staticmethod
    def _build_context_block(
        *,
        student_state: dict[str, Any],
        memories: list[dict[str, Any]],
        course_excerpts: list[dict[str, Any]],
        style: str,
    ) -> str:
        """Render the four context slots into a single string the
        LLM consumes. We use plain text rather than JSON because
        Anthropic models prompt-respond better to prose-shaped
        context than to a literal JSON dump."""
        parts: list[str] = [f"[Style preference: {style}]"]
        if student_state:
            snap = student_state.get("snapshot", {})
            if snap:
                parts.append(
                    "[Student state]\n"
                    + "\n".join(
                        f"  - {k}: {v}" for k, v in snap.items() if v is not None
                    )
                )
        if memories:
            parts.append(
                "[What I remember about this student]\n"
                + "\n".join(
                    f"  - {m['key']}: {m['value']}"
                    for m in memories
                    if m.get("value") is not None
                )
            )
        if course_excerpts:
            parts.append(
                "[Relevant course excerpts]\n"
                + "\n".join(
                    f"  - {h.get('lesson_title', '?')}: "
                    f"{h.get('snippet', '')[:200]}"
                    for h in course_excerpts
                )
            )
        return "\n\n".join(parts)

    def _build_llm(self, *, max_tokens: int = 1024) -> Any:
        """Build the agent's LLM. Centralised so subclasses (or
        tests via monkeypatch) can swap the model without touching
        every call site. Production uses claude-sonnet-4-6 (the
        legacy default for tutoring agents); cheaper paths can
        override to `tier='fast'`."""
        from app.agents.llm_factory import build_llm

        return build_llm(max_tokens=max_tokens, tier="smart")

    @staticmethod
    def _extract_text(content: Any) -> str:
        """Anthropic occasionally returns a list of content blocks
        when extended thinking is enabled. We harvest the text
        parts; everything else is silently dropped."""
        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "".join(text_parts)
        return str(content)


__all__ = [
    "LearningCoach",
    "LearningCoachInput",
]
