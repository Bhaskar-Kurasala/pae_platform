"""D9 / Pass 3f — entitlement context schemas.

The structured representation of "what this user can access right
now." Built by entitlement_service.compute_active_entitlements at
the start of every agentic request; consumed by all three
enforcement layers:

  Layer 1 — require_active_entitlement dependency (route gate)
  Layer 2 — Supervisor's reasoning (filtered AgentCapability list)
  Layer 3 — dispatch-time fresh re-check (race-condition catch)

The single shared data structure keeps the three layers in sync.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.supervisor import AgentCapability, RateLimitState


# ── Active entitlement (full form) ──────────────────────────────────


class ActiveEntitlement(BaseModel):
    """One row in course_entitlements, represented at API boundary.

    Distinct from EntitlementSummary (in supervisor.py) which is the
    trimmed version the Supervisor's prompt sees. ActiveEntitlement
    is the version the orchestrator and dispatch layer reason over.
    """

    entitlement_id: uuid.UUID
    user_id: uuid.UUID
    course_id: uuid.UUID
    course_slug: str
    tier: Literal["free", "standard", "premium"]
    source: str  # 'order' | 'comp' | 'promotional' | 'bundle' | etc.
    granted_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    # metadata.granted_via and metadata.cost_ceiling_inr_override (see
    # Pass 3f §F.3 / §H.3) are read by the orchestrator. Free-form so
    # we can add more override knobs without a schema change.
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Free-tier state ─────────────────────────────────────────────────


FreeTierGrantType = Literal[
    "signup_grace",
    "placement_quiz_session",
    "demo_chat",
]


class FreeTierState(BaseModel):
    """Active free-tier grant for a user.

    Only one type is active at a time per Pass 3f §C.4 ("one active
    grant per user"). The orchestrator picks the longest-lived active
    grant when multiple exist (defensive — shouldn't happen in
    practice given the per-type uniqueness rules).
    """

    grant_id: uuid.UUID
    grant_type: FreeTierGrantType
    granted_at: datetime
    expires_at: datetime
    # `allowed_agents` is computed from TIER_CONFIGS["free"].allowed_agents
    # at materialization time so the consumer doesn't import core.tiers
    # to figure out what's allowed. Stable for the lifetime of the
    # FreeTierState instance.
    allowed_agents: set[str]


# ── The headline EntitlementContext ─────────────────────────────────


class EntitlementContext(BaseModel):
    """Shared between Layer 1, Layer 2, and Layer 3.

    `is_empty()` and `can_invoke()` are the methods the layers call.
    All three layers compute against the same instance: Layer 1
    builds it once, attaches to request state; Layer 2 reads from
    SupervisorContext.entitlements (a trimmed projection); Layer 3
    re-fetches a fresh instance to catch races.
    """

    user_id: uuid.UUID
    active_entitlements: list[ActiveEntitlement] = Field(default_factory=list)
    free_tier: FreeTierState | None = None
    effective_tier: Literal["free", "standard", "premium"]
    cost_budget_remaining_today_inr: Decimal
    cost_budget_used_today_inr: Decimal
    rate_limit_state: RateLimitState

    def is_empty(self) -> bool:
        """True iff the user has no paid entitlements AND no free grant.

        Used by Layer 1 to decide between 200/402. The Supervisor
        sees only the *post*-empty case (it's never invoked when this
        is True) — Layer 1 short-circuits with 402.
        """
        return not self.active_entitlements and self.free_tier is None

    def can_invoke(
        self, agent_capability: AgentCapability
    ) -> tuple[bool, str | None]:
        """Check whether this user may invoke a specific agent.

        Used by Layer 2 (during Supervisor reasoning, via the filtered
        capability list) and Layer 3 (dispatch-time fresh re-check).

        Returns (allowed, reason_if_denied).

        The order of checks matters:
          1. Agent doesn't require entitlement → always allowed
             (e.g. supervisor itself, billing_support)
          2. Paid entitlements present → allowed regardless of tier
             constraint (paid > free)
          3. Free-tier present + agent is on free-tier allow-list →
             allowed
          4. Anything else → denied with 'agent_not_in_tier'
        """
        if not agent_capability.requires_entitlement:
            return (True, None)
        if self.active_entitlements:
            return (True, None)
        if (
            self.free_tier is not None
            and agent_capability.name in self.free_tier.allowed_agents
        ):
            return (True, None)
        return (False, "agent_not_in_tier")
