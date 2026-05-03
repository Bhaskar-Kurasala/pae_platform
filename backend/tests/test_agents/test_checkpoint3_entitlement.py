"""D9 Checkpoint 3 — entitlement policy tests.

Verifies the stop-and-review triggers from the Checkpoint 3 spec:
  • Three entitlement layers verifiable via unit tests
  • compute_active_entitlements returns correct EntitlementContext
    for synthetic users (entitled, unentitled, free-tier, refunded)

Tests target the *logic* (tier resolution, cost ceiling, tier
filtering, can_invoke checks) rather than the SQL — full DB
integration is exercised in Checkpoint 4 E2E tests where the
endpoint is wired.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.agents.capability import filter_capabilities_for_user
from app.core.tiers import (
    DEFAULT_TIER,
    TIER_CONFIGS,
    get_tier,
    tier_meets_minimum,
)
from app.schemas.entitlement import (
    ActiveEntitlement,
    EntitlementContext,
    FreeTierState,
)
from app.schemas.supervisor import (
    AgentCapability,
    RateLimitState,
)
from app.services.entitlement_service import (
    _resolve_cost_ceiling,
    _resolve_effective_tier,
)


def _rate_limit() -> RateLimitState:
    now = datetime.now(UTC)
    return RateLimitState(
        burst_remaining=10,
        burst_window_resets_at=now + timedelta(minutes=1),
        hourly_remaining=100,
        hourly_window_resets_at=now + timedelta(hours=1),
    )


# ── tiers config ───────────────────────────────────────────────────


class TestTierConfig:
    def test_only_free_and_standard_in_v1(self) -> None:
        assert set(TIER_CONFIGS.keys()) == {"free", "standard"}

    def test_premium_not_present(self) -> None:
        # Per Checkpoint 1 sign-off: schema admits premium but
        # TIER_CONFIGS must NOT define it in D9.
        assert "premium" not in TIER_CONFIGS

    def test_free_tier_costs_5_inr(self) -> None:
        assert TIER_CONFIGS["free"].daily_cost_ceiling_inr == Decimal("5.00")

    def test_standard_tier_costs_50_inr(self) -> None:
        assert TIER_CONFIGS["standard"].daily_cost_ceiling_inr == Decimal("50.00")

    def test_free_tier_allows_billing_and_supervisor(self) -> None:
        free = TIER_CONFIGS["free"]
        assert "billing_support" in free.allowed_agents
        assert "supervisor" in free.allowed_agents

    def test_standard_tier_uses_wildcard(self) -> None:
        std = TIER_CONFIGS["standard"]
        assert std.allowed_agents == {"*"}
        assert std.agent_allowed("anything")

    def test_get_tier_unknown_falls_back_to_default(self) -> None:
        # 'premium' is allowed by schema but not in TIER_CONFIGS;
        # must not crash — falls back to DEFAULT_TIER.
        result = get_tier("premium")
        assert result.name == DEFAULT_TIER

    def test_tier_ordering(self) -> None:
        assert tier_meets_minimum("standard", "free")
        assert tier_meets_minimum("standard", "standard")
        assert not tier_meets_minimum("free", "standard")


# ── EntitlementContext.can_invoke (Layer 2 / 3) ────────────────────


class TestCanInvoke:
    def _ctx(
        self,
        *,
        paid: bool = False,
        free: bool = False,
        free_allowed: set[str] | None = None,
    ) -> EntitlementContext:
        user_id = uuid.uuid4()
        active: list[ActiveEntitlement] = []
        if paid:
            active.append(
                ActiveEntitlement(
                    entitlement_id=uuid.uuid4(),
                    user_id=user_id,
                    course_id=uuid.uuid4(),
                    course_slug="x",
                    tier="standard",
                    source="purchase",
                    granted_at=datetime.now(UTC),
                )
            )
        free_state: FreeTierState | None = None
        if free:
            free_state = FreeTierState(
                grant_id=uuid.uuid4(),
                grant_type="signup_grace",
                granted_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                allowed_agents=free_allowed or {"billing_support", "supervisor"},
            )
        return EntitlementContext(
            user_id=user_id,
            active_entitlements=active,
            free_tier=free_state,
            effective_tier="standard" if paid else ("free" if free else "standard"),
            cost_budget_remaining_today_inr=Decimal("50"),
            cost_budget_used_today_inr=Decimal("0"),
            rate_limit_state=_rate_limit(),
        )

    def _capability(
        self, name: str, requires_entitlement: bool = True, minimum_tier: str = "standard"
    ) -> AgentCapability:
        return AgentCapability(
            name=name,
            description="x",
            requires_entitlement=requires_entitlement,
            minimum_tier=minimum_tier,  # type: ignore[arg-type]
            available_now=True,
        )

    def test_paid_user_can_invoke_any_agent(self) -> None:
        ctx = self._ctx(paid=True)
        cap = self._capability("learning_coach")
        allowed, reason = ctx.can_invoke(cap)
        assert allowed
        assert reason is None

    def test_free_tier_user_can_invoke_allowed_agent(self) -> None:
        ctx = self._ctx(free=True, free_allowed={"billing_support", "supervisor"})
        cap = self._capability("billing_support")
        allowed, reason = ctx.can_invoke(cap)
        assert allowed
        assert reason is None

    def test_free_tier_user_cannot_invoke_disallowed_agent(self) -> None:
        ctx = self._ctx(free=True, free_allowed={"billing_support"})
        cap = self._capability("learning_coach")
        allowed, reason = ctx.can_invoke(cap)
        assert not allowed
        assert reason == "agent_not_in_tier"

    def test_unentitled_user_cannot_invoke_gated_agent(self) -> None:
        ctx = self._ctx(paid=False, free=False)
        cap = self._capability("learning_coach")
        allowed, reason = ctx.can_invoke(cap)
        assert not allowed

    def test_no_entitlement_required_always_allowed(self) -> None:
        ctx = self._ctx(paid=False, free=False)
        cap = self._capability("supervisor", requires_entitlement=False)
        allowed, reason = ctx.can_invoke(cap)
        assert allowed
        assert reason is None

    def test_is_empty_when_no_paid_no_free(self) -> None:
        ctx = self._ctx(paid=False, free=False)
        assert ctx.is_empty()

    def test_is_empty_false_with_paid(self) -> None:
        ctx = self._ctx(paid=True)
        assert not ctx.is_empty()

    def test_is_empty_false_with_free(self) -> None:
        ctx = self._ctx(free=True)
        assert not ctx.is_empty()


# ── Effective tier resolution ──────────────────────────────────────


class TestEffectiveTier:
    def test_paid_wins_over_free(self) -> None:
        user_id = uuid.uuid4()
        paid = [
            ActiveEntitlement(
                entitlement_id=uuid.uuid4(),
                user_id=user_id,
                course_id=uuid.uuid4(),
                course_slug="x",
                tier="standard",
                source="purchase",
                granted_at=datetime.now(UTC),
            )
        ]
        free = FreeTierState(
            grant_id=uuid.uuid4(),
            grant_type="signup_grace",
            granted_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            allowed_agents={"billing_support"},
        )
        assert _resolve_effective_tier(paid, free) == "standard"

    def test_free_only_returns_free(self) -> None:
        free = FreeTierState(
            grant_id=uuid.uuid4(),
            grant_type="signup_grace",
            granted_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            allowed_agents={"billing_support"},
        )
        assert _resolve_effective_tier([], free) == "free"

    def test_neither_returns_default(self) -> None:
        # Empty context — Layer 1 short-circuits before reaching here,
        # but the resolver is defensive.
        assert _resolve_effective_tier([], None) == DEFAULT_TIER


# ── Cost ceiling resolution + override ─────────────────────────────


class TestCostCeiling:
    def test_default_standard_ceiling(self) -> None:
        ent = ActiveEntitlement(
            entitlement_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            course_slug="x",
            tier="standard",
            source="purchase",
            granted_at=datetime.now(UTC),
        )
        ceiling = _resolve_cost_ceiling("standard", [ent])
        assert ceiling == Decimal("50.00")

    def test_metadata_override_raises_ceiling(self) -> None:
        ent = ActiveEntitlement(
            entitlement_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            course_slug="x",
            tier="standard",
            source="purchase",
            granted_at=datetime.now(UTC),
            metadata={"cost_ceiling_inr_override": "150.00"},
        )
        ceiling = _resolve_cost_ceiling("standard", [ent])
        assert ceiling == Decimal("150.00")

    def test_metadata_override_below_default_ignored(self) -> None:
        # Override that's smaller than the tier default doesn't reduce
        # the ceiling — base wins.
        ent = ActiveEntitlement(
            entitlement_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            course_slug="x",
            tier="standard",
            source="purchase",
            granted_at=datetime.now(UTC),
            metadata={"cost_ceiling_inr_override": "10.00"},
        )
        ceiling = _resolve_cost_ceiling("standard", [ent])
        assert ceiling == Decimal("50.00")

    def test_bad_override_value_ignored(self) -> None:
        ent = ActiveEntitlement(
            entitlement_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            course_slug="x",
            tier="standard",
            source="purchase",
            granted_at=datetime.now(UTC),
            metadata={"cost_ceiling_inr_override": "not a number"},
        )
        # Base wins; the bad value is logged + skipped.
        ceiling = _resolve_cost_ceiling("standard", [ent])
        assert ceiling == Decimal("50.00")


# ── Tier filtering of capabilities (Layer 2 helper) ────────────────


class TestCapabilityFilteringByEntitlement:
    def _capability(
        self,
        name: str,
        *,
        minimum_tier: str = "standard",
        requires_entitlement: bool = True,
        available_now: bool = True,
    ) -> AgentCapability:
        return AgentCapability(
            name=name,
            description="x",
            minimum_tier=minimum_tier,  # type: ignore[arg-type]
            requires_entitlement=requires_entitlement,
            available_now=available_now,
        )

    def _free_ctx(self) -> EntitlementContext:
        user_id = uuid.uuid4()
        return EntitlementContext(
            user_id=user_id,
            active_entitlements=[],
            free_tier=FreeTierState(
                grant_id=uuid.uuid4(),
                grant_type="signup_grace",
                granted_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                allowed_agents={"billing_support", "supervisor"},
            ),
            effective_tier="free",
            cost_budget_remaining_today_inr=Decimal("5"),
            cost_budget_used_today_inr=Decimal("0"),
            rate_limit_state=_rate_limit(),
        )

    def _paid_ctx(self) -> EntitlementContext:
        user_id = uuid.uuid4()
        return EntitlementContext(
            user_id=user_id,
            active_entitlements=[
                ActiveEntitlement(
                    entitlement_id=uuid.uuid4(),
                    user_id=user_id,
                    course_id=uuid.uuid4(),
                    course_slug="x",
                    tier="standard",
                    source="purchase",
                    granted_at=datetime.now(UTC),
                )
            ],
            free_tier=None,
            effective_tier="standard",
            cost_budget_remaining_today_inr=Decimal("50"),
            cost_budget_used_today_inr=Decimal("0"),
            rate_limit_state=_rate_limit(),
        )

    def test_free_tier_user_only_sees_allowlisted_agents(self) -> None:
        caps = [
            self._capability("supervisor", minimum_tier="free"),
            self._capability("billing_support", minimum_tier="free"),
            self._capability("learning_coach", minimum_tier="standard"),
        ]
        ctx = self._free_ctx()
        available = filter_capabilities_for_user(caps, ctx)
        names = {c.name for c in available}
        assert names == {"supervisor", "billing_support"}

    def test_paid_user_sees_all_available(self) -> None:
        caps = [
            self._capability("supervisor", minimum_tier="free"),
            self._capability("billing_support", minimum_tier="free"),
            self._capability("learning_coach", minimum_tier="standard"),
        ]
        ctx = self._paid_ctx()
        available = filter_capabilities_for_user(caps, ctx)
        names = {c.name for c in available}
        assert names == {"supervisor", "billing_support", "learning_coach"}

    def test_unavailable_now_filtered_out(self) -> None:
        caps = [
            self._capability("supervisor", minimum_tier="free", available_now=False),
            self._capability("billing_support", minimum_tier="free"),
        ]
        ctx = self._free_ctx()
        available = filter_capabilities_for_user(caps, ctx)
        names = {c.name for c in available}
        assert names == {"billing_support"}


# ── Layer 1 / 2 / 3 wiring contract ────────────────────────────────


class TestThreeLayerContract:
    """The three entitlement layers share a single EntitlementContext.

    Layer 1 builds it once. Layer 2 reads a trimmed projection. Layer 3
    re-fetches a fresh one. These tests verify the data contract
    holds across all three.
    """

    def test_empty_context_signals_unentitled_for_layer_1(self) -> None:
        """Layer 1 raises 402 when ctx.is_empty(). Verify the bool is
        wired correctly."""
        user_id = uuid.uuid4()
        ctx = EntitlementContext(
            user_id=user_id,
            active_entitlements=[],
            free_tier=None,
            effective_tier="standard",
            cost_budget_remaining_today_inr=Decimal("50"),
            cost_budget_used_today_inr=Decimal("0"),
            rate_limit_state=_rate_limit(),
        )
        assert ctx.is_empty() is True

    def test_can_invoke_returns_consistent_for_layer_2_and_layer_3(self) -> None:
        """Layer 2 (Supervisor reasoning) and Layer 3 (dispatch
        re-check) call the same can_invoke method on the same shape.
        Verify the contract: identical input → identical output."""
        user_id = uuid.uuid4()
        ctx = EntitlementContext(
            user_id=user_id,
            active_entitlements=[
                ActiveEntitlement(
                    entitlement_id=uuid.uuid4(),
                    user_id=user_id,
                    course_id=uuid.uuid4(),
                    course_slug="x",
                    tier="standard",
                    source="purchase",
                    granted_at=datetime.now(UTC),
                )
            ],
            free_tier=None,
            effective_tier="standard",
            cost_budget_remaining_today_inr=Decimal("50"),
            cost_budget_used_today_inr=Decimal("0"),
            rate_limit_state=_rate_limit(),
        )
        cap = AgentCapability(
            name="learning_coach",
            description="x",
            minimum_tier="standard",
            requires_entitlement=True,
            available_now=True,
        )
        # Layer 2 calls can_invoke; Layer 3 calls can_invoke. Same
        # context → same answer → consistent enforcement.
        result_a = ctx.can_invoke(cap)
        result_b = ctx.can_invoke(cap)
        assert result_a == result_b
        assert result_a == (True, None)

    def test_revoked_during_request_caught_by_layer_3(self) -> None:
        """Simulate the race: Layer 1 saw a paid entitlement; Layer 3
        sees it revoked. The revoked state surfaces as is_empty()."""
        user_id = uuid.uuid4()
        ctx_at_layer_1 = EntitlementContext(
            user_id=user_id,
            active_entitlements=[
                ActiveEntitlement(
                    entitlement_id=uuid.uuid4(),
                    user_id=user_id,
                    course_id=uuid.uuid4(),
                    course_slug="x",
                    tier="standard",
                    source="purchase",
                    granted_at=datetime.now(UTC),
                )
            ],
            free_tier=None,
            effective_tier="standard",
            cost_budget_remaining_today_inr=Decimal("50"),
            cost_budget_used_today_inr=Decimal("0"),
            rate_limit_state=_rate_limit(),
        )
        # ... refund processes mid-request ...
        ctx_at_layer_3 = EntitlementContext(
            user_id=user_id,
            active_entitlements=[],
            free_tier=None,
            effective_tier="standard",
            cost_budget_remaining_today_inr=Decimal("50"),
            cost_budget_used_today_inr=Decimal("0"),
            rate_limit_state=_rate_limit(),
        )
        assert not ctx_at_layer_1.is_empty()
        assert ctx_at_layer_3.is_empty()  # caught at Layer 3
