# D16 follow-up — SendGrid Event Webhook (bounce / complaint / open)

**Status:** Open. Post-launch operational.
**Created:** 2026-05-08 (D16/CP2 closure).

## What this is

CP1 finding (m): `outreach_service` exposes `mark_delivered()` and
`mark_opened()` helpers (lines 133-167 per the audit) that flip
`outreach_log.delivered_at` / `opened_at`, but **no webhook route is
registered** to actually receive SendGrid Event Webhook callbacks.
Delivery + open tracking is therefore not currently captured on
`outreach_log` rows.

This is operational deliverability infrastructure, not a code defect —
emails still send and SendGrid attempts delivery; we just don't know on
our side which ones bounced or were opened.

## What this follow-up tracks

A webhook route at `POST /api/v1/webhooks/sendgrid` that:

1. Verifies the signed payload (SendGrid signs with ECDSA; their docs
   provide the verification primitive).
2. Parses the event array.
3. For each event:
   - `delivered` → `mark_delivered(external_id)`
   - `bounce` / `dropped` → set `outreach_log.status='bounced'` /
     `'failed'`, store error
   - `open` → `mark_opened(external_id)`
   - `spamreport` → set `status='failed'`, log warning
   - `unsubscribe` → set a per-user `opted_out_marketing=true`
     preference (this requires a small `user_preferences` change)

## Pre-webhook operational checklist

- [ ] SendGrid account has a verified sender identity
- [ ] SPF + DKIM + DMARC are configured at the DNS level for the
      sending domain
- [ ] Signed Event Webhook is enabled in the SendGrid dashboard with
      the verification key copied to Fly secrets as
      `SENDGRID_WEBHOOK_VERIFICATION_KEY`

## Why post-launch

For low-volume (single-admin, per-student transactional) sends,
manually monitoring SendGrid's dashboard is fine. The webhook becomes
load-bearing once retention/marketing emails go out at cohort scale,
where bounce rate matters for sender reputation.

## Cross-references

- `backend/app/services/outreach_service.py` — `mark_delivered` /
  `mark_opened` helpers awaiting a caller.
- `docs/architecture/d16-functional-audit.md` finding (m).
- `d16-followup-bulk-email-marketing.md` — bulk send infrastructure;
  this webhook is a prerequisite for that.
