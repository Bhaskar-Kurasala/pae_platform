"""F11 — RefundOfferService: Slip 4 day 14 refund-offer flow.

When a paid_silent student crosses 14 days of inactivity, the admin can
proactively offer a refund rather than wait for the request. This service
owns the lifecycle:

  propose_refund  — admin clicks "Send offer", we write a refund_offers row
  send_refund_offer — fires the templated email via outreach_email_service,
                      links the outreach_log row back, flips status to 'sent'
                      (or 'proposed' on send failure so admin can retry)
  mark_response   — admin records the student's reply (accepted | declined)
  list_open_for_user — admin UI shows prior offers + their statuses

Two design rules to flag:
  1. We do NOT write to outreach_log directly — that's outreach_email_service's
     job. We just hold the foreign key after the send returns. Audit-table
     ownership stays in one place per the F3 contract.
  2. propose_refund + send_refund_offer are kept separate so the route
     handler can call them in one transaction OR (later) split them across
     a propose-now / send-tomorrow workflow without changing the data shape.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refund_offer import RefundOffer
from app.models.user import User
from app.services import outreach_email_service

log = structlog.get_logger()

ResponseLiteral = Literal["accepted", "declined"]


def _now() -> datetime:
    return datetime.now(UTC)


async def propose_refund(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    proposed_by_admin_id: uuid.UUID,
    reason: str | None,
) -> RefundOffer:
    """Write a refund_offers row in 'proposed' state. Does not send mail."""
    offer = RefundOffer(
        id=uuid.uuid4(),
        user_id=user_id,
        proposed_by=proposed_by_admin_id,
        status="proposed",
        reason=(reason or "").strip() or None,
        proposed_at=_now(),
    )
    db.add(offer)
    await db.commit()
    await db.refresh(offer)
    log.info(
        "refund_offer.proposed",
        user_id=str(user_id),
        proposed_by=str(proposed_by_admin_id),
        offer_id=str(offer.id),
    )
    return offer


async def send_refund_offer(
    db: AsyncSession,
    *,
    offer_id: uuid.UUID,
) -> RefundOffer:
    """Fire the refund_offer email template, link the outreach_log row.

    Looks up the recipient via the FK to users (we do not stash the email
    on refund_offers — single source of truth is users.email). On send
    success the offer's status flips to 'sent' and outreach_log_id holds
    the audit pointer. On send failure (mocked / throttled / failed
    statuses from outreach_email_service) the offer keeps status='proposed'
    so the admin can retry without filling the row with rotten send IDs.
    """
    offer = await db.get(RefundOffer, offer_id)
    if offer is None:
        raise ValueError(f"refund_offer {offer_id} not found")

    user = await db.get(User, offer.user_id)
    if user is None:
        # The CASCADE on user delete should make this unreachable, but
        # we belt-and-brace it. A missing user means we can't send.
        log.warning("refund_offer.send.missing_user", offer_id=str(offer_id))
        return offer

    template_vars = {
        "name": user.full_name,
        # F1 risk service doesn't yet write target_role onto the user
        # row (documented v1 limitation). Once it does, swap this in.
        "target_role": "AI engineer",
        "admin_reason": offer.reason,
    }

    result = await outreach_email_service.send_outreach_email(
        db,
        user_id=user.id,
        to_email=user.email,
        template_key="refund_offer",
        template_vars=template_vars,
        slip_type="paid_silent",
        triggered_by="admin_manual",
        triggered_by_user_id=offer.proposed_by,
    )

    # 'sent' → real SendGrid send. 'mocked' → no API key path, but the
    # outreach_log row was still written + the audit trail is intact, so
    # the offer flips to 'sent' from the operator's POV. Throttled / failed
    # / no_recipient leave the offer in 'proposed' so a retry is possible.
    if result.status in {"sent", "mocked"}:
        offer.status = "sent"
        offer.outreach_log_id = result.log_id
        await db.commit()
        await db.refresh(offer)
        log.info(
            "refund_offer.sent",
            offer_id=str(offer_id),
            outreach_log_id=str(result.log_id),
            send_status=result.status,
        )
    else:
        log.warning(
            "refund_offer.send_skipped",
            offer_id=str(offer_id),
            send_status=result.status,
            reason=result.skipped_reason,
        )

    return offer


async def mark_response(
    db: AsyncSession,
    *,
    offer_id: uuid.UUID,
    response: ResponseLiteral,
) -> RefundOffer:
    """Record the student's reply: 'accepted' (process refund) or 'declined'."""
    if response not in {"accepted", "declined"}:
        raise ValueError(f"invalid response: {response!r}")
    offer = await db.get(RefundOffer, offer_id)
    if offer is None:
        raise ValueError(f"refund_offer {offer_id} not found")
    offer.status = response
    offer.responded_at = _now()
    await db.commit()
    await db.refresh(offer)
    log.info(
        "refund_offer.response_marked",
        offer_id=str(offer_id),
        response=response,
    )
    return offer


async def list_open_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> list[RefundOffer]:
    """All offers for a user, newest first.

    "Open" historically meant non-terminal but the admin UI also wants
    to see prior accepted/declined/expired offers as audit trail, so we
    return everything sorted newest-first. Filtering by status is
    cheap to do client-side in the small N (rarely more than 1-2).
    """
    q = await db.execute(
        select(RefundOffer)
        .where(RefundOffer.user_id == user_id)
        .order_by(RefundOffer.proposed_at.desc())
    )
    return list(q.scalars().all())
