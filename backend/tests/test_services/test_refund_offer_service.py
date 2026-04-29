"""F11 — Refund offer service tests.

Five cases per the F11 ticket:
  1. propose_refund writes a row in 'proposed' state
  2. send_refund_offer happy path → status='sent' + outreach_log linked
  3. send_refund_offer when no email service path (no_recipient on user) →
     offer stays in 'proposed' so retry remains possible
  4. mark_response('accepted' | 'declined') → status flip + responded_at set
  5. list_open_for_user returns rows newest-first

The email send is monkeypatched at outreach_email_service.send_outreach_email
so the test never touches SendGrid (or jinja templates we don't ship in the
test sandbox).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach_log import OutreachLog
from app.models.refund_offer import RefundOffer
from app.models.user import User
from app.services import outreach_email_service, refund_offer_service


async def _make_user(
    db: AsyncSession, *, email: str = "ref@pae.dev", name: str = "Ref User"
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name=name,
        hashed_password="x",
        role="student",
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.commit()
    return user


async def _make_admin(db: AsyncSession) -> User:
    admin = User(
        id=uuid.uuid4(),
        email="admin@pae.dev",
        full_name="Admin",
        hashed_password="x",
        role="admin",
        is_active=True,
        is_verified=True,
    )
    db.add(admin)
    await db.commit()
    return admin


@pytest.mark.asyncio
async def test_propose_refund_writes_row_in_proposed_state(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    admin = await _make_admin(db_session)

    offer = await refund_offer_service.propose_refund(
        db_session,
        user_id=user.id,
        proposed_by_admin_id=admin.id,
        reason="No engagement since day-7 nudge.",
    )

    assert offer.status == "proposed"
    assert offer.user_id == user.id
    assert offer.proposed_by == admin.id
    assert offer.reason == "No engagement since day-7 nudge."
    assert offer.outreach_log_id is None
    assert offer.responded_at is None

    # Round-trip through the DB to confirm it persisted.
    refetched = await db_session.get(RefundOffer, offer.id)
    assert refetched is not None
    assert refetched.status == "proposed"


@pytest.mark.asyncio
async def test_send_refund_offer_flips_status_and_links_outreach_log(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: send_outreach_email returns 'mocked' (no API key),
    which the service treats as a successful send for accounting
    purposes — the audit trail is intact, just no real network call."""
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.setattr(
        outreach_email_service,
        "render_template",
        lambda k, v: ("Subject!", f"<p>Hello {v.get('name', 'there')}</p>"),
    )

    user = await _make_user(db_session)
    admin = await _make_admin(db_session)

    proposed = await refund_offer_service.propose_refund(
        db_session,
        user_id=user.id,
        proposed_by_admin_id=admin.id,
        reason="14-day silent.",
    )
    sent = await refund_offer_service.send_refund_offer(
        db_session, offer_id=proposed.id
    )

    assert sent.status == "sent"
    assert sent.outreach_log_id is not None

    # Outreach log row exists and references the same user with the
    # refund_offer template_key.
    log_row = await db_session.get(OutreachLog, sent.outreach_log_id)
    assert log_row is not None
    assert log_row.user_id == user.id
    assert log_row.template_key == "refund_offer"
    assert log_row.triggered_by == "admin_manual"
    assert log_row.triggered_by_user_id == admin.id


@pytest.mark.asyncio
async def test_send_refund_offer_when_email_blocked_keeps_status_proposed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the email service can't send (e.g. user has no recipient
    address) the offer must remain 'proposed' so the admin can retry —
    NOT 'sent', which would lie about the audit trail, and NOT 'failed',
    which the schema doesn't define."""
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.setattr(
        outreach_email_service,
        "render_template",
        lambda k, v: ("S", "<p>x</p>"),
    )

    # Create a user with no email; outreach_email_service will short-
    # circuit to 'no_recipient' status.
    admin = await _make_admin(db_session)
    user = User(
        id=uuid.uuid4(),
        email="placeholder@pae.dev",
        full_name="Placeholder",
        hashed_password="x",
        role="student",
        is_active=True,
        is_verified=False,
    )
    db_session.add(user)
    await db_session.commit()
    # Manually clear email post-insert because the column is unique +
    # non-null at the schema level — the service guards on falsy email.
    user.email = ""
    await db_session.commit()

    proposed = await refund_offer_service.propose_refund(
        db_session,
        user_id=user.id,
        proposed_by_admin_id=admin.id,
        reason="14d silent.",
    )
    sent = await refund_offer_service.send_refund_offer(
        db_session, offer_id=proposed.id
    )

    # Offer stays in 'proposed', NO outreach_log linkage even though
    # outreach_email_service did write an audit row of its own.
    assert sent.status == "proposed"
    assert sent.outreach_log_id is None


@pytest.mark.asyncio
async def test_mark_response_sets_status_and_responded_at(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    admin = await _make_admin(db_session)
    offer = await refund_offer_service.propose_refund(
        db_session,
        user_id=user.id,
        proposed_by_admin_id=admin.id,
        reason=None,
    )

    accepted = await refund_offer_service.mark_response(
        db_session, offer_id=offer.id, response="accepted"
    )
    assert accepted.status == "accepted"
    assert accepted.responded_at is not None
    assert isinstance(accepted.responded_at, datetime)

    # 'declined' is also valid; invalid inputs raise.
    declined_offer = await refund_offer_service.propose_refund(
        db_session,
        user_id=user.id,
        proposed_by_admin_id=admin.id,
        reason=None,
    )
    declined = await refund_offer_service.mark_response(
        db_session, offer_id=declined_offer.id, response="declined"
    )
    assert declined.status == "declined"

    with pytest.raises(ValueError):
        await refund_offer_service.mark_response(
            db_session, offer_id=offer.id, response="weird"  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_list_open_for_user_returns_newest_first(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    admin = await _make_admin(db_session)

    first = await refund_offer_service.propose_refund(
        db_session,
        user_id=user.id,
        proposed_by_admin_id=admin.id,
        reason="first try",
    )
    # Force first.proposed_at to be older than the second.
    first.proposed_at = datetime.now(UTC).replace(year=2025)
    await db_session.commit()

    second = await refund_offer_service.propose_refund(
        db_session,
        user_id=user.id,
        proposed_by_admin_id=admin.id,
        reason="second try",
    )

    listed = await refund_offer_service.list_open_for_user(
        db_session, user_id=user.id
    )
    assert [o.id for o in listed] == [second.id, first.id]
