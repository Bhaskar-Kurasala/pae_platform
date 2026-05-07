"""D9 / Pass 3b §3.1, Pass 3f §B.3 — AgentCapability registry.

The Supervisor reads its `available_agents` list from this registry.
Each agent declares its capability once; the Supervisor's prompt is
built dynamically from the registered capabilities at request time.
This decouples the Supervisor from agent implementations — adding or
retiring an agent is a registration change, not a Supervisor change.

D9 Checkpoint 1 inventory: 12 specialist capabilities + supervisor
itself = 13 total declarations. Of those, only `learning_coach`
(D8-migrated) is `available_now=True`. The rest stay
`available_now=False` until their migration deliverable lands.

The retired/merged legacy agents (socratic_tutor, student_buddy,
adaptive_path, spaced_repetition, knowledge_graph, curriculum_mapper,
cover_letter, job_match, peer_matching, deep_capturer,
community_celebrator, disrupt_prevention, adaptive_quiz) get NO
capability declaration — they remain reachable ONLY via the legacy
MOA endpoint until Pass 3j / D17 deletes them. code_review and
coding_assistant were ALSO in this list pre-D11; they were
absorbed into senior_engineer at the D11 cutover (Checkpoint 4),
so they're no longer reachable via either path.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

import structlog

from app.core.tiers import TierName, tier_meets_minimum
from app.schemas.entitlement import EntitlementContext
from app.schemas.supervisor import AgentCapability

log = structlog.get_logger().bind(layer="capability_registry")


# ── The 13 v1 capability declarations ──────────────────────────────


_CAPABILITIES: Final[list[AgentCapability]] = [
    # ── Group J / OS Infrastructure: Supervisor itself ───────────────
    AgentCapability(
        name="supervisor",
        description=(
            "The orchestrator. Routes student requests to specialist "
            "agents, manages chains and handoffs, enforces policy. "
            "Free-tier accessible because every agentic request goes "
            "through it; tier filtering happens inside its prompt."
        ),
        inputs_required=["user_message"],
        outputs_provided=["route_decision"],
        # D12 CP3 Phase 4 calibration: observed ~26s P95 under MiniMax
        # (consistent across multiple smoke runs). 9000ms typical * 3 = 27s
        # which floors to 30s; matches observation. Was 800ms (Anthropic-era
        # estimate when supervisor's route-decision call was sub-second).
        typical_latency_ms=9000,
        typical_cost_inr=Decimal("0.40"),
        requires_entitlement=False,
        minimum_tier="free",
        available_now=True,
        handoff_targets=[],
    ),
    # ── Group A / Tutoring & Learning ────────────────────────────────
    AgentCapability(
        name="learning_coach",
        description=(
            "The canonical teaching agent. Replaces socratic_tutor, "
            "student_buddy, adaptive_path, spaced_repetition, and "
            "knowledge_graph. Stateful coach across chat, cron, and "
            "webhook entry points. Use for: explaining concepts, "
            "Socratic dialogue, study sessions, mastery checks, "
            "personalized learning plans."
        ),
        inputs_required=["question"],
        inputs_optional=["course_context", "current_lesson"],
        outputs_provided=["explanation", "follow_up_questions"],
        typical_latency_ms=2500,
        typical_cost_inr=Decimal("3.50"),
        requires_entitlement=True,
        minimum_tier="standard",
        available_now=True,  # MIGRATED in D8 — only specialist live in D9
        handoff_targets=["senior_engineer", "career_coach"],
    ),
    # ── Group B / Content Generation ─────────────────────────────────
    AgentCapability(
        name="mcq_factory",
        description=(
            "Generates multiple-choice questions. Stateless content "
            "generator. Use for: building quizzes, generating drill "
            "cards, creating spaced-repetition prompts."
        ),
        inputs_required=["concept", "difficulty"],
        outputs_provided=["mcq_set"],
        typical_latency_ms=1800,
        typical_cost_inr=Decimal("2.00"),
        requires_entitlement=True,
        minimum_tier="standard",
        available_now=False,  # awaits future migration
        handoff_targets=[],
    ),
    # ── Group C / Code & Engineering ─────────────────────────────────
    AgentCapability(
        name="senior_engineer",
        description=(
            "Reviews student-submitted code with a senior engineer's "
            "voice — direct, kind, no sycophancy. Three modes: "
            "'pr_review' for structured PR-style feedback (verdict + "
            "comments + next step), 'chat_help' for conversational "
            "debugging and code discussion, 'rubric_score' for graded "
            "code-review exercises. Reads the student's prior code "
            "submissions and prior reviews to track patterns. Best "
            "for: code review, debugging help, code quality questions, "
            "'is this approach right'. Requires `code` in context. "
            "v1 is LLM-only — does NOT execute code, run tests, or "
            "run static analysis (sandbox tools land in D14)."
        ),
        inputs_required=["code"],
        inputs_optional=["problem_context", "mode", "language", "test_results"],
        outputs_provided=["review", "verdict", "next_step", "handoff_request"],
        typical_latency_ms=10000,
        typical_cost_inr=Decimal("3.50"),
        requires_entitlement=True,
        minimum_tier="standard",
        # D11 Checkpoint 1 — capability flipped on. The agent class
        # itself lands in Checkpoint 2; for now the registry advertises
        # senior_engineer as available so Supervisor's filtered_agents
        # logic can include it during chain construction even before
        # the AgenticBaseAgent subclass is wired.
        available_now=True,
        # Pass 3c E2 lists ["mock_interview", "learning_coach"]. v1
        # (D11) ships handoff_targets as INFORMATIONAL METADATA only —
        # the Supervisor's chain-construction logic uses this hint
        # up-front, but specialist HandoffRequest returns are NOT
        # honored post-hoc until D13. See
        # docs/followups/handoff-protocol-d11-d13.md for the Option B
        # decision.
        handoff_targets=["mock_interview", "learning_coach"],
    ),
    AgentCapability(
        name="project_evaluator",
        description=(
            "Capstone evaluation against published rubrics. Reads the "
            "full capstone artifact + rubric, returns scored evaluation. "
            "Use for: capstone grading, portfolio-readiness checks."
        ),
        inputs_required=["capstone_id"],
        outputs_provided=["evaluation_report", "score"],
        typical_latency_ms=8000,
        typical_cost_inr=Decimal("8.00"),
        requires_entitlement=True,
        minimum_tier="standard",
        available_now=False,  # awaits D14
        handoff_targets=["portfolio_builder"],
    ),
    # ── Group D / Career Services ────────────────────────────────────
    AgentCapability(
        name="career_coach",
        description=(
            "Builds personalized 90-day career plans for students transitioning "
            "into senior GenAI engineering. Reads the student's mastery state, "
            "completed projects, capstone progress, target role, and goal contract "
            "to ground advice in their actual situation. Coordinates with "
            "study_planner (for weekly tactical plans), resume_reviewer (for "
            "portfolio review), and mock_interview (for readiness checks). Best "
            "for: 'what should I focus on next', 'am I ready to apply for jobs', "
            "'how do I get from where I am to senior GenAI engineer', career "
            "direction questions. Does not handle: day-to-day study scheduling "
            "(study_planner), resume editing (resume_reviewer), interview practice "
            "(mock_interview). v1: market signals (salary/hiring data) not available."
        ),
        inputs_required=[],
        inputs_optional=["target_role", "specific_question", "timeline_weeks"],
        outputs_provided=["plan", "milestones", "concerns", "handoff_requests"],
        # D12 CP3 Phase 4 calibration (Bug 16 ricochet): 90s override
        # was sufficient at max_tokens=2048 (LLM completed in 69s but
        # truncated mid-JSON). After bumping max_tokens to 8192 to fix
        # truncation, MiniMax expanded its output (more thinking + more
        # text) and the call exceeds 90s. Override raised to 150s —
        # absorbs the heavy-output case under MiniMax. Pure-LLM measured
        # P50 was 45s at 1280 output tokens; at 5000+ tokens (8192 budget
        # × ~60% non-thinking) the proportional generation time is
        # ~3-4x. 150s = 30% margin over 4x estimate.
        typical_latency_ms=15000,
        timeout_override_seconds=150,
        typical_cost_inr=Decimal("4.00"),
        requires_entitlement=True,
        minimum_tier="standard",
        # D12 CP1 — capability flipped. Agent class lands in CP2.
        # handoff_targets is informational metadata (Option B per
        # docs/followups/handoff-protocol-d11-d13.md). mock_interview
        # and portfolio_builder declared now for forward compat even
        # though they don't exist yet.
        available_now=True,
        handoff_targets=["study_planner", "resume_reviewer", "mock_interview", "portfolio_builder"],
    ),
    AgentCapability(
        name="study_planner",
        description=(
            "Builds tactical weekly and daily study plans. Given a student's "
            "available hours, current course progress, due SRS cards, capstone "
            "state, and upcoming interview goals, produces time-blocked plans for "
            "the week and specific plans for tonight's session. Best for: 'what "
            "should I do this week', 'I have 2 hours tonight, what should I focus "
            "on', 'my plan slipped, help me catch up'. Different from career_coach "
            "(strategic 90-day plans) and adaptive_path (which lessons to take "
            "next). Reads goal_contract for hours commitment."
        ),
        inputs_required=[],
        inputs_optional=["available_hours_this_week", "session_duration_minutes", "specific_focus"],
        outputs_provided=["weekly_plan", "session_plan", "adherence_check"],
        # D12 CP3 Phase 4 calibration: Phase 2 verification measured 25.6s
        # for 1081 output tokens, no tools. 9000ms * 3 = 27s floors to 30s.
        # Was 6000 (Anthropic-era estimate).
        typical_latency_ms=9000,
        typical_cost_inr=Decimal("1.50"),
        requires_entitlement=True,
        minimum_tier="standard",
        # D12 CP1 — NEW agent, no legacy reference.
        available_now=True,
        handoff_targets=["career_coach"],
    ),
    AgentCapability(
        name="resume_reviewer",
        description=(
            "Reviews resumes for engineers transitioning into GenAI roles. "
            "Cross-references resume claims against the student's actual "
            "capstones, exercise submissions, and GitHub activity to flag claims "
            "unsupported by evidence and to suggest additions for accomplishments "
            "the student undersold. Best for: 'review my resume', 'is this resume "
            "ready', 'what should I add or remove'. Different from tailored_resume "
            "(which generates JD-tailored versions)."
        ),
        inputs_required=["resume_text"],
        inputs_optional=["target_role", "specific_concerns"],
        outputs_provided=["review", "score", "suggested_changes"],
        # D12 CP3 Phase 4 calibration (Bug 16 ricochet): observed 36s
        # timeout under formula-derived budget after max_tokens bump
        # to 8192. Resume_reviewer's schema has 4 nested object types
        # (UnsupportedClaim, Accomplishment, ResumeSuggestion ×2 in
        # issues + suggested_changes); under MiniMax with thinking
        # blocks the heavy-output case structurally exceeds the formula
        # ceiling. Override to 90s — same pattern as career_coach,
        # lighter than tailored_resume's 120s pipeline.
        typical_latency_ms=12000,
        timeout_override_seconds=90,
        typical_cost_inr=Decimal("3.00"),
        requires_entitlement=True,
        minimum_tier="standard",
        # D12 CP1 — flipped. portfolio_builder declared for forward compat.
        available_now=True,
        handoff_targets=["portfolio_builder"],
    ),
    AgentCapability(
        name="tailored_resume",
        description=(
            "Generates a JD-tailored, ATS-safe version of the student's resume "
            "for a specific job description. Reads the student's base resume + "
            "capstones + submissions and rewrites for keyword match and role fit. "
            "Best for: 'tailor my resume for this JD'. Different from "
            "resume_reviewer (which critiques rather than generates). Note: "
            "mandatory self-validation via resume_reviewer is deferred to D13."
        ),
        inputs_required=["resume_text", "job_description"],
        inputs_optional=["specific_emphasis"],
        outputs_provided=["tailored_resume", "changes_made", "ats_score"],
        typical_latency_ms=10000,
        typical_cost_inr=Decimal("3.50"),
        requires_entitlement=True,
        minimum_tier="standard",
        # D12 CP1 — flipped. resume_reviewer declared for D13 mandatory chain.
        available_now=True,
        handoff_targets=["resume_reviewer"],
        # D12 CP3 Phase 3 (Bug 6) — full tailored_resume pipeline does
        # JD parse + evidence allowlist + tailoring + cover letter +
        # validation across 3-5 inner LLM calls. Structurally exceeds
        # the 60s formula ceiling; override to 120s.
        timeout_override_seconds=120,
    ),
    # ── Group E / Interview ──────────────────────────────────────────
    AgentCapability(
        name="mock_interview",
        description=(
            "Conducts mock interviews across multiple formats: "
            "system_design, coding, behavioral, take_home. Reads the "
            "student's prior session history, identified weaknesses, "
            "and target role to calibrate difficulty. Tracks weakness "
            "patterns across sessions. Suggests senior_engineer (for "
            "code-level review when the candidate fails a coding round) "
            "or career_coach (for strategic readiness gaps) at session "
            "close. Best for: 'mock interview', 'practice for an "
            "interview', 'evaluate me on system design'. Different from "
            "career_coach (strategic 90-day plans) and senior_engineer "
            "(code review). Sessions are stateful across multiple turns "
            "via session_id."
        ),
        inputs_required=["mode"],
        inputs_optional=[
            "session_id", "target_role", "difficulty_level", "specific_topic",
        ],
        outputs_provided=[
            "session_id", "turn_kind", "question", "evaluation",
            "feedback", "session_summary",
        ],
        # D13 CP3 calibration: measured P50 ~35s under MiniMax with the
        # self_eval Critic loop active (main agent ~17s + Critic ~16s +
        # safety classifier 2s). The 3x formula on typical_latency_ms
        # alone would resolve to a budget below the measured run length,
        # so we use timeout_override_seconds=60 to set a hard 60s budget
        # explicitly. Pattern matches D12 career_coach (override=150) and
        # tailored_resume (override=120) — agents whose structural floor
        # exceeds what the typical_latency_ms × 3 formula expresses.
        # typical_latency_ms stays at 12000 as the no-Critic baseline so
        # downstream consumers (UI ETA, cost forecasting) see realistic
        # main-agent latency, not the Critic-inclusive worst case.
        typical_latency_ms=12000,
        timeout_override_seconds=60,
        typical_cost_inr=Decimal("3.00"),  # per turn; full session is multiple turns
        requires_entitlement=True,
        minimum_tier="standard",
        # D13 CP1 — capability flipped. Agent class lands in CP2 + CP3.
        # handoff_targets is informational metadata (Option B per D-2);
        # mock_interview emits HandoffRequest only on turn_kind=
        # "session_summary" turns (post-session suggestion), never
        # mid-session. True state-preserving mid-session handoff is
        # deferred to a future deliverable.
        available_now=True,
        handoff_targets=["senior_engineer", "career_coach"],
    ),
    # ── Group F / Content Pipeline ───────────────────────────────────
    AgentCapability(
        name="content_ingestion",
        description=(
            "Background-only ingestion from GitHub / YouTube / free "
            "text into the curriculum graph. NOT student-facing — "
            "fired by webhooks, not chat. Listed in the registry so "
            "the Supervisor can decline politely if a student tries to "
            "invoke it directly."
        ),
        inputs_required=["source_url"],
        outputs_provided=["ingestion_report"],
        typical_latency_ms=15000,
        typical_cost_inr=Decimal("10.00"),
        requires_entitlement=False,  # webhook-driven; not student-billed
        minimum_tier="free",  # even free-tier student can't actually invoke it
        available_now=False,  # awaits D15
        handoff_targets=[],
    ),
    # ── Group G / Engagement ─────────────────────────────────────────
    AgentCapability(
        name="progress_report",
        description=(
            "Weekly narrative summary of student progress. Cron-fired "
            "(not chat-fired); reads agent_memory across other agents "
            "and synthesizes a personalized recap. Listed for "
            "Supervisor awareness; not directly invokable."
        ),
        inputs_required=["user_id", "week_of"],
        outputs_provided=["narrative_report"],
        typical_latency_ms=4500,
        typical_cost_inr=Decimal("3.50"),
        requires_entitlement=True,
        minimum_tier="standard",
        available_now=False,  # awaits D16
        handoff_targets=[],
    ),
    # ── Group H / Portfolio ──────────────────────────────────────────
    AgentCapability(
        name="portfolio_builder",
        description=(
            "Generates portfolio entries from completed capstones. "
            "Markdown output suitable for embedding in a personal "
            "site or GitHub README. Use for: post-capstone "
            "documentation, GitHub README generation."
        ),
        inputs_required=["capstone_id"],
        outputs_provided=["portfolio_entry"],
        typical_latency_ms=3500,
        typical_cost_inr=Decimal("3.00"),
        requires_entitlement=True,
        minimum_tier="standard",
        available_now=False,  # awaits future migration
        handoff_targets=[],
    ),
    # ── Group I / Operations ─────────────────────────────────────────
    AgentCapability(
        name="billing_support",
        description=(
            "Account, billing, and entitlement Q&A. Free-tier "
            "accessible — students whose subscription expired can "
            "still ask 'what happened to my account?' and get a real "
            "answer. Routes refunds to support email; does not itself "
            "process refunds."
        ),
        inputs_required=["question"],
        outputs_provided=["answer", "next_action"],
        typical_latency_ms=1500,
        typical_cost_inr=Decimal("0.80"),
        requires_entitlement=True,  # gated, but minimum_tier=free includes it
        minimum_tier="free",  # available to expired-subscription students
        available_now=True,  # MIGRATED in D10
        handoff_targets=[],
    ),
]


# Index by name for O(1) lookup.
_BY_NAME: Final[dict[str, AgentCapability]] = {
    cap.name: cap for cap in _CAPABILITIES
}


# ── Public API ─────────────────────────────────────────────────────


def list_capabilities() -> list[AgentCapability]:
    """Return every registered capability. Caller must NOT mutate.

    Returns a list (not a view) so the caller can iterate freely;
    individual AgentCapability instances are pydantic BaseModels and
    treated as immutable by convention.
    """
    return list(_CAPABILITIES)


def get_capability(name: str) -> AgentCapability | None:
    """Return one capability by name, or None if unregistered.

    Used by the dispatch layer to validate that the Supervisor's
    chosen target_agent is real before invoking. The fallback path
    in dispatch.py treats None here as a hallucinated agent name.
    """
    return _BY_NAME.get(name)


def filter_capabilities_for_user(
    capabilities: list[AgentCapability],
    entitlement_ctx: EntitlementContext,
) -> list[AgentCapability]:
    """Filter a capability list down to what this user can reach.

    Three gates per Pass 3f §B.3:
      1. Tier gate: user's tier must meet minimum_tier
      2. Free-tier allow-list (if user is on free tier)
      3. available_now gate (rate limits, dependency health)

    This is what the Supervisor's prompt sees as available_agents.
    Layer 3 dispatch re-runs this same check just before invoking
    a specialist, catching mid-flight tier changes.
    """
    user_tier: TierName = entitlement_ctx.effective_tier
    free_allowlist = (
        entitlement_ctx.free_tier.allowed_agents
        if entitlement_ctx.free_tier is not None
        else set()
    )
    has_paid = bool(entitlement_ctx.active_entitlements)

    out: list[AgentCapability] = []
    for cap in capabilities:
        if not cap.available_now:
            continue
        if not tier_meets_minimum(user_tier, cap.minimum_tier):
            continue
        if not has_paid:
            # Pure free-tier user: must be in the explicit allow-list
            # OR the agent doesn't require entitlement at all (e.g.
            # supervisor itself).
            if cap.requires_entitlement and cap.name not in free_allowlist:
                continue
        out.append(cap)
    return out


# ── Per-agent dispatch timeout resolver (D12 CP3 Phase 3) ──────────


# Floor: 30s — matches the prior production behavior so already-shipped
# agents (D8 supervisor, D10 billing_support, D11 senior_engineer) get
# at least the budget they were operating under successfully. The "3x
# typical" formula scales correctly in the middle of the range but
# breaks down at the bottom because real-world LLM tail latency doesn't
# scale linearly with typical (P99 of a 1500ms-typical agent is more
# often 5-10s than 4.5s). 30s absorbs that tail.
#
# Ceiling: 60s — keeps the orchestrator from holding a connection for
# minutes on a single specialist. Agents that structurally need longer
# (multi-LLM pipelines) set timeout_override_seconds explicitly.
#
# Multiplier: 3x typical — gives a ~99th percentile envelope under
# normal LLM latency distributions while staying well clear of HTTP
# server-side limits.
_TIMEOUT_FLOOR_SECONDS: Final[int] = 30
_TIMEOUT_CEILING_SECONDS: Final[int] = 60
_TIMEOUT_MULTIPLIER: Final[float] = 3.0


def resolve_timeout_seconds(capability: AgentCapability) -> float:
    """Per-agent dispatch timeout (D12 CP3 Phase 3 — Bug 11 / Bug 6).

    Returns the wall-clock budget the orchestrator's `asyncio.wait_for`
    around `callee.run_agentic` should use for this specific agent.

    Resolution order:
      1. If `capability.timeout_override_seconds` is set, use it verbatim.
         This is the escape hatch for agents whose structural latency
         doesn't fit the formula (e.g. tailored_resume's multi-LLM
         pipeline, override=120).
      2. Otherwise, derive from `typical_latency_ms`:
         max(30, min(60, typical_latency_ms * 3 / 1000))
         Floor and ceiling protect against runaway values; the floor
         in particular ensures no shipped agent regresses below the
         prior 30s flat default.

    Pure function — safe to call from anywhere capability is reachable.
    """
    if capability.timeout_override_seconds is not None:
        return float(capability.timeout_override_seconds)
    formula_seconds = capability.typical_latency_ms * _TIMEOUT_MULTIPLIER / 1000.0
    return float(
        max(
            _TIMEOUT_FLOOR_SECONDS,
            min(_TIMEOUT_CEILING_SECONDS, formula_seconds),
        )
    )


def all_known_agent_names() -> set[str]:
    """Set of every agent name the Supervisor knows about.

    Used by dispatch.py to validate that the Supervisor's RouteDecision
    target_agent is on the registered list. Anything else is a
    hallucination and triggers fallback per Pass 3b §7.1 Failure Class B.
    """
    return set(_BY_NAME.keys())


__all__ = [
    "all_known_agent_names",
    "filter_capabilities_for_user",
    "get_capability",
    "list_capabilities",
    "resolve_timeout_seconds",
]
