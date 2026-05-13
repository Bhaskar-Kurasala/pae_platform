# Cohort membership modeling

**Status:** Open. Deferred-pending-trigger.
**Origin:** D19.1 CP1 pre-flight (2026-04-29 — discovery that
`User.cohort_id` doesn't exist as a schema concept). D19.1 CP5
registered as "Open D-G item" in observability overview. **D19.3
closure (2026-05-13) confirms continued deferral with concrete
re-evaluation trigger.**
**Severity:** Tracked-not-blocking. Cohort-1 launch operations don't
need this; revisit on trigger.

## What's deferred

D19.1 D-B reserves `cohort_id` as a load-bearing correlation ID for
"per-cohort cost attribution in D19.3" — but the platform has no
first-class cohort membership concept on `User`. The closest existing
concepts:

  * `cohort_events.kind` + `cohort_events.level_slug` — an event-feed
    table; `level_slug` tags events with the student's promotion level
    (e.g., `python_developer`, `data_analyst`) at event time. NOT a
    cohort membership record.
  * `course_entitlements` (paid + free-tier grants) — captures access
    rights to specific courses. Not a cohort concept either; a student
    can have entitlements to multiple courses, and a "cohort" in the
    business sense is something else entirely (a time-bounded group
    of students onboarded together for a specific business reason).

Per D19.1 + D19.2 closures the deferral has remained correct: no
business need at cohort-1 scale (20-100 high-touch users where
the founder knows every user by name) has forced the modeling
decision.

## Three options on the table

When the trigger fires (see below), the architect-led re-engagement
picks between:

  **Option (a) — FK + migration.** Add `User.cohort_id` UUID NULL,
  + `cohorts` table with id, name, created_at, started_at,
  ended_at, etc. Joins through. Highest fidelity, highest schema
  change. Right when cohorts are first-class business entities
  (corporate cohorts, paid programs, multi-month structured cohorts).

  **Option (b) — Derived view on enrollment + level.** A
  materialized view that infers cohort membership from existing
  enrollment dates + role progression. No new table; no new column.
  Right when "cohort" is a reporting concept rather than a
  business entity.

  **Option (c) — `level_slug` proxy.** Use the existing
  `cohort_events.level_slug` as the proxy for cohort membership.
  Cheapest; lowest fidelity. Right when the analytical question is
  "what does the python-developer-level cohort look like in
  aggregate" rather than "what does the Q2-2026 enrollment batch
  look like."

The right choice depends on the specific cohort-2 use case that
triggers re-engagement; modeling now without that data would be
speculative.

## Re-evaluation trigger (D19.3 CP1.4 — concrete, not vague)

Return to this deliverable when ANY of:

  1. **Cohort-2 onboarding planning begins.** When the founder
     opens a planning doc for cohort-2 scope — naming the cohort,
     defining the onboarding window, identifying which agents +
     content this cohort will see differently — the cohort_id
     decision is informed by the planning's actual shape. Don't
     model in the abstract; model against the planning artifact.
  2. **A corporate cohort signs an enrollment commitment.** A
     corporate buyer (e.g., a company enrolling 50 employees in
     a structured 8-week cohort) is the natural moment for
     option (a) — the business explicitly is paying for cohort
     identity, so cohort_id becomes a load-bearing concept.
  3. **A cohort-1 retrospective surfaces a cost-attribution
     question the per-student view can't answer.** Specifically:
     a question of shape "the 5 students who joined in week 3
     are costing 3x the students who joined in week 1 — what's
     different about them?" can't be answered by per-student
     attribution because the question is about a cohort
     (joining-week aggregate), not a student. If this question
     comes up post-cohort-1, that's the trigger.

The trigger formulation matters more than the eventual answer:
the next architect-led pass at cohort_id has unambiguous criteria
for re-engaging.

## Implications across D19 substrate

CP1's `_PROPAGATED_KEYS` in `app/core/celery_logging.py` includes
`cohort_id` as a reserved key — Celery task propagation already
handles it. When `cohort_id` is bound to structlog contextvars
(post-decision), the propagation works without any
celery_logging.py change.

Dashboards: the cost dashboard's `per-cohort-attribution-placeholder`
panel (D19.3 CP1.2) explicitly carries the placeholder until the
decision lands. When the deferred decision lands, the placeholder
panel becomes a real query against the chosen mechanism.

Sentry breadcrumb bridge: structlog contextvars flow to Sentry.
Whichever option lands, `cohort_id` will appear automatically in
Sentry event tags — no Sentry-side change needed.

## Estimated cost when re-evaluated

Highly option-dependent:
  * Option (a) FK + migration: ~₹4-6 (schema design + migration +
    backfill + closure-time verification).
  * Option (b) derived view: ~₹2-4 (view definition + dashboard
    panel refit).
  * Option (c) level_slug proxy: ~₹1-2 (dashboard panel + doc
    update only; no schema work).

## Cross-references

- D19.1 observability overview (Open D-G items section): [`docs/architecture/d19-1-observability-overview.md`](../architecture/d19-1-observability-overview.md)
- D19.1 D-B contract (reserved correlation IDs): same doc, "Locked architectural decisions" section
- D19.3 cost dashboard (carries the deferred placeholder): [`docs/operations/dashboards/cost.json`](../operations/dashboards/cost.json)
- CP1 Celery propagation reserved keys: [`backend/app/core/celery_logging.py`](../../backend/app/core/celery_logging.py)
- Sibling deferral (different trigger): [`docs/followups/provider-level-cost-attribution-via-gen-ai-otel.md`](provider-level-cost-attribution-via-gen-ai-otel.md)
- D19 deferred work inventory: [`docs/followups/d19-deferred-alerting-and-runbooks.md`](d19-deferred-alerting-and-runbooks.md)
