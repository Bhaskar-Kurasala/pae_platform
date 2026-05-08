# Frontend `data-testid` additions — D18 Phase A

**Status:** Open. Operational. CP3 inline additions complete; this doc
captures additions deferred for non-trivial reasons + the convention.
**Origin:** D18 Phase A CP3 (2026-05-08).
**Created:** 2026-05-08.

## Convention (Path C, ratified at D18 Phase A CP3)

Page objects in `backend/tests/playwright/pages/` follow:

  1. **Role-first.** Use `get_by_role`, `get_by_label`, `get_by_text`.
     Mirrors the existing `frontend/e2e/` TS suite.
  2. **`data-testid` only where role-based selection is genuinely
     insufficient** — state-driven elements with no accessible name,
     dynamic disambiguation across siblings of the same role, badges
     that share a parent role.
  3. **If a page object needs a testid the frontend doesn't have:**
     - **Trivial** (1-line attribute addition, no prop threading, no
       refactor): add inline as part of the same commit as the page
       object. Cite the page object that needs it in the diff.
     - **Non-trivial** (component refactor, prop threading,
       conditional rendering changes): register here in this doc,
       defer to a focused frontend chunk.

## CP3 inline additions (already landed)

These were trivial (1-line) and shipped in the CP3 commit:

| File | Element | Testid | Page object |
|---|---|---|---|
| `frontend/src/components/v8/screens/today-screen.tsx:594` | capstone teaser `<section>` | `today-capstone-trailer` | TodayPage |
| `frontend/src/components/v8/screens/today-screen.tsx:418` | step card "warmup" `<article>` | `today-step-warmup` | TodayPage |
| `frontend/src/components/v8/screens/today-screen.tsx:441` | step card "lesson" `<article>` | `today-step-lesson` | TodayPage |
| `frontend/src/components/v8/screens/today-screen.tsx:465` | step card "reflect" `<article>` | `today-step-reflect` | TodayPage |
| `frontend/src/app/(portal)/interview/page.tsx:57` | VerdictBadge `<span>` | `interview-verdict-badge` | MockInterviewPage |

## Non-trivial additions deferred (CP3 → frontend follow-on)

None at CP3. The pre-flight survey identified five "Sparse" surfaces
(LoginPage, TodayPage, StudentDetailPanel, LessonPage,
MockInterviewPage), but in practice every critical element was
addressable either via existing `aria-label` / `htmlFor` / role-based
selection OR via a 1-line inline addition (above). No surface required
a component refactor.

If CP4-CP6 surface gaps that need non-trivial frontend work, append
them below as `## CP{N} additions` sections with element + context +
page object that needs them.

## Path A trigger (escalation)

If CP4 / CP5 surface more than ~10 non-trivial testid gaps, escalate
this from "operational follow-up" to a focused frontend PR landing all
testid additions in one chunk (Path A from the original CP3 scope
question). Re-survey at that point to determine whether systematic
addition is cheaper than per-need addition.

## Cross-references

- `backend/tests/playwright/pages/__init__.py` — convention captured
  in package docstring.
- `backend/tests/playwright/pages/base_page.py` — convention captured
  in module docstring.
- `frontend/e2e/helpers.ts` — TS suite's existing selector patterns
  (mixed `getByTestId` / `getByRole` / `getByText`); the Python suite
  follows the same mix but with explicit role-first preference.
