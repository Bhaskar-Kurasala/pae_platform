"""D9 / Pass 3b — Supervisor data contract.

Schemas for the Supervisor's input (SupervisorContext + supporting
types) and output (RouteDecision + ChainStep). The Supervisor speaks
Pydantic, not free text — the Critic (D5) validates decisions
structurally, the dispatch layer reads them deterministically.

These types are read by:
  - backend/app/agents/supervisor.py (the agent itself)
  - backend/app/services/agentic_orchestrator.py (builds context)
  - backend/app/services/student_snapshot_service.py (computes snapshot)
  - backend/app/agents/dispatch.py (executes decisions)
  - backend/app/api/v1/routes/agentic.py (the canonical endpoint)
  - backend/app/agents/capability.py (the capability registry)

Subsequent agent migrations (D10+) read AgentCapability when
declaring their capabilities and StudentSnapshot when consuming
context the Supervisor passes them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Capability registry ─────────────────────────────────────────────


class AgentCapability(BaseModel):
    """The Supervisor's view of a single specialist agent.

    Each agent declares its capability at registration time. This
    decouples the Supervisor from agent implementations — adding an
    agent is a registration change, not a Supervisor change.

    `description` is written for the Supervisor's reasoning, not for
    humans. It needs to be specific enough that an LLM can match
    intents to it; vague capability descriptions produce wrong routes.

    `available_now` is computed live (rate limit state, dependency
    health, tier filtering); the Supervisor's prompt sees only
    capabilities with available_now=True after EntitlementContext
    filtering — that's the structural enforcement of tier gating.
    """

    name: str
    description: str
    inputs_required: list[str] = Field(default_factory=list)
    inputs_optional: list[str] = Field(default_factory=list)
    outputs_provided: list[str] = Field(default_factory=list)
    typical_latency_ms: int = 0
    typical_cost_inr: Decimal = Decimal("0")
    requires_entitlement: bool = True
    minimum_tier: Literal["free", "standard", "premium"] = "standard"
    available_now: bool = True
    handoff_targets: list[str] = Field(default_factory=list)


# ── Student snapshot (curated student model) ────────────────────────
#
# These small reference types let the snapshot stay typed end-to-end
# without each consumer re-parsing JSON. They are intentionally
# narrow — fields the Supervisor needs for routing decisions, not
# the full memory bank or full progress detail (those are tools).


class CourseRef(BaseModel):
    course_id: uuid.UUID
    slug: str
    title: str


class ConceptRef(BaseModel):
    concept_id: uuid.UUID | None = None
    slug: str
    name: str
    mastery: float | None = None  # 0.0..1.0 if known, else None


class MisconceptionRef(BaseModel):
    misconception_id: uuid.UUID | None = None
    slug: str
    description: str
    last_observed_at: datetime | None = None


class ProgressSummary(BaseModel):
    pct_complete: float = Field(ge=0.0, le=100.0)
    weeks_active: int = 0
    last_session_at: datetime | None = None


class GoalContractSummary(BaseModel):
    weekly_hours_committed: float | None = None
    target_role: str | None = None
    expires_at: datetime | None = None


class CapstoneStatus(BaseModel):
    status: Literal["not_started", "in_progress", "submitted", "evaluated"]
    last_updated_at: datetime | None = None


class StudentSnapshot(BaseModel):
    """Pre-computed, cached, per-student summary the Supervisor reads.

    Pass 3b §3.1 calls this load-bearing for performance at 1k
    students: the Supervisor never queries DB tables directly, it
    always reads through this snapshot. 5-minute Redis TTL.
    """

    # Course context
    active_courses: list[CourseRef] = Field(default_factory=list)
    current_focus: ConceptRef | None = None
    progress_summary: ProgressSummary | None = None

    # Mastery and gaps
    strong_concepts: list[ConceptRef] = Field(default_factory=list)
    weak_concepts: list[ConceptRef] = Field(default_factory=list)
    open_misconceptions: list[MisconceptionRef] = Field(default_factory=list)

    # Behavioral signals
    risk_state: Literal["healthy", "at_risk", "critical"] | None = None
    energy_signal: Literal["fresh", "tired", "frustrated"] | None = None
    streak_days: int = 0

    # Goals
    active_goal_contract: GoalContractSummary | None = None
    capstone_status: CapstoneStatus | None = None

    # Preferences (from memory bank, scope=user). Free-form by design;
    # the Supervisor's prompt selects the relevant keys per situation.
    preferences: dict[str, Any] = Field(default_factory=dict)


# ── Awareness window (recent agent activity) ────────────────────────


class AgentActionSummary(BaseModel):
    """A 1-sentence rendering of a recent agent action.

    The `summary` string is critical (Pass 3b §3.1): without it, the
    Supervisor would either get full agent outputs (too expensive in
    tokens) or only metadata (uninformative). memory_curator writes
    this on insert; the agent_actions.summary column landed in 0055.
    """

    agent_name: str
    action_type: str
    occurred_at: datetime
    summary: str
    score: float | None = None
    triggered_followup: bool = False


# ── Conversation thread ─────────────────────────────────────────────


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    occurred_at: datetime
    agent_name: str | None = None  # which specialist produced an assistant turn


# ── Attachments ─────────────────────────────────────────────────────


class AttachmentRef(BaseModel):
    """Reference to a non-text input (code blob, file, JD text, etc.).

    Concrete attachment storage is in app.services.attachment_service;
    the Supervisor only sees a typed reference, not the bytes.
    """

    attachment_id: uuid.UUID
    kind: Literal["code", "text", "file", "jd", "image"]
    filename: str | None = None
    excerpt: str | None = None  # short preview for the Supervisor's reasoning
    size_bytes: int | None = None


# ── Rate limit + entitlement carry-forward ──────────────────────────
#
# RateLimitState is referenced from SupervisorContext; the actual
# entitlement context types live in schemas/entitlement.py. We
# import EntitlementSummary lazily to keep the module graph one-way:
# entitlement.py imports nothing from supervisor.py, supervisor.py
# imports the summary type. (TYPE_CHECKING-style forward-ref keeps
# Pydantic happy without circulars.)


class RateLimitState(BaseModel):
    burst_remaining: int
    burst_window_resets_at: datetime
    hourly_remaining: int
    hourly_window_resets_at: datetime


class EntitlementSummary(BaseModel):
    """Compact summary of one active entitlement, for SupervisorContext.

    The fuller ActiveEntitlement type lives in schemas/entitlement.py
    and is what the orchestrator builds; this is the trimmed version
    the Supervisor actually sees in its prompt.
    """

    course_id: uuid.UUID
    course_slug: str
    tier: Literal["free", "standard", "premium"]
    granted_at: datetime
    expires_at: datetime | None = None


# ── Supervisor input ────────────────────────────────────────────────


class SupervisorContext(BaseModel):
    """Everything the Supervisor sees on a single request.

    Built by AgenticOrchestratorService before the Supervisor LLM
    call; consumed by the Supervisor; portions passed forward into
    constructed_context for the dispatched specialist.
    """

    # Identity
    student_id: uuid.UUID
    request_id: uuid.UUID
    conversation_id: uuid.UUID
    actor_id: uuid.UUID
    actor_role: Literal["student", "admin", "system"]

    # The actual request
    user_message: str
    attachments: list[AttachmentRef] = Field(default_factory=list)
    explicit_agent_request: str | None = None

    # Policy gates (computed before Supervisor runs)
    entitlements: list[EntitlementSummary] = Field(default_factory=list)
    rate_limit_remaining: RateLimitState
    cost_budget_remaining_today_inr: Decimal

    # Student model snapshot
    student_snapshot: StudentSnapshot

    # Conversation thread
    thread_summary: str | None = None
    recent_turns: list[ConversationTurn] = Field(default_factory=list)

    # Recent agent activity (last 10 across all agents in last 7 days)
    recent_agent_actions: list[AgentActionSummary] = Field(default_factory=list)

    # Available capabilities (filtered by entitlement + tier + availability)
    available_agents: list[AgentCapability] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)


# ── Supervisor output ───────────────────────────────────────────────


class ChainStep(BaseModel):
    """One step in a multi-agent chain plan.

    `pass_outputs_from_steps` references prior step numbers (1-based).
    `on_failure` controls how the dispatch layer reacts to a step
    failure; defaults are deliberately conservative (abort_chain).
    """

    step_number: int = Field(ge=1)
    target_agent: str
    constructed_context: dict[str, Any]
    pass_outputs_from_steps: list[int] = Field(default_factory=list)
    on_failure: Literal["abort_chain", "continue", "fallback_to_default"] = "abort_chain"
    timeout_ms: int = 30_000


class RouteDecision(BaseModel):
    """The structured output of every Supervisor invocation.

    The Critic (D5) validates this structurally; the dispatch layer
    executes it deterministically. The Supervisor never invokes
    specialists directly — it returns a decision, the dispatch layer
    runs it. That separation enables unit-testing the Supervisor
    without specialists, and the dispatch layer without an LLM.
    """

    # The decision itself
    action: Literal[
        "dispatch_single",
        "dispatch_chain",
        "decline",
        "escalate",
        "ask_clarification",
    ]

    # If dispatch_single
    target_agent: str | None = None
    constructed_context: dict[str, Any] | None = None

    # If dispatch_chain
    chain_plan: list[ChainStep] | None = None

    # If decline
    decline_reason: (
        Literal[
            "out_of_scope",
            "entitlement_required",
            "rate_limited",
            "cost_exhausted",
            "safety_blocked",
        ]
        | None
    ) = None
    decline_message: str | None = None
    suggested_next_action: str | None = None

    # If escalate
    escalation_reason: str | None = None
    admin_inbox_summary: str | None = None

    # If ask_clarification
    clarification_questions: list[str] | None = None
    expected_clarifications: list[str] | None = None

    # Reasoning + intent metadata (always required)
    reasoning: str = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]
    primary_intent: str
    secondary_intents: list[str] = Field(default_factory=list)


# ── Dispatch result types ───────────────────────────────────────────


class HandoffRequest(BaseModel):
    """A specialist asking the dispatch layer to invoke another agent.

    The dispatch layer does NOT blindly follow handoff requests —
    it re-invokes the Supervisor with the handoff context and the
    Supervisor decides whether to honor it. Prevents loops + cost
    runaway (Pass 3b §5.3).
    """

    target_agent: str
    reason: str
    suggested_context: dict[str, Any] = Field(default_factory=dict)
    handoff_type: Literal["mandatory", "suggested"] = "suggested"


class AgentResult(BaseModel):
    """Result of a single specialist invocation through the dispatch layer."""

    agent_name: str
    output_text: str | None = None
    structured_output: dict[str, Any] | None = None
    output_summary: str | None = None
    blocked: bool = False
    block_reason: str | None = None
    redacted: bool = False
    handoff_request: HandoffRequest | None = None
    duration_ms: int = 0
    cost_inr: Decimal = Decimal("0")


class ChainResult(BaseModel):
    """Result of a multi-step chain dispatch."""

    steps: list[AgentResult] = Field(default_factory=list)
    aborted_at_step: int | None = None  # 1-based; None if completed
    abort_reason: str | None = None
    composed_response: str | None = None
    total_duration_ms: int = 0
    total_cost_inr: Decimal = Decimal("0")
