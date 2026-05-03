"""D9 Checkpoint 3 — DB-backed wiring for abuse_patterns lookups.

The Layer 3 abuse pattern detector (abuse_patterns.py) takes injectable
async lookups. This module provides the production implementations
backed by the safety_incidents and users tables.

Kept separate from abuse_patterns.py so the detector logic stays
DB-free and unit-testable; the wiring lives here and gets composed
by SafetyGate at construction time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.primitives.safety.abuse_patterns import (
    AbusePatternDetector,
    IncidentSummary,
)

log = structlog.get_logger().bind(layer="abuse_db")


# ── DB-backed lookups ──────────────────────────────────────────────


def make_incident_lookup(
    session_factory: async_sessionmaker[AsyncSession],
) -> Any:
    """Build an IncidentLookup that reads from the safety_incidents table.

    Takes a session factory rather than a session because abuse-
    pattern lookups happen across many incoming requests; a per-request
    session would couple them to the calling request's transaction.
    Independent reads are cleaner — rolling back the incident scan
    if the calling request rolls back is wrong.
    """

    async def _lookup(
        user_id: uuid.UUID, since: datetime
    ) -> list[IncidentSummary]:
        try:
            async with session_factory() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT occurred_at, incident_type, severity, decision
                        FROM safety_incidents
                        WHERE user_id = :uid
                          AND occurred_at >= :since
                        ORDER BY occurred_at DESC
                        LIMIT 200
                        """
                    ),
                    {"uid": user_id, "since": since},
                )
                rows = result.all()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "abuse_db.incident_lookup_failed",
                error=str(exc),
                user_id=str(user_id),
            )
            return []

        return [
            IncidentSummary(
                occurred_at=row[0],
                category=row[1],
                severity=row[2],
                decision=row[3],
            )
            for row in rows
        ]

    return _lookup


def make_account_age_lookup(
    session_factory: async_sessionmaker[AsyncSession],
) -> Any:
    """Build an AccountAgeLookup that reads users.created_at."""

    async def _lookup(user_id: uuid.UUID) -> datetime | None:
        try:
            async with session_factory() as session:
                result = await session.execute(
                    text("SELECT created_at FROM users WHERE id = :uid"),
                    {"uid": user_id},
                )
                row = result.first()
                if row is None:
                    return None
                return row[0]
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "abuse_db.account_age_lookup_failed",
                error=str(exc),
                user_id=str(user_id),
            )
            return None

    return _lookup


def build_db_backed_abuse_detector(
    session_factory: async_sessionmaker[AsyncSession],
) -> AbusePatternDetector:
    """Convenience: build an AbusePatternDetector wired to real DB.

    Used by the SafetyGate factory at FastAPI lifespan startup.
    Tests don't call this — they construct AbusePatternDetector
    directly with mock callables.
    """
    return AbusePatternDetector(
        incident_lookup=make_incident_lookup(session_factory),
        account_age_lookup=make_account_age_lookup(session_factory),
    )


__all__ = [
    "build_db_backed_abuse_detector",
    "make_account_age_lookup",
    "make_incident_lookup",
]
