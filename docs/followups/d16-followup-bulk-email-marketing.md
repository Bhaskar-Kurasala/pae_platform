# D16 follow-up — bulk email / marketing infrastructure

**Status:** Open. Deferred per founder reframe. Revisit at cohort scale.
**Created:** 2026-05-08 (D16/CP2 closure).

## What this is

The original D16 framing imagined Pass 3c "Email MCP" — a central
templated-email orchestration server that would handle bulk sends,
template management, and a/b testing across the student population.
D16's CP1 audit confirmed the existing SendGrid integration
(`outreach_email_service.py`) is sufficient for the per-student
transactional flows the platform actually does today (refund offers,
weekly letters, F9 nightly outreach).

The "Email MCP" as a separate primitive does not pay off at current
scale. This follow-up captures the deferral so we don't reinvent it.

## When to revisit

Two signals, either of which justifies the rebuild:

- **Cohort-size sends**: monthly newsletter to the entire active
  student base; admin-curated content; non-transactional. Today's
  per-user record() pattern doesn't scale to a 5000-student blast
  (5000 × outreach_log writes is fine; 5000 × SendGrid /v3/mail/send
  is wasteful — bulk endpoints exist).
- **A/B test infrastructure**: testing template variants for retention
  email, with success measured against `outreach_log.replied_at` or
  downstream re-engagement rate.

## What's already in place (and works)

- `outreach_email_service` handles templated transactional sends
  with audit, throttle, and dry-run gating. CP1 finding (g) verified.
- `outreach_log` audit captures channel + template + reply tracking
  for analytics.
- The Jinja2 template registry at `backend/app/templates/email/`
  works for the current ~5 templates (refund_offer, weekly_letter,
  re_engagement variants).

## Cross-references

- D16 prompt scope-out: "Email MCP server authoring (the existing
  SendGrid integration is sufficient; Pass 3c 'Email MCP' terminology
  was aspirational)".
- `docs/architecture/d16-functional-audit.md` finding (m) —
  SendGrid config status.
