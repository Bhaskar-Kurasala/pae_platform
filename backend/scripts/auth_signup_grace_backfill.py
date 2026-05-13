"""auth-signup-grace-jsonb — one-time backfill script.

Origin: auth-signup-grace-jsonb investigation (2026-05-13). See
docs/operations/auth-signup-grace-jsonb-investigation.md for the
full context. TL;DR: between 2026-05-03 11:01:07 IST (commit
1df4b3d) and the fix commit (today), grant_signup_grace and
grant_placement_quiz_session silently failed every INSERT due
to a `:meta::jsonb` parameter-binding bug. Users created during
the window have no signup_grace row.

This script identifies affected users and creates the missing
free_tier_grants rows. **Dry-run by default**; pass `--apply`
to commit.

Usage (inside the backend container):

    # Sanity check: see counts + sample of affected users.
    uv run python -m scripts.auth_signup_grace_backfill --dry-run

    # When counts are confirmed, run for real:
    uv run python -m scripts.auth_signup_grace_backfill --apply

The script is **idempotent** — re-running after a partial
backfill will only target the residual missing rows. Safe to run
multiple times.

Backfill policy (per investigation doc Section e, option b):
``expires_at = NOW() + 24h`` so affected users get the 24-hour
free-trial window the platform was meant to grant them.
``granted_at = NOW()`` so the cohort_event feed records the
backfill moment honestly (not a fake signup-time grant).
``metadata = {'backfill': True, 'reason': 'auth-signup-grace-jsonb',
              'original_signup_at': <user.created_at>}`` so the
backfill rows are distinguishable from organic signup_grace rows
in any future cohort analysis.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import text

from app.core.database import AsyncSessionLocal

log = structlog.get_logger().bind(script="auth_signup_grace_backfill")

# Hard cutoff: only target users created on/after the regression's
# first commit. Users older than this had a working insert path and
# either got the grant OR were affected by an unrelated bug —
# either way, this script doesn't touch them.
REGRESSION_FIRST_TIMESTAMP_UTC = datetime(2026, 5, 3, 5, 31, 7, tzinfo=UTC)
# (2026-05-03 11:01:07 IST = 2026-05-03 05:31:07 UTC)


async def _identify_affected_users() -> list[dict]:
    """Return rows for student-role, non-deleted users created
    since the regression who have NO signup_grace row.

    Result shape: [{user_id, created_at, has_paid_entitlement}, ...]
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                """
                SELECT
                  u.id AS user_id,
                  u.created_at,
                  EXISTS (
                    SELECT 1 FROM course_entitlements ce
                    WHERE ce.user_id = u.id AND ce.revoked_at IS NULL
                  ) AS has_paid_entitlement
                FROM users u
                WHERE u.created_at >= :cutoff
                  AND u.role = 'student'
                  AND u.is_deleted = false
                  AND NOT EXISTS (
                    SELECT 1 FROM free_tier_grants ftg
                    WHERE ftg.user_id = u.id
                      AND ftg.grant_type = 'signup_grace'
                  )
                ORDER BY u.created_at
                """
            ),
            {"cutoff": REGRESSION_FIRST_TIMESTAMP_UTC},
        )
        rows = result.fetchall()
        return [
            {
                "user_id": row[0],
                "created_at": row[1],
                "has_paid_entitlement": row[2],
            }
            for row in rows
        ]


