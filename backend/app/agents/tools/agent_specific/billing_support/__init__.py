"""D10 Checkpoint 3 — billing_support agent-specific tools.

Per Pass 3d §F.1, the four lookup + escalation tools the
billing_support agent calls to ground its answers in the
student's actual records:

  • lookup_order_history       — orders most-recent-first
  • lookup_active_entitlements — what courses they have access to
  • lookup_refund_status       — refund state machine status
  • escalate_to_human          — write a student_inbox row tagged
                                  for admin review

Importing this package side-effect-registers all four tools with
`app.agents.primitives.tools.registry`. The agent's
`uses_tools=True` flag + the per-tool `requires=...` permissions
gate access at the executor.

Real SQL bodies against the production schema (orders, refunds,
payment_attempts, course_entitlements, student_inbox). Tools
follow the asyncpg-rollback discipline from Commit 5
(docs/followups/asyncpg-rollback-discipline.md): any caught DB
exception triggers a session rollback so downstream statements
on the same session don't trip InFailedSQLTransactionError.
"""

from app.agents.tools.agent_specific.billing_support import (  # noqa: F401
    escalate_to_human,
    lookup_active_entitlements,
    lookup_order_history,
    lookup_refund_status,
)


__all__ = [
    "escalate_to_human",
    "lookup_active_entitlements",
    "lookup_order_history",
    "lookup_refund_status",
]
