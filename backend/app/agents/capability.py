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
        typical_latency_ms=800,
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
            "Strategic career direction over 90-day windows. NOT "
            "tactical (that's study_planner). Use for: career-switch "
            "questions, role-targeting, market positioning, when to "
            "start interviewing."
        ),
        inputs_required=["question"],
        inputs_optional=["target_role", "current_role"],
        outputs_provided=["plan", "rationale"],
        typical_latency_ms=3000,
        typical_cost_inr=Decimal("4.50"),
        requires_entitlement=True,
        minimum_tier="standard",
        available_now=False,  # awaits D12
        handoff_targets=["resume_reviewer", "tailored_resume"],
    ),
    AgentCapability(
        name="resume_reviewer",
        description=(
            "Structured resume critique against industry expectations. "
            "Reads existing resume, returns line-by-line feedback + "
            "rewrite suggestions. Use for: resume polishing, role-fit "
            "alignment, gap framing."
        ),
        inputs_required=["resume_text"],
        inputs_optional=["target_jd"],
        outputs_provided=["critique", "suggestions"],
        typical_latency_ms=3500,
        typical_cost_inr=Decimal("4.00"),
        requires_entitlement=True,
        minimum_tier="standard",
        available_now=False,  # awaits D12
        handoff_targets=["tailored_resume"],
    ),
    AgentCapability(
        name="tailored_resume",
        description=(
            "Generates a JD-tailored resume from the student's master "
            "resume + a target job description. Calls resume_reviewer "
            "for self-validation. Use for: applying to a specific role, "
            "rewriting bullets for a JD."
        ),
        inputs_required=["master_resume", "jd_text"],
        outputs_provided=["tailored_resume"],
        typical_latency_ms=5000,
        typical_cost_inr=Decimal("6.50"),
        requires_entitlement=True,
        minimum_tier="standard",
        available_now=False,  # awaits D12
        handoff_targets=["resume_reviewer"],
    ),
    # ── Group E / Interview ──────────────────────────────────────────
    AgentCapability(
        name="mock_interview",
        description=(
            "Stateful FAANG-style mock interviews across system "
            "design, coding, behavioral, and take-home formats. "
            "Maintains session state across multiple Supervisor "
            "invocations within an interview. Use for: interview prep, "
            "weakness identification, format-specific practice."
        ),
        inputs_required=["format"],
        inputs_optional=["target_role", "session_id"],
        outputs_provided=["question", "feedback", "next_step"],
        typical_latency_ms=3500,
        typical_cost_inr=Decimal("5.00"),
        requires_entitlement=True,
        minimum_tier="standard",
        available_now=False,  # awaits D13
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
]