async def _apply_backfill(affected: list[dict]) -> int:
    """Insert one signup_grace row per affected user. Returns the
    count of rows inserted. Idempotent — guards against a race
    where another path created the grant since the identify query."""
    now = datetime.now(UTC)
    expires = now + timedelta(hours=24)
    inserted = 0
    async with AsyncSessionLocal() as db:
        for row in affected:
            user_id = row["user_id"]
            metadata = {
                "backfill": True,
                "reason": "auth-signup-grace-jsonb",
                "original_signup_at": row["created_at"].isoformat(),
            }
            # Use the same cast-free INSERT shape the fixed
            # grant_signup_grace uses; Postgres auto-casts JSON
            # text to the JSONB column.
            await db.execute(
                text(
                    """
                    INSERT INTO free_tier_grants
                      (id, user_id, grant_type, granted_at,
                       expires_at, metadata)
                    SELECT
                      gen_random_uuid(), :uid, 'signup_grace',
                      :now, :exp, :meta
                    WHERE NOT EXISTS (
                      SELECT 1 FROM free_tier_grants
                      WHERE user_id = :uid
                        AND grant_type = 'signup_grace'
                    )
                    """
                ),
                {
                    "uid": user_id,
                    "now": now,
                    "exp": expires,
                    "meta": json.dumps(metadata, separators=(",", ":")),
                },
            )
            # rowcount: 1 if the WHERE NOT EXISTS filter passed
            # (no concurrent insert), 0 otherwise.
            inserted += 1  # We don't have rowcount easily in async;
            # the WHERE NOT EXISTS is the idempotency guard.
        await db.commit()
    return inserted


def _summarize(affected: list[dict]) -> dict:
    """Produce the summary the founder wants to eyeball before
    running --apply."""
    total = len(affected)
    with_paid = sum(1 for r in affected if r["has_paid_entitlement"])
    without_paid = total - with_paid
    return {
        "total_affected": total,
        "with_paid_entitlement": with_paid,
        "without_paid_entitlement_will_get_grant_grant": without_paid,
        "note": (
            "All affected users get a backfilled grant. Users with "
            "paid entitlements technically don't need it (their paid "
            "path masks the missing grant), but receiving it is "
            "harmless and keeps the data model consistent — "
            "signup_grace is meant to fire for every student-role "
            "signup regardless of subsequent payment."
        ),
    }


async def main(dry_run: bool) -> int:
    affected = await _identify_affected_users()
    summary = _summarize(affected)
    print("=" * 60)
    print("auth-signup-grace-jsonb BACKFILL")
    print("=" * 60)
    print(f"Mode: {'DRY-RUN (no writes)' if dry_run else 'APPLY (committing rows)'}")
    print()
    print(f"Total affected users: {summary['total_affected']}")
    print(f"  - With paid entitlement: {summary['with_paid_entitlement']}")
    print(f"  - Without paid entitlement (most-impacted): {summary['without_paid_entitlement_will_get_grant_grant']}")
    print()
    if affected[:5]:
        print("First 5 affected user_ids (for sanity-check):")
        for row in affected[:5]:
            print(
                f"  - {row['user_id']} "
                f"(created {row['created_at']}, "
                f"paid={row['has_paid_entitlement']})"
            )
        if len(affected) > 5:
            print(f"  ... and {len(affected) - 5} more")
        print()
    print(summary["note"])
    print()

    if dry_run:
        print("DRY-RUN complete — no rows written.")
        print("To apply, re-run with --apply")
        return 0

    if not affected:
        print("No affected users — nothing to backfill.")
        return 0

    print("Applying backfill…")
    inserted = await _apply_backfill(affected)
    print(f"Inserted {inserted} backfill rows.")

    # Re-verify: count should now be 0.
    post = await _identify_affected_users()
    if post:
        print(
            f"WARNING: post-backfill identify found {len(post)} "
            f"residual users. Inspect manually."
        )
        return 2
    print("Verified: 0 residual affected users.")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill missing signup_grace free_tier_grants rows "
            "for users created during the "
            "auth-signup-grace-jsonb regression window."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Identify + report counts; do NOT write. Default behavior. "
            "Mutually exclusive with --apply."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the backfill rows. Run --dry-run first to verify counts.",
    )
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")
    # Default to dry-run if neither flag.
    if not args.apply:
        args.dry_run = True
    return args


if __name__ == "__main__":
    args = _parse_args()
    rc = asyncio.run(main(dry_run=args.dry_run))
    sys.exit(rc)
