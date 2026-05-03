"""D9 / Pass 3f §B.2 — tier configuration.

Per-tier limits live in code, not in a database table. Pass 3f §B.2
explicitly chose this:
  - Changes are reviewed via PR (config drift visible in git history)
  - No "the prod tier table got out of sync with staging" mode
  - Tier configs rarely change; making them dynamic adds complexity
    for no benefit
  - Per-student overrides (rare, e.g. comp'd accounts) live in
    course_entitlements.metadata and are explicit

Two tiers ship in v1: 'free' and 'standard'. The migration's CHECK
constraint admits 'premium' so adding the SKU later is a config
change, not a migration. Per Checkpoint 1 sign-off: D9 ships NO
premium config — adding it now would be the wrong moment.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


# Tier name type — matches the migration's CHECK constraint values.
# 'premium' is allowed by the schema but absent from TIER_CONFIGS in v1.
TierName = Literal["free", "standard", "premium"]


class TierConfig(BaseModel):
    """Per-tier policy: cost ceiling, rate limits, agent allow-list.

    `allowed_agents` is either a literal "*" (all agents available
    given other gates) or an explicit set of agent names. Pass 3f §B.2.
    """

    name: str
    # Set of agent names OR the wildcard "*" sentinel string.
    # Pydantic doesn't have a clean "set | Literal[...]" so we model
    # it as set[str] with the convention that {"*"} means wildcard.
    # The check helper `agent_allowed()` below honors that convention.
    allowed_agents: set[str] = Field(default_factory=set)
    daily_cost_ceiling_inr: Decimal
    burst_rate_limit_per_minute: int = Field(ge=1)
    hourly_rate_limit_per_hour: int = Field(ge=1)
    upgrade_path: TierName | None = None

    def agent_allowed(self, agent_name: str) -> bool:
        """True iff this tier's allow-list admits the named agent."""
        return "*" in self.allowed_agents or agent_name in self.allowed_agents


# Per Pass 3f §B.2 — exactly two tiers in v1.
#
# Free tier limits (Pass 3f §C.2): tighter than standard by 10x on
# cost, 3x on burst, 5x on hourly. Tight enough to prevent abuse;
# generous enough for a placement quiz to actually function.
TIER_CONFIGS: dict[TierName, TierConfig] = {
    "free": TierConfig(
        name="free",
        allowed_agents={
            # Pass 3f §B.4: billing_support and supervisor are free-
            # tier accessible. Adding the placement-quiz agents when
            # those flows wire in is a config-only change.
            "billing_support",
            "supervisor",
        },
        daily_cost_ceiling_inr=Decimal("5.00"),
        burst_rate_limit_per_minute=3,
        hourly_rate_limit_per_hour=20,
        upgrade_path="standard",
    ),
    "standard": TierConfig(
        name="standard",
        allowed_agents={"*"},  # all agents per Pass 3a Addendum roster
        daily_cost_ceiling_inr=Decimal("50.00"),
        burst_rate_limit_per_minute=10,
        hourly_rate_limit_per_hour=100,
        upgrade_path=None,
    ),
    # 'premium' is intentionally absent. The schema CHECK constraint
    # admits the value; adding a TIER_CONFIGS entry is the only thing
    # standing between an entitlement row tagged 'premium' and the
    # SKU being live. This deferral is documented per the Checkpoint
    # 1 sign-off discussion.
}


DEFAULT_TIER: TierName = "standard"


def get_tier(name: str) -> TierConfig:
    """Look up a tier config; fall back to DEFAULT_TIER on unknown.

    A row tagged 'premium' (allowed by the CHECK) but with no config
    falls back to 'standard' rather than crashing the request. The
    fallback logs a warning so the operator notices the orphaned tier
    string in production data.
    """
    if name in TIER_CONFIGS:
        return TIER_CONFIGS[name]  # type: ignore[index]
    # Fail-soft: return default tier. This is the correct behavior
    # when 'premium' lands in DB but config hasn't been deployed yet.
    import structlog

    structlog.get_logger().warning(
        "tiers.unknown_tier_fallback",
        requested=name,
        fallback=DEFAULT_TIER,
    )
    return TIER_CONFIGS[DEFAULT_TIER]


# Tier ordering used by capability filtering (Pass 3f §B.3):
# free < standard < premium. A user's tier must meet or exceed an
# agent's minimum_tier for that agent to appear in the
# Supervisor's available_agents list.
_TIER_ORDER: dict[TierName, int] = {
    "free": 0,
    "standard": 1,
    "premium": 2,
}


def tier_meets_minimum(user_tier: TierName, required_tier: TierName) -> bool:
    """True iff `user_tier` >= `required_tier` in the order above.

    Used by the AgentCapability filter when the Supervisor builds
    its prompt's available_agents list — and by the Layer 3 dispatch
    re-check that catches mid-flight tier changes.
    """
    return _TIER_ORDER[user_tier] >= _TIER_ORDER[required_tier]
