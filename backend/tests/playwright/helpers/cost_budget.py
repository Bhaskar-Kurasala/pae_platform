"""D18 Phase A CP5 — LLM cost budget tracking.

`TestBudgetTracker` accumulates LLM cost across a pytest run and
enforces a ceiling. Per-test attribution comes from
agent_invocation_log; the tracker queries the table for rows whose
`created_at` falls inside a per-test timestamp window.

CP4 pre-flight verified: agent_invocation_log.cost_inr is populated
unconditionally on every HTTP agent path (not gated by test mode).
The column is `double precision`, default 0; rows tie back to
user_id, source, source_id, sub_agent, model.

Per-test attribution caveat:
  * Timestamp-window attribution assumes tests run sequentially. If
    a future CP6 enables parallel test workers, the window shape
    won't be reliable — concurrent tests will see each other's rows
    inside their own windows. Documented at the top of
    docs/followups/cost-budget-attribution-parallel-runs.md (would
    register if/when parallel runs land).
  * For now, sequential pytest execution is the documented mode and
    the attribution is sound. A future CP can swap to source_id-
    based attribution if parallel runs are needed.

Pytest hook integration is in playwright/conftest.py — the tracker
is instantiated session-scope, hooks query it on setup/teardown.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession


class BudgetExceeded(RuntimeError):
    """Raised when cumulative test cost crosses the configured ceiling."""


# Default budget for D18 Phase A: ₹2.00 ceiling per the founder's
# CP5 cost ceiling. Override via env var if a CP wants headroom for
# real-LLM verification.
DEFAULT_BUDGET_INR: float = float(os.environ.get("PLAYWRIGHT_BUDGET_INR", "2.00"))


@dataclass
class TestBudgetTracker:
    """Accumulate LLM cost across the test session and enforce a ceiling.

    Lifecycle:
        tracker = TestBudgetTracker(budget_inr=2.00)
        # Per test:
        start = datetime.now(UTC)
        # ... test runs ...
        cost = await tracker.query_test_cost(db_session, since=start)
        await tracker.record_test_cost(test_name, cost)
        # raises BudgetExceeded if cumulative > budget

    `record_test_cost` is async only because callers tend to be async;
    no actual await happens inside. Kept async for shape consistency.
    """

    budget: float = DEFAULT_BUDGET_INR
    cumulative: float = 0.0
    per_test_cost: dict[str, float] = field(default_factory=dict)

    async def record_test_cost(self, test_name: str, cost_inr: float) -> None:
        """Add cost to cumulative; raise if budget exceeded.

        Recorded even on excess so the post-mortem report shows
        which test pushed cumulative over the ceiling.
        """
        self.cumulative += cost_inr
        self.per_test_cost[test_name] = cost_inr
        if self.cumulative > self.budget:
            raise BudgetExceeded(
                f"Cumulative {self.cumulative:.4f} > budget "
                f"{self.budget:.4f} after test {test_name!r} "
                f"(this test added {cost_inr:.4f})"
            )

    async def query_test_cost(
        self,
        db_session: AsyncSession,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> float:
        """SUM(cost_inr) on agent_invocation_log within [since, until].

        Default `until` is now(); tests typically pass `since=start`
        captured before the test runs.
        """
        end = until or datetime.now(UTC)
        result = await db_session.execute(
            sql_text(
                """
                SELECT COALESCE(SUM(cost_inr), 0.0)::float
                FROM agent_invocation_log
                WHERE created_at >= :since
                  AND created_at <= :end
                """
            ),
            {"since": since, "end": end},
        )
        return float(result.scalar_one())

    def remaining(self) -> float:
        """Remaining budget headroom; negative if over."""
        return self.budget - self.cumulative

    def report(self) -> str:
        """Compact post-run report for display in pytest summary."""
        top = sorted(self.per_test_cost.items(), key=lambda kv: kv[1], reverse=True)[:5]
        lines = [
            f"Total: ₹{self.cumulative:.4f} / ₹{self.budget:.4f} "
            f"({len(self.per_test_cost)} tests)",
        ]
        if top:
            lines.append("Top 5 cost tests:")
            for name, cost in top:
                lines.append(f"  ₹{cost:.4f}  {name}")
        return "\n".join(lines)


__all__ = ["BudgetExceeded", "DEFAULT_BUDGET_INR", "TestBudgetTracker"]
