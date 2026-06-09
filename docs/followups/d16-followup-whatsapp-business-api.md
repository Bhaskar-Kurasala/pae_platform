# D16 follow-up — WhatsApp Business API integration

**Status:** Open. Post-launch. Justified only when volume justifies the
approval ceremony.
**Created:** 2026-05-08 (D16/CP2 closure).

## What this is

D16 ships (or defers, pending CP3 decision) WhatsApp via **manual deep
links**: admin clicks `wa.me/{number}` from the cockpit, types in their
own WhatsApp, then clicks "log this contact" to write
`outreach_log(channel='whatsapp', triggered_by='admin_manual')`. No API
integration — the platform is observation + audit, not a sender.

The full WhatsApp Business API integration (programmatic sends via Meta
Cloud API, Twilio, gupshup, or similar) is post-launch. It introduces:

- Business verification with Meta (multi-week approval).
- Template message pre-approval (every templated send must be approved
  by Meta first).
- Per-message cost (currently ~$0.005-0.05 depending on country and
  conversation type).
- Webhook plumbing for delivery + read receipts (mark_delivered /
  mark_opened on outreach_log).

## When to revisit

The value-vs-friction crossover is volume-driven:

- **Below ~50 manual outreaches per admin per week**: deep-link is
  strictly better — admins prefer their own phone's WhatsApp (full
  history, voice notes, etc.) and the audit log captures the action.
- **Above ~50/week per admin**: admin time savings on copy-paste +
  templated sends justify the approval ceremony. At platform-cohort
  scale (multiple admins, multi-cohort), this lands first.

## What's already in place

- `outreach_log.channel='whatsapp'` is schema-supported (CP1 finding (5.2)).
- `outreach_log.external_id` accepts WhatsApp message-id strings without
  schema change.
- `outreach_log.delivered_at` + `opened_at` columns are ready for
  webhook callbacks.

## Out of scope for this follow-up

Bulk email infrastructure (separate doc:
`d16-followup-bulk-email-marketing.md`).

## Cross-references

- `docs/architecture/d16-functional-audit.md` finding (n) — admin
  workflow validation; WhatsApp gap.
- `docs/architecture/d16-pre-flight-admin-surface-audit.md` §9 —
  WhatsApp / phone contact infrastructure baseline.
- D16 prompt D-B locked decision (outreach_log canonical).
