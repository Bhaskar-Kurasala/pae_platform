# Capstone submission UI — frontend not built

**Status:** Open. Frontend feature gap. Backend infrastructure is
ready; the dedicated student-facing submission UI is not.
**Origin:** D18 Phase A CP3 capstone investigation (2026-05-08).
**Created:** 2026-05-08.

## What this is

The Today screen has a **capstone teaser** card
(`frontend/src/components/v8/screens/today-screen.tsx:594` —
`<section className="capstone-trailer">`) that displays a visual
brief. The "Preview brief" button on that card has **no `onClick`
handler** (file:631-642) — it renders but does nothing.

The actual capstone work surface lives at **`/practice?mode=capstone`**
— the unified Practice editor, which submits via
`POST /api/v1/practice/review`. There is **no dedicated `/capstone`
route**; capstone exercises are flagged `is_capstone=True` on the
generic `Exercise` model, and submitted via the generic
`POST /api/v1/exercises/{id}/submit` endpoint.

So "the capstone submission UI" splits across:
  * **Discovery surface** — Today teaser card with non-functional CTA.
  * **Work surface** — `/practice?mode=capstone` (unified editor).
  * **Tracking surface** — Today screen's `TodayCapstone` schema
    (drafts_count, draft_quality, days_to_due) populated by
    `backend/app/services/today_summary_service.py:70-121`.

## Why this matters

- **D18 Phase B** capstone-related journey tests can't target a
  dedicated submission UI because it doesn't exist. Two options:
    1. Skip dedicated capstone journeys until UI ships.
    2. Author them against `/practice?mode=capstone` via a future
       `PracticePage` page object.
- **Student discovery is broken.** A student who wants to submit
  their capstone has no in-product path: the teaser CTA is dead, no
  navigation links to `/practice?mode=capstone`. They must discover
  the URL externally or via a different page.
- **Capstone draft tracking is wired but unhittable** — the Today
  screen shows draft metadata, but students can't act on it.

## What's missing (frontend)

1. **CTA wiring on the Today teaser.** Either:
   - `onClick={() => router.push('/practice?mode=capstone')}` on the
     "Preview brief" button, OR
   - Wrap the teaser section in a `<Link href="/practice?mode=capstone">`.
   Estimate: ~30min, including a Playwright smoke test.

2. **Capstone-specific submission feedback.** Practice review surface
   today returns generic feedback. Capstone submissions might want
   distinct UI (rubric-grounded breakdown, draft history, "submit
   for grading" vs "save draft" affordance). Scope larger.

3. **Optional: dedicated `/capstone` route** if the founder decides
   capstone deserves a distinct surface (separate brief view, draft
   history, peer comparison). Largest scope; explicitly deferred
   pending product decision.

## What's there (backend)

- `Exercise` model with `is_capstone=True` flag.
- `POST /api/v1/exercises/{id}/submit` accepts capstone drafts.
- `POST /api/v1/practice/review` runs senior-engineer review.
- `TodayCapstone` schema + aggregation service.
- `project_evaluator` agent for rubric-grounded grading.

## Decision needed

Two paths forward (founder call):

  - **Path A — minimal (~1hr).** Wire the "Preview brief" CTA to
    `/practice?mode=capstone`. Document that capstone work happens
    in the Practice editor. Phase B journeys target the Practice
    editor with `?mode=capstone` query.
  - **Path B — full surface (multi-day).** Build a dedicated
    `/capstone` route with brief view + draft history + submit
    flow + rubric-grounded feedback display. Reserve the dedicated
    `CapstoneSubmissionPage` page-object slot for that surface.

CP3 dropped `CapstoneSubmissionPage` from the 8-page-object scope
pending this decision. The slot is reserved in the saved D18 Phase A
prompt at `docs/claude-code-prompts/d18a-prompt.md`.

## Cross-references

- `frontend/src/components/v8/screens/today-screen.tsx:594-644` —
  the non-functional teaser.
- `frontend/src/components/v8/screens/practice-screen.tsx:70,183,263-267`
  — the unified Practice editor with `?mode=capstone`.
- `backend/app/api/v1/routes/exercises.py:155-163` — submission
  endpoint.
- `backend/app/services/today_summary_service.py:70-121` —
  TodayCapstone aggregation.
- `docs/claude-code-prompts/d18a-prompt.md` — saved D18 prompt
  updated to mark CapstoneSubmissionPage as DROPPED at CP3 with
  reference to this doc.
