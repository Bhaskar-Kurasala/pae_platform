"""D17b/ITEM 3 (Path E) — deterministic lead-in opener composition.

Replaces the prompt-side lead-in approach that surfaced two
verification problems:

  1. Tone-competition: career_coach's existing "honest, direct, zero
     sycophancy" prompt instructions overrode the lead-in section's
     warmer framing; the LLM consistently led with deficit analysis
     instead of the welcome / mock-pass / gate-cleared opener.
  2. Timeout drift: study_planner's prompt extension pushed the LLM
     call past the 30s dispatch ceiling (Pattern 18b territory),
     producing empty / timeout outputs in 3 of 6 study_planner phases.

Path E (Pattern 26 canonical shape, refined): the lead-in firing
decision is **deterministic** — the platform has computed the signals
and the templates are pre-authored. The LLM does not see the lead-in
section at all. Agents call ``compose_lead_in_opener(signals, ...)``
post-LLM and prepend the returned opener (or skip when None) before
returning the response.

Trade-offs accepted (per founder direction at Path E selection):
  * Lead-in copy is templated, not LLM-generated organic.
  * Future tone iteration requires a code change, not a prompt change.
  * Templates feel slightly more mechanical than free-form riffs.

These trade-offs are smaller than the unreliability of the LLM-judgment
approach demonstrated in the 7-phase verification under MiniMax
routing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from app.agents.tools.universal.read_student_lead_in_signals import (
    ReadStudentLeadInSignalsOutput as StudentLeadInSignals,
)


AgentName = Literal["career_coach", "study_planner"]


# ── Trigger windows (kept as module constants so tests can pin them) ─

# Returning-after-absence: agent leads with a re-engagement framing
# when the student has been gone this many days or more.
_ABSENCE_DAYS_THRESHOLD = 5

# Mock-pass: career_coach celebrates a fresh mock pass within this
# rolling window. Tight window so the framing only fires on the
# session that just happened, not on stale wins.
_MOCK_PASS_WINDOW_HOURS = 24

# Gate-cleared: career_coach celebrates a transition within this
# rolling window. Wider than mock window because gate transitions
# happen rarely and the "fresh" feeling lasts longer.
_GATE_CLEARED_WINDOW_HOURS = 48

# Momentum: study_planner acknowledges consistency when active days
# in last 7 are at this threshold or above.
_MOMENTUM_ACTIVITY_DAYS_THRESHOLD = 3


# ── Templates ────────────────────────────────────────────────────────
#
# Per-agent, per-trigger. Keep templates short (one sentence each)
# so the prepended opener flows into the agent's normal response
# without dominating the message.
#
# Tone discipline (encoded as content here rather than prompt):
#   * Honest + curious, never performative.
#   * Acknowledge the moment; don't perform care.
#   * Open a door (the question), don't lecture.

_TEMPLATES: dict[tuple[AgentName, str], str] = {
    # Returning-after-absence — both agents have one
    ("career_coach", "returning_after_absence"): (
        "Welcome back — saw you stepped away for a bit. What's pulling "
        "at you right now?"
    ),
    ("study_planner", "returning_after_absence"): (
        "Last week's plan didn't quite land — let's re-set. What's "
        "your week look like?"
    ),
    # Mock-pass — career_coach only
    ("career_coach", "mock_pass"): (
        "Nice work on that mock — you're one step closer to clearing "
        "the gate."
    ),
    # Gate-cleared — career_coach only; copy formats with role display name
    # and (optionally) an identity brief from role_state. The default
    # (no brief) phrasing is graceful when the brief isn't available.
    ("career_coach", "gate_cleared_with_brief"): (
        "Congratulations on clearing to {display_name}. Here's what "
        "changes at this level: {role_identity_brief}"
    ),
    ("career_coach", "gate_cleared_no_brief"): (
        "Congratulations on clearing the gate. What do you want to "
        "focus on next?"
    ),
    # Stalled — study_planner only
    ("study_planner", "capstone_stalled"): (
        "Noticed the exercises haven't been clicking — want to walk "
        "through one together before we plan the week?"
    ),
    # Momentum — study_planner only
    ("study_planner", "momentum"): (
        "You've been consistent — keep going. Here's a tighter plan "
        "than last week."
    ),
}


# ── Public API ───────────────────────────────────────────────────────


def compose_lead_in_opener(
    signals: StudentLeadInSignals,
    *,
    agent_name: AgentName,
    role_identity_brief: str | None = None,
    next_role_display_name: str | None = None,
    now: datetime | None = None,
) -> str | None:
    """Compose a lead-in opener from deterministic state signals.

    Returns None when no signal warrants a lead-in (the healthy-student
    baseline path; agent's response goes out unchanged). Returns a
    one-sentence opener string when triggered.

    Priority order (first match wins; agent_name filters out triggers
    that don't apply to that agent):

      1. Returning-after-absence (both agents)
         → days_since_last_session >= 5

      2. Mock-pass (career_coach only)
         → most_recent_mock_pass_at within last 24h

      3. Gate-cleared (career_coach only)
         → most_recent_transition_completed_at within last 48h

      4. Stalled (study_planner only)
         → current_slip_type == 'capstone_stalled'

      5. Momentum (study_planner only)
         → recent_activity_days_count_7d >= 3 AND no slip signal

    The priority order matters for ambiguous-state students:
      * A student who BOTH cleared a gate AND has been gone 5 days
        gets the **returning-after-absence** framing first per the
        priority table above (re-engagement is the more urgent product
        signal — the celebration can come back into the session later).
      * A study_planner student who BOTH has a stall signal AND high
        activity gets the **stalled** framing — declaring momentum on
        a slip-flagged student is performative.

    Args:
      signals: aggregator output from read_student_lead_in_signals.
      agent_name: which agent's templates to use.
      role_identity_brief: optional one-line description of the student's
        new role identity, used to enrich the gate-cleared opener.
        When provided, must be paired with next_role_display_name; both
        get formatted into the template. When omitted, falls back to
        the no-brief gate-cleared template.
      next_role_display_name: optional display name for the role the
        student just transitioned INTO (e.g. "Data Analyst"). Required
        when role_identity_brief is provided.
      now: optional time anchor for testing (default datetime.now(UTC)).
        Production callers pass None.

    Returns:
      The opener string, or None when no signal warrants a lead-in.
    """
    if now is None:
        now = datetime.now(UTC)

    # Rule 1 — returning-after-absence (both agents)
    days_absent = signals.days_since_last_session
    if days_absent is not None and days_absent >= _ABSENCE_DAYS_THRESHOLD:
        return _TEMPLATES[(agent_name, "returning_after_absence")]

    # Rule 2 — mock-pass (career_coach only)
    if agent_name == "career_coach":
        mock_at = signals.most_recent_mock_pass_at
        if mock_at is not None and (now - mock_at) <= timedelta(
            hours=_MOCK_PASS_WINDOW_HOURS
        ):
            return _TEMPLATES[("career_coach", "mock_pass")]

    # Rule 3 — gate-cleared (career_coach only)
    if agent_name == "career_coach":
        transition_at = signals.most_recent_transition_completed_at
        if transition_at is not None and (now - transition_at) <= timedelta(
            hours=_GATE_CLEARED_WINDOW_HOURS
        ):
            if role_identity_brief and next_role_display_name:
                return _TEMPLATES[
                    ("career_coach", "gate_cleared_with_brief")
                ].format(
                    display_name=next_role_display_name,
                    role_identity_brief=role_identity_brief,
                )
            return _TEMPLATES[("career_coach", "gate_cleared_no_brief")]

    # Rule 4 — stalled (study_planner only)
    if agent_name == "study_planner":
        if signals.current_slip_type == "capstone_stalled":
            return _TEMPLATES[("study_planner", "capstone_stalled")]

    # Rule 5 — momentum (study_planner only); requires absence of slip
    if agent_name == "study_planner":
        if (
            signals.recent_activity_days_count_7d
            >= _MOMENTUM_ACTIVITY_DAYS_THRESHOLD
            and signals.current_slip_type is None
        ):
            return _TEMPLATES[("study_planner", "momentum")]

    # No rule fired — healthy student baseline path.
    return None


__all__ = [
    "AgentName",
    "compose_lead_in_opener",
]
