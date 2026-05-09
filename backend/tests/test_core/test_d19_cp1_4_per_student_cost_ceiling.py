"""D19.2 / CP1.4 — per-student daily cost ceiling tests.

Three discipline tests covering the override-resolution helper and
two integration-shape tests covering the orchestrator-side
enforcement (block + cohort-event recording).

Per the closure-time test verification discipline (D19.1 CP5
canonical sub-rule): scope-matching applies. CP1.4 changes
substrate behaviour (new schema column + enforcement at
dispatch entry) so the closure also runs the full Phase B
suite.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.entitlement_service import _resolve_cost_ceiling


# ---------------------------------------------------------------------------
# Unit: _resolve_cost_ceiling override resolution
# ---------------------------------------------------------------------------


def test_user_override_wins_over_tier_default() -> None:
    """D19.2 D-B: per-user override is the binding constraint.
    Wins over tier default when set."""
    # Tighten this user to ₹10/day regardless of free-tier default
    # (typically higher).
    ceiling = _resolve_cost_ceiling(
        tier="free",
        paid=[],
        user_override=Decimal("10.00"),
    )
    assert ceiling == Decimal("10.00")


def test_user_override_wins_over_entitlement_metadata_override() -> None:
    """A flagged user can't bypass tightening by buying a course
    with a generous metadata override. D-B requires user-level
    override to be the binding constraint."""
    # Construct a fake paid entitlement carrying a generous metadata
    # override (₹500). User-level override (₹10) must still win.
    from datetime import UTC, datetime
    import uuid

    from app.schemas.entitlement import ActiveEntitlement

    paid = [
        ActiveEntitlement(
            entitlement_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            course_slug="generous-course",
            source="purchase",
            granted_at=datetime.now(UTC),
            expires_at=None,
            tier="standard",
            metadata={"cost_ceiling_inr_override": "500"},
        )
    ]
    ceiling = _resolve_cost_ceiling(
        tier="standard", paid=paid, user_override=Decimal("10.00")
    )
    assert ceiling == Decimal("10.00"), (
        "User override must beat entitlement metadata override per D19.2 D-B"
    )


def test_no_user_override_falls_through_to_existing_resolution() -> None:
    """When user_override is None, the existing (Pass 3f §H.3)
    resolution chain applies — entitlement metadata override or
    tier default. CP1.4 must not regress the prior behaviour."""
    # No user override, no entitlement override → tier default
    free_default = _resolve_cost_ceiling(
        tier="free", paid=[], user_override=None
    )
    assert free_default > Decimal("0"), (
        "Free tier should have a non-zero default ceiling"
    )

    # No user override, with entitlement metadata override → larger of
    # base vs override (Pass 3f §H.3 contract preserved)
    from datetime import UTC, datetime
    import uuid

    from app.schemas.entitlement import ActiveEntitlement

    paid = [
        ActiveEntitlement(
            entitlement_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            course_slug="standard-course",
            source="purchase",
            granted_at=datetime.now(UTC),
            expires_at=None,
            tier="standard",
            metadata={"cost_ceiling_inr_override": "999"},
        )
    ]
    ceiling = _resolve_cost_ceiling(
        tier="standard", paid=paid, user_override=None
    )
    assert ceiling >= Decimal("999"), (
        "Entitlement metadata override must apply when user_override is None"
    )


# ---------------------------------------------------------------------------
# Unit: ceiling override of zero behaves as "block all"
# ---------------------------------------------------------------------------


def test_user_override_of_zero_blocks_all_invocations() -> None:
    """An admin tightening a flagged user to ₹0/day produces
    cost_remaining = 0 - cost_used; orchestrator's <=0 check fires
    immediately. Verifies the substrate handles edge values."""
    ceiling = _resolve_cost_ceiling(
        tier="free", paid=[], user_override=Decimal("0.00")
    )
    assert ceiling == Decimal("0.00")


# ---------------------------------------------------------------------------
# Substrate boundary: orchestrator enforcement smoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_blocks_when_cost_remaining_zero() -> None:
    """The orchestrator short-circuits with a graceful-decline
    OrchestratorResult when EntitlementContext.cost_budget_remaining
    is <= 0. Substrate-functional smoke; doesn't exercise the full
    LLM path.
    """
    import uuid
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from app.schemas.entitlement import EntitlementContext, RateLimitState
    from app.services.agentic_orchestrator import (
        AgenticOrchestratorService,
        OrchestratorResult,
    )

    # Build an EntitlementContext with cost_remaining at exactly 0 and
    # a non-empty active_entitlements list so the prior is_empty()
    # check doesn't short-circuit before the cost check.
    user_id = uuid.uuid4()
    rate_state = RateLimitState(
        burst_remaining=10,
        burst_window_resets_at=datetime.now(UTC),
        hourly_remaining=100,
        hourly_window_resets_at=datetime.now(UTC),
    )
    from app.schemas.entitlement import ActiveEntitlement

    ent_ctx = EntitlementContext(
        user_id=user_id,
        active_entitlements=[
            ActiveEntitlement(
                entitlement_id=uuid.uuid4(),
                user_id=user_id,
                course_id=uuid.uuid4(),
                course_slug="any-course",
                source="purchase",
                granted_at=datetime.now(UTC),
                expires_at=None,
                tier="standard",
                metadata={},
            )
        ],
        free_tier=None,
        effective_tier="standard",
        cost_budget_remaining_today_inr=Decimal("0"),
        cost_budget_used_today_inr=Decimal("100"),
        rate_limit_state=rate_state,
    )

    svc = AgenticOrchestratorService(supervisor=AsyncMock())
    # Stub the cohort-event recording so the test doesn't need a DB.
    svc._record_ceiling_hit = AsyncMock()  # type: ignore[method-assign]

    result = await svc.process_request(
        db=AsyncMock(),
        flow="default",
        student_id=user_id,
        actor_id=user_id,
        actor_role="student",
        user_message="hi",
        attachments=None,
        conversation_id=None,
        entitlement_ctx=ent_ctx,
    )

    assert isinstance(result, OrchestratorResult)
    assert result.blocked is True
    assert result.block_reason == "daily_cost_ceiling_hit"
    assert "today's usage limit" in result.response_text
    assert result.target_agent is None
    # Cohort event recording was attempted (best-effort).
    svc._record_ceiling_hit.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrator_blocks_when_cost_remaining_negative() -> None:
    """Negative remaining (mid-flight invocation pushed user over
    ceiling) also blocks subsequent invocations. Defense in depth."""
    import uuid
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from app.schemas.entitlement import (
        ActiveEntitlement,
        EntitlementContext,
        RateLimitState,
    )
    from app.services.agentic_orchestrator import (
        AgenticOrchestratorService,
        OrchestratorResult,
    )

    user_id = uuid.uuid4()
    rate_state = RateLimitState(
        burst_remaining=10,
        burst_window_resets_at=datetime.now(UTC),
        hourly_remaining=100,
        hourly_window_resets_at=datetime.now(UTC),
    )
    ent_ctx = EntitlementContext(
        user_id=user_id,
        active_entitlements=[
            ActiveEntitlement(
                entitlement_id=uuid.uuid4(),
                user_id=user_id,
                course_id=uuid.uuid4(),
                course_slug="any-course",
                source="purchase",
                granted_at=datetime.now(UTC),
                expires_at=None,
                tier="standard",
                metadata={},
            )
        ],
        free_tier=None,
        effective_tier="standard",
        cost_budget_remaining_today_inr=Decimal("-2.50"),
        cost_budget_used_today_inr=Decimal("102.50"),
        rate_limit_state=rate_state,
    )

    svc = AgenticOrchestratorService(supervisor=AsyncMock())
    svc._record_ceiling_hit = AsyncMock()  # type: ignore[method-assign]

    result = await svc.process_request(
        db=AsyncMock(),
        flow="default",
        student_id=user_id,
        actor_id=user_id,
        actor_role="student",
        user_message="hi",
        attachments=None,
        conversation_id=None,
        entitlement_ctx=ent_ctx,
    )
    assert isinstance(result, OrchestratorResult)
    assert result.blocked is True
    assert result.block_reason == "daily_cost_ceiling_hit"
