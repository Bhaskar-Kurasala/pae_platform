# D16 follow-up — disrupt_prevention as @proactive agent

**Status:** Open. Deferred per D16 D-A. Revisit only if real value emerges.
**Created:** 2026-05-08 (D16/CP2 closure).

## What this is

The original D16 plan promoted `disrupt_prevention` to a `@proactive(cron=...)`
agent so it would auto-run nightly against the at-risk cohort and surface
re-engagement messages. D-A locked at CP1 reversed this:

- The existing chat-on-return flow already surfaces re-engagement when an
  inactive student opens the chat after the inactivity_sweep flag — but
  only via admin trigger today (CP1 finding (h)).
- Existing F9 nightly outreach automation (`outreach_automation` Celery
  task) already drives templated email outreach against the at-risk
  cohort; promoting `disrupt_prevention` as @proactive duplicates that
  surface in a different channel without adding signal.
- `outreach_log` is canonical for admin contact records (D-B). Manual
  admin outreach via WhatsApp/phone goes through outreach_log directly,
  not through a proactive agent.

## When to revisit

A new value path that today's flows don't cover:

- A signal that the at-risk cohort wants conversational re-engagement
  (rather than templated outreach), and admins are not pinging that
  cohort manually because volume exceeded their bandwidth.
- A growth signal where re-engaged students who go through
  disrupt_prevention's chat outperform those who go through templated
  email outreach — i.e. the personalisation matters and is measurable.

Either condition would justify the @proactive wiring. Without one of
them, this stays deferred.

## What's NOT blocked

- The `@proactive(cron=...)` infrastructure is ready and unused (CP1
  finding (k); D7b plumbing). Any future agent can adopt it without
  scaffold work.
- The `agent_proactive_runs` audit + idempotency-key infrastructure is
  in place; this isn't blocked on engineering, only on signal.

## Cross-references

- `docs/architecture/d16-functional-audit.md` finding (k) — proactive
  infrastructure status.
- `docs/architecture/pass-3h-interrupt-agent-proactive-loop.md` —
  prior architectural sketch (pre-D-A).
- D16 prompt D-A locked decision.
