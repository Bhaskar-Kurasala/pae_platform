"""D12 CP3 Phase 3 — pin resolve_timeout_seconds behavior.

The resolver derives per-agent dispatch timeout from
AgentCapability.typical_latency_ms with an override path. Replaces the
single hardcoded 30s wrapper that timed out career_coach (Bug 11) and
tailored_resume (Bug 6).

Formula:  max(30, min(60, typical_latency_ms * 3 / 1000))
Override: timeout_override_seconds takes precedence when set.

Tests cover the floor / ceiling / formula center / formula above floor /
override path, plus a sibling check that asserts every shipped D10/D11
agent gets >=30s (no regression for already-shipped surface).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.capability import (
    list_capabilities,
    resolve_timeout_seconds,
)
from app.schemas.supervisor import AgentCapability


def _make_capability(
    *,
    typical_latency_ms: int = 1000,
    override: int | None = None,
    name: str = "test_agent",
) -> AgentCapability:
    """Minimal AgentCapability for resolver tests. Only the fields the
    resolver reads are non-default — everything else takes Pydantic
    defaults so tests don't drift if AgentCapability gains new fields."""
    return AgentCapability(
        name=name,
        description="test",
        typical_latency_ms=typical_latency_ms,
        typical_cost_inr=Decimal("0"),
        timeout_override_seconds=override,
    )


# ── Formula behavior ──────────────────────────────────────────────


class TestResolverFormula:
    def test_floor_holds_at_low_typical_latency(self) -> None:
        """typical=1500 → formula=4.5 → floored to 30."""
        cap = _make_capability(typical_latency_ms=1500)
        assert resolve_timeout_seconds(cap) == 30.0

    def test_floor_at_zero_typical(self) -> None:
        """typical=0 (unset) → floored to 30. Defensive."""
        cap = _make_capability(typical_latency_ms=0)
        assert resolve_timeout_seconds(cap) == 30.0

    def test_ceiling_holds_at_high_typical_latency(self) -> None:
        """typical=30000 → formula=90 → capped to 60."""
        cap = _make_capability(typical_latency_ms=30000)
        assert resolve_timeout_seconds(cap) == 60.0

    def test_formula_at_floor_boundary(self) -> None:
        """typical=10000 → formula=30 — exactly at the floor boundary.
        Both floor and formula yield 30, so result is 30."""
        cap = _make_capability(typical_latency_ms=10000)
        assert resolve_timeout_seconds(cap) == 30.0

    def test_formula_above_floor(self) -> None:
        """typical=12000 → formula=36 — above floor, below ceiling.
        career_coach's actual value; this is where Bug 11 was hurting."""
        cap = _make_capability(typical_latency_ms=12000)
        assert resolve_timeout_seconds(cap) == 36.0

    def test_formula_at_ceiling_boundary(self) -> None:
        """typical=20000 → formula=60 — exactly at the ceiling boundary."""
        cap = _make_capability(typical_latency_ms=20000)
        assert resolve_timeout_seconds(cap) == 60.0


# ── Override path ─────────────────────────────────────────────────


class TestResolverOverride:
    def test_override_takes_precedence_over_formula(self) -> None:
        """override=120 → 120, ignoring whatever typical_latency_ms says."""
        cap = _make_capability(typical_latency_ms=10000, override=120)
        assert resolve_timeout_seconds(cap) == 120.0

    def test_override_can_be_below_floor(self) -> None:
        """Override is the escape hatch; if a future agent needs <30s
        explicitly (e.g., a fast-Haiku safety check), the override
        bypasses the floor too. Verifies the resolver doesn't silently
        re-floor an explicit override."""
        cap = _make_capability(typical_latency_ms=10000, override=10)
        assert resolve_timeout_seconds(cap) == 10.0

    def test_override_can_be_above_ceiling(self) -> None:
        """tailored_resume's actual override. Multi-LLM pipeline
        structurally exceeds the 60s formula ceiling."""
        cap = _make_capability(typical_latency_ms=10000, override=120)
        assert resolve_timeout_seconds(cap) == 120.0

    def test_override_none_falls_through_to_formula(self) -> None:
        """Explicit None means 'use the formula' — same as omitting it."""
        cap = _make_capability(typical_latency_ms=12000, override=None)
        assert resolve_timeout_seconds(cap) == 36.0


