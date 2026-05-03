"""D10 Checkpoint 3 / Pass 3d §F.1 — escalate_to_human.

Writes a row to `student_inbox` tagged for admin review when the
billing_support agent decides the issue needs human attention
(genuine grievance, regulatory concern, anything outside the
agent's authority per Pass 3c E1's "Hard constraints" section).

Returns a ticket_id (the inbox row's UUID) so the LLM can quote it
back to the student in its `escalation_ticket_id` output field —
giving them something concrete to reference in follow-up
conversations.

Idempotency: passes the agent-supplied `idempotency_key` to the
`student_inbox.idempotency_key` column. Per the model's partial
unique index `(user_id, idempotency_key) UNIQUE WHERE
idempotency_key IS NOT NULL`, re-firing the same escalation
collapses to a no-op and returns the existing row's id.

Permissions: admin:escalation per Pass 3d §C.1. The
billing_support agent's permission set must include this — granted
via the agent class's `permissions` declaration (see
billing_support.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.billing_support.escalate_to_human"
)


class EscalateToHumanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(
        description="The student the escalation is on behalf of."
    )
    reason: str = Field(
        min_length=3,
        max_length=200,
        description=(
            "Short machine-readable reason code or label, e.g. "
            "'repeat_charge_after_cancel_attempt' — used for "
            "admin triage filtering."
        ),
    )
    summary: str = Field(
        min_length=10,
        max_length=2000,
        description=(
            "Human-readable summary of the situation for the admin "
            "who picks up the ticket. Should include enough context "
            "that the admin doesn't need to re-interview the agent."
        ),
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Optional dedup key. If the same student fires the same "
            "escalation twice in a session, pass the same key both "
            "times — the second call returns the original ticket id "
            "rather than creating a duplicate."
        ),
    )


class EscalateToHumanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: uuid.UUID = Field(
        description=(
            "The student_inbox row id. Quote this to the student in "
            "the agent's escalation_ticket_id output field."
        ),
    )
    was_new: bool = Field(
        description=(
            "True iff a new row was inserted; False iff an existing "
            "row was found via idempotency_key dedup."
        ),
    )


@tool(
    name="escalate_to_human",
    description=(
        "Escalate the billing question to a human admin. Writes a "
        "tagged row to student_inbox with the supplied reason + "
        "summary. Returns a ticket_id the agent should quote back "
        "to the student. Idempotent via idempotency_key. Use only "
        "for genuine grievances, regulatory concerns, or issues "
        "outside the agent's authority."
    ),
    input_schema=EscalateToHumanInput,
    output_schema=EscalateToHumanOutput,
    requires=("admin:escalation",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def escalate_to_human(
    args: EscalateToHumanInput,
) -> EscalateToHumanOutput:
    """Insert a student_inbox row tagged with kind='escalation' so
    the admin inbox-triage UI can filter on it.

    On idempotency_key collision (the partial unique index throws),
    we look up the existing row and return its id with was_new=False.
    """
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "escalate_to_human called without an active session. "
            "The tool body relies on the contextvar set by call_agent."
        )

    # Pre-check: if the caller passed an idempotency_key and a row
    # already exists for this (user, key), return its id without
    # inserting. Avoids racing the partial unique index in the
    # common case (re-fire of the same escalation from a retry).
    if args.idempotency_key is not None:
        try:
            result = await session.execute(
                sql_text(
                    """
                    SELECT id FROM student_inbox
                    WHERE user_id = :uid AND idempotency_key = :key
                    LIMIT 1
                    """
                ),
                {"uid": args.student_id, "key": args.idempotency_key},
            )
            existing = result.first()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "escalate_to_human.lookup_failed",
                error=str(exc),
                student_id=str(args.student_id),
            )
            try:
                await session.rollback()
            except Exception as rollback_exc:  # noqa: BLE001
                log.error(
                    "escalate_to_human.rollback_failed",
                    original_error=str(exc),
                    rollback_error=str(rollback_exc),
                    student_id=str(args.student_id),
                )
            existing = None

        if existing is not None:
            return EscalateToHumanOutput(
                ticket_id=existing[0],
                was_new=False,
            )

    ticket_id = uuid.uuid4()
    now = datetime.now(UTC)

    # Body is the human-readable summary; title is a short header.
    # kind='escalation' so the admin triage UI can filter; agent_name
    # tags which agent fired it (admins can group by agent to see
    # which paths produce the most escalations).
    metadata: dict[str, Any] = {
        "reason": args.reason,
        "escalated_by": "billing_support",
        "escalated_at": now.isoformat(),
    }

    try:
        # NOTE: ::jsonb cast omitted on the metadata bind — asyncpg
        # parses `:meta::jsonb` as the parameter `meta:` (literal
        # colon then `:jsonb` resolves to a positional gap), which
        # raises PostgresSyntaxError. Postgres auto-casts the text
        # `_json_dumps(metadata)` to the JSONB column type at INSERT
        # because the column is declared JSONB — same trick used for
        # student_inbox.metadata_'s server_default after Commit 5
        # (see docs/followups/goal-contracts-schema-divergence.md
        # for the pattern documentation).
        await session.execute(
            sql_text(
                """
                INSERT INTO student_inbox
                  (id, user_id, agent_name, kind, title, body,
                   metadata, idempotency_key, created_at)
                VALUES
                  (:id, :uid, 'billing_support', 'escalation',
                   :title, :body, :meta, :key, :now)
                """
            ),
            {
                "id": ticket_id,
                "uid": args.student_id,
                "title": f"Billing escalation: {args.reason}"[:200],
                "body": args.summary,
                "meta": _json_dumps(metadata),
                "key": args.idempotency_key,
                "now": now,
            },
        )
        await session.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "escalate_to_human.insert_failed",
            error=str(exc),
            student_id=str(args.student_id),
            reason=args.reason,
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "escalate_to_human.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        # On insert failure, raise so the agent's prompt-side
        # decision logic surfaces it (the agent will fall back to
        # telling the student "I had trouble escalating; please
        # email support@aicareeros.com directly"). Different from
        # the read tools which return empty-but-valid output on
        # failure — escalation is a write side effect, the caller
        # needs to know it didn't land.
        raise RuntimeError(
            f"escalate_to_human failed to write inbox row: {exc}"
        ) from exc

    log.info(
        "escalate_to_human.created",
        ticket_id=str(ticket_id),
        student_id=str(args.student_id),
        reason=args.reason,
    )
    return EscalateToHumanOutput(ticket_id=ticket_id, was_new=True)


def _json_dumps(value: Any) -> str:
    """Compact JSON for the metadata column. Matches the pattern
    in entitlement_service.py's grant_signup_grace."""
    import json as _json

    return _json.dumps(value, separators=(",", ":"), default=str)


__all__ = [
    "EscalateToHumanInput",
    "EscalateToHumanOutput",
    "escalate_to_human",
]
