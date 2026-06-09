"""Assertion helpers shipped at D18 Phase A CP5.

Four modules organized by concern:

  * traceability_assertions — verify side-effect rows landed in the
    DB after a Phase B journey runs an action through the UI.
  * grounding_assertions — verify agent text references only
    accessible content + role vocabulary (wraps D15 verifier).
  * behavior_shape_assertions — heuristic checks on agent text
    (intent / role-voice / no-sycophancy / no-fabricated-urgency).
  * cost_budget — TestBudgetTracker + agent_invocation_log query
    for per-test LLM-cost attribution + ceiling enforcement.

Phase B journey tests import from these modules; CP6 final smoke
exercises the full helper surface end-to-end.
"""

from .behavior_shape_assertions import (
    assert_no_fabricated_urgency,
    assert_no_sycophancy,
    assert_response_contains_intent,
    assert_response_role_appropriate,
)
from .cost_budget import BudgetExceeded, TestBudgetTracker
from .grounding_assertions import (
    assert_no_runtime_grounding_violation,
    assert_no_runtime_grounding_violation_db,
)
from .traceability_assertions import (
    assert_agent_action_logged,
    assert_outreach_log_entry,
    assert_student_message_thread,
    assert_student_note_count,
)

__all__ = [
    "BudgetExceeded",
    "TestBudgetTracker",
    "assert_agent_action_logged",
    "assert_no_fabricated_urgency",
    "assert_no_runtime_grounding_violation",
    "assert_no_runtime_grounding_violation_db",
    "assert_no_sycophancy",
    "assert_outreach_log_entry",
    "assert_response_contains_intent",
    "assert_response_role_appropriate",
    "assert_student_message_thread",
    "assert_student_note_count",
]