# ── Sibling check: D10 + D11 + D12 agents in the live registry ────


class TestNoRegressionForShippedAgents:
    """Pins the 'no regression for already-shipped agents' invariant.

    Stop-condition from D12 CP3 Phase 3 stage 3.3.d: any shipped agent
    getting <30s under the new resolver is a regression. Fail the test
    rather than silently shipping a tighter budget than what those
    agents already operate under successfully.
    """

    def test_every_shipped_agent_gets_at_least_30_seconds(self) -> None:
        shipped = [c for c in list_capabilities() if c.available_now]
        # We expect at least the D8/D10/D11/D12 surface to be present.
        assert len(shipped) >= 7, (
            f"Expected ≥7 shipped capabilities; got {len(shipped)}. "
            "Has the registry shrunk unexpectedly?"
        )

        below_floor = [
            (cap.name, resolve_timeout_seconds(cap))
            for cap in shipped
            if resolve_timeout_seconds(cap) < 30.0
        ]
        assert below_floor == [], (
            f"Regression: shipped agents getting <30s timeout: {below_floor}. "
            "Bumping the floor or adding a per-agent override is required "
            "before this lands."
        )

    def test_tailored_resume_gets_120_second_override(self) -> None:
        """Bug 6 closure pin: tailored_resume's override is what unblocks
        its multi-LLM pipeline from the prior 30s timeout."""
        from app.agents.capability import get_capability

        cap = get_capability("tailored_resume")
        assert cap is not None
        assert resolve_timeout_seconds(cap) == 120.0

    def test_career_coach_gets_above_30_seconds(self) -> None:
        """Bug 11 closure pin: career_coach gets 150s override under MiniMax.
        Measured P50 was 45s at 1280 output tokens; after Bug-16 fix
        (max_tokens 2048→8192) MiniMax produces ~3-4x more tokens, scaling
        generation time proportionally. 150s absorbs the new envelope."""
        from app.agents.capability import get_capability

        cap = get_capability("career_coach")
        assert cap is not None
        assert resolve_timeout_seconds(cap) > 30.0
        assert resolve_timeout_seconds(cap) == 150.0

    @pytest.mark.parametrize(
        "agent_name,expected_timeout",
        [
            # D8 / D10 / D11 — already-shipped agents that previously ran
            # under the 30s flat default. Floor must keep them at ≥30s.
            # Phase 4 calibration adjusted typical_latency_ms values up
            # to reflect MiniMax-observed P50s; floor still anchors them
            # at 30s where formula would otherwise drop them.
            ("supervisor", 30.0),       # typical=9000 → formula=27 → floor=30
            ("learning_coach", 30.0),
            ("billing_support", 30.0),
            ("senior_engineer", 30.0),
            # D12 — the four agents this Phase is closing bugs for.
            ("study_planner", 30.0),    # typical=9000 → formula=27 → floor=30
            ("resume_reviewer", 90.0),  # override=90 (Phase 4 ricochet: max_tokens bump)
            ("career_coach", 150.0),    # override=150 (Phase 4 ricochet: max_tokens bump scaled gen time)
            ("tailored_resume", 120.0), # override=120
        ],
    )
    def test_per_agent_timeout_matches_phase3_inventory(
        self, agent_name: str, expected_timeout: float
    ) -> None:
        """Pins the timeout values surfaced in the Phase 3 inventory
        table. Catches drift if someone changes typical_latency_ms in
        capability.py without realizing it shifts the dispatch budget."""
        from app.agents.capability import get_capability

        cap = get_capability(agent_name)
        assert cap is not None, f"Capability not found: {agent_name}"
        assert resolve_timeout_seconds(cap) == expected_timeout
