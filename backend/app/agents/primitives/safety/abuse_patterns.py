"""D9 / Pass 3g §B.4 — Layer 3 cross-conversation abuse pattern detection.

Catches *patient* attackers — students who probe slowly hoping each
individual message stays below a threshold. Reads from
safety_incidents (the per-finding audit table from migration 0058) to
look at a user's recent history rather than just the current message.

Three signals tracked in v1:
  • Repeated safety blocks  (>= 3 in 24h)
  • Diverse attack categories (>= 3 distinct categories in 7d)
  • New-account aggression  (account < 24h old AND any high-severity
    incident already)

The fourth signal Pass 3g §B.4 mentions (coordinated IP-correlated
abuse) is deferred per Pass 3g §J — it needs IP-tracking infra not
in v1.

Design choice (per Checkpoint 2 sign-off): the detector takes an
*injectable async function* that returns recent incidents for a user.
Tests pass mock data; Checkpoint 3 wires the real DB-backed lookup.
This mirrors the EscalationLimiter (D5) testability pattern.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.schemas.safety import SafetyFinding


# Thresholds — tunable per-deployment. v1 starts conservative.
DEFAULT_REPEATED_BLOCKS_LIMIT = 3
DEFAULT_REPEATED_BLOCKS_WINDOW = timedelta(hours=24)
DEFAULT_DIVERSE_CATEGORIES_LIMIT = 3
DEFAULT_DIVERSE_CATEGORIES_WINDOW = timedelta(days=7)
DEFAULT_NEW_ACCOUNT_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class IncidentSummary:
    """Trimmed view of a safety_incidents row for the detector.

    The detector doesn't need the full row — only timestamp, category,
    severity, decision. Keeps the contract narrow so the Checkpoint 3
    DB-backed loader can return projections instead of full ORM rows.
    """

    occurred_at: datetime
    category: str
    severity: str
    decision: str  # 'allow' | 'redact' | 'warn' | 'block'


# Type alias for the injectable lookup function.
#
# Async by convention — Checkpoint 3's real implementation will
# query Postgres asynchronously. For tests, an async lambda or an
# async helper that returns a static list works.
IncidentLookup = Callable[
    [uuid.UUID, datetime],  # user_id, since
    Awaitable[list[IncidentSummary]],
]

# Optional callback for "when did this user's account get created?"
# Used only for the new-account aggression signal. Returns None if
# unknown — detector silently skips that signal in that case.
AccountAgeLookup = Callable[
    [uuid.UUID],
    Awaitable[datetime | None],
]


class AbusePatternDetector:
    """Layer 3 cross-conversation abuse detector.

    Stateless — every call re-reads the user's recent incidents
    through the injected lookup. Cache invalidation is the caller's
    responsibility (the typical caller is SafetyGate.scan_input,
    which runs once per request — caching across requests would
    make signals lag reality).
    """

    def __init__(
        self,
        *,
        incident_lookup: IncidentLookup,
        account_age_lookup: AccountAgeLookup | None = None,
        repeated_blocks_limit: int = DEFAULT_REPEATED_BLOCKS_LIMIT,
        repeated_blocks_window: timedelta = DEFAULT_REPEATED_BLOCKS_WINDOW,
        diverse_categories_limit: int = DEFAULT_DIVERSE_CATEGORIES_LIMIT,
        diverse_categories_window: timedelta = DEFAULT_DIVERSE_CATEGORIES_WINDOW,
        new_account_window: timedelta = DEFAULT_NEW_ACCOUNT_WINDOW,
        # Injectable for tests so we don't depend on real wall-clock.
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._incident_lookup = incident_lookup
        self._account_age_lookup = account_age_lookup
        self._repeated_limit = repeated_blocks_limit
        self._repeated_window = repeated_blocks_window
        self._diverse_limit = diverse_categories_limit
        self._diverse_window = diverse_categories_window
        self._new_account_window = new_account_window
        self._clock = clock

    async def scan(self, user_id: uuid.UUID) -> list[SafetyFinding]:
        """Look for abuse patterns in `user_id`'s recent history.

        Returns zero or more SafetyFindings (category=abuse_pattern).
        Multiple signals can fire simultaneously — e.g. a new account
        with 4 blocked requests in the last 24 hours produces both
        the new_account_aggression and repeated_blocks findings.

        The findings are aggregated by SafetyGate via safety_policy
        like any other finding; this detector just produces the
        signals.
        """
        now = self._clock()
        # Look back as far as the longest of the configured windows
        # so a single DB query covers all signals.
        lookback_window = max(
            self._repeated_window,
            self._diverse_window,
        )
        since = now - lookback_window
        incidents = await self._incident_lookup(user_id, since)

        findings: list[SafetyFinding] = []

        # Signal 1: repeated safety blocks
        block_count = sum(
            1
            for inc in incidents
            if inc.decision == "block"
            and inc.occurred_at >= now - self._repeated_window
        )
        if block_count >= self._repeated_limit:
            findings.append(
                SafetyFinding(
                    category="abuse_pattern",
                    severity="high",
                    description=(
                        f"User has {block_count} safety blocks in last "
                        f"{int(self._repeated_window.total_seconds() / 3600)}h "
                        f"(threshold {self._repeated_limit})"
                    ),
                    evidence=None,
                    detector="abuse_repeated_blocks",
                    confidence=1.0,
                )
            )

        # Signal 2: diverse attack categories
        recent_categories = {
            inc.category
            for inc in incidents
            if inc.occurred_at >= now - self._diverse_window
            and inc.severity in ("medium", "high", "critical")
        }
        if len(recent_categories) >= self._diverse_limit:
            findings.append(
                SafetyFinding(
                    category="abuse_pattern",
                    severity="high",
                    description=(
                        f"User has triggered {len(recent_categories)} distinct "
                        f"safety categories in last "
                        f"{self._diverse_window.days}d "
                        f"(threshold {self._diverse_limit})"
                    ),
                    evidence=",".join(sorted(recent_categories)),
                    detector="abuse_diverse_categories",
                    confidence=1.0,
                )
            )

        # Signal 3: new-account aggression
        if self._account_age_lookup is not None:
            created_at = await self._account_age_lookup(user_id)
            if created_at is not None:
                # Treat naive datetimes as UTC — defensive against
                # callers who forget tzinfo.
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if now - created_at < self._new_account_window:
                    high_severity_count = sum(
                        1
                        for inc in incidents
                        if inc.severity in ("high", "critical")
                    )
                    if high_severity_count > 0:
                        findings.append(
                            SafetyFinding(
                                category="abuse_pattern",
                                severity="high",
                                description=(
                                    "Newly-created account already has "
                                    f"{high_severity_count} high-severity "
                                    "safety incidents"
                                ),
                                evidence=None,
                                detector="abuse_new_account",
                                confidence=0.9,
                            )
                        )

        return findings
