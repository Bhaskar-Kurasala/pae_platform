# Phase 3 — Contributor Operating Manual

**Audience:** one teammate shipping Phase 3B in parallel with the main Phase 3A stream.
**Goal:** you can open this doc, pick a ticket, ship it at production quality, and never need to ask "wait, how do we do X here?"

If anything in this doc contradicts `CLAUDE.md`, `docs/ARCHITECTURE.md`, or existing code in the repo, the existing code wins — flag the contradiction back so we can update the doc.

---

## 1. Your scope (39 tickets, 7 areas)

You own these seven areas end-to-end. They are chosen to have **zero file-overlap** with the Phase 3A stream (tutor behavior, prompts, `stream.py`, `user_preferences`, `reflections`). If you find yourself wanting to edit any of those files — stop and ping first.

| Area | Tickets | Primary files |
|---|---|---|
| Skill Map | 6 | `frontend/src/app/(portal)/map/*`, `backend/app/api/v1/routes/skill_path.py`, `backend/app/services/skill_path_service.py` |
| Studio polish | 9 | `frontend/src/app/(portal)/studio/*`, Monaco config |
| Receipts 3B | 6 | `frontend/src/app/(portal)/receipts/*`, `backend/app/services/receipts_service.py` (new) |
| Admin 3B | 3 | `frontend/src/app/admin/*` (not `/admin/students/{id}` — 3A-18 owns that), `backend/app/api/v1/routes/admin.py` |
| Infrastructure | 8 | `backend/app/core/*`, `docs/ops/*` |
| Meta | 2 | `backend/app/models/feedback.py` (new), new `/admin/pulse` page |
| Career | 5 | `frontend/src/app/(portal)/career/*` (new), `backend/app/services/career_service.py` (new) |

Full ticket-by-ticket breakdown with why/touches/acceptance lives in [`docs/ROADMAP-P3-CRITIC.md`](ROADMAP-P3-CRITIC.md) under **Phase 3B**. Your tickets are:

**Skill Map:** `#21, #22, #24, #25, #26, #27`
**Studio:** `#39, #40, #41, #42, #43, #44, #45, #48, #50`
**Receipts:** `#75, #76, #79, #81, #82, #83`  (skip `#78` — 3A-16 owns it)
**Admin:** `#142, #148, course+rubric editor`
**Infrastructure:** `#158, #159, #160, #162, #163, #164, #165, #167`
**Meta:** `#177, #180`
**Career:** `#168, #169, #171, #172, #173`

Areas explicitly **NOT yours** (I'll ship after 3A): UI/UX polish, Mobile, Engagement, Learning mechanics, Onboarding, Community, Today, Tutor. If a UI/UX ticket blocks one of yours (e.g. you need a skeleton before the Receipts chart lands), ship your ticket without the skeleton and leave a TODO referencing the UI ticket number. Don't block.

---

## 2. Claim protocol

We share one tracker: `docs/ROADMAP-P3-CRITIC.md`. Every ticket has a checkbox.

**Before starting a ticket:**
1. `git pull --rebase` (the tracker is where conflicts happen)
2. Edit the ticket line from `- [ ] #NN …` to `- [~] #NN … (name, feat/p3-NN)` — name claims it, branch name is included
3. Commit that edit alone: `chore(tracker): claim 3B-#NN`
4. Push to your branch so others see the claim

**When done:**
1. Edit the line to `- [x] #NN … DONE (commit-sha)`
2. Include that edit in the final commit of the ticket, alongside the feature code

**Never** work on a ticket that already shows `[~]` or `[x]`. If the tracker is ambiguous, ping before starting.

---

## 3. The non-negotiables

These are not style preferences — breaking them means the change doesn't merge.

### Backend (Python)
- **Type hints on every function parameter and return.** `mypy app/` must stay clean. No `Any` except at third-party boundaries and only with a comment explaining why.
- **All DB calls are async.** Use `AsyncSession` from SQLAlchemy 2.0. If you reach for `session.query(...)`, stop — that's sync API.
- **Service-first.** Routes are thin (≤30 lines). They parse request, call a service, serialize response. Business logic lives in `app/services/`. Pure helpers live at the top of the service file so they're unit-testable without a DB.
- **`structlog`, never `print` or `logging.getLogger`.** `log = structlog.get_logger()` at module top. Log events with structured kwargs: `log.info("receipts.gap_analysis_computed", user_id=str(user.id), gap_count=3)`.
- **Pydantic schemas for every request/response.** Go in `app/schemas/`. Never return a raw SQLAlchemy model from a route.
- **Failures in non-critical paths must not break the parent request.** Pattern: wrap in try/except, log a warning, fall back to a sensible default. See `stream.py` misconception overlay for the canonical example.
- **Migrations:** use Alembic autogenerate (`alembic revision --autogenerate -m 'desc'`). Review the generated SQL before committing — autogenerate gets column types wrong sometimes. **Claim the migration number in the tracker before writing.**

### Frontend (Next.js 15 / TypeScript)
- **Server Components by default.** Only add `'use client'` when you need state, effects, or event handlers. If you can push interactivity to a small client leaf, do that instead of marking the whole page client.
- **No `any`. Strict mode is on for a reason.** If a type is genuinely dynamic, use `unknown` and narrow.
- **Tailwind utilities only.** No inline styles, no CSS modules, no styled-components. Design tokens are in `frontend/CLAUDE.md`.
- **`next/image` with explicit `width` / `height` for every image.**
- **Accessibility:** interactive elements need `aria-label` or visible text; images need `alt`; keyboard users must be able to reach every control.
- **Loading states:** use Suspense + the existing skeleton components in `components/ui/skeleton.tsx`. Don't invent a new spinner.
- **Error states:** add an `error.tsx` per route segment if it can fail.
- **React Query for server state, Zustand for client state.** Don't mix them; don't add a third state library.

### Tests (both)
- **Unit test every pure function.** If it takes primitives and returns primitives, it gets a test. See `test_at_risk_student_service.py` — pure scoring helpers, no DB, ~20 tiny focused tests. Copy that pattern.
- **Integration test for the DB path.** One test per service method that actually hits the DB with the in-memory SQLite fixture (`db_session`).
- **Frontend: Vitest for pure logic, Playwright MCP for behavior.** Don't write React Testing Library tests for "did this component render" — use the Playwright protocol below.
- **Tests go beside the thing they test:** `app/services/foo.py` → `tests/test_services/test_foo.py`. Frontend: `feature.tsx` → `feature.test.tsx` in the same dir.

### Git hygiene
- **Commit format:** `feat|fix|chore|docs|test(area): {ticket-id} {short desc}` — e.g. `feat(studio): 3B-39 Monaco diff view for tutor suggestions`
- **One logical change per commit.** If you fix an unrelated bug while in a file, commit it separately.
- **Trailer on every commit:** `Co-Authored-By: {name} <{email}>` if pairing; otherwise omit.
- **Never force-push `main`.** Never `git reset --hard` without confirming with me.
- **Never commit secrets.** `.env*` is gitignored — if you added a secret to committed code, tell me immediately so we can rotate.

---

## 4. The critic question (ask before every ticket)

> Does this change student behavior or student support?

If the answer is "it's prettier" or "we don't have this yet" or "other tools have it" — **drop the ticket and tell me.** We already dropped 45 tickets in the critic pass (see bottom of `ROADMAP-P3-CRITIC.md`). If you find another that deserves to drop, do the same: edit the tracker, move the ticket to the DROPPED section with a one-line reason, commit as `docs(tracker): drop #NN ({reason})`.

"I don't know if this matters" is a fine answer — ask me. But "it's a nice polish" is not.

---

## 5. Per-ticket completion checklist

Don't mark a ticket DONE until every box is checked. No batching — check them as you go.

- [ ] **Critic question answered.** You can state in one sentence how this changes student behavior or support.
- [ ] **Ticket claimed** in tracker (`[~]`) in its own commit before work starts.
- [ ] **Read the touched files first.** Understand the existing patterns before you add yours.
- [ ] **Code follows the non-negotiables** (section 3).
- [ ] **Pure helpers at top of service files** if backend. Unit tests for them.
- [ ] **Integration test** if the ticket touches the DB.
- [ ] **Type check clean** — `uv run mypy app/` (backend), `pnpm tsc --noEmit` (frontend).
- [ ] **Lint clean** — `uv run ruff check .` / `uv run ruff format .`, `pnpm lint`.
- [ ] **Tests pass** — `uv run pytest -x`, `pnpm test`.
- [ ] **Browser verified** if UI — see section 6.
- [ ] **Telemetry logged.** Every ticket emits at least one `log.info("{area}.{event}", ...)` line with structured kwargs. Without this we can't see if the feature is used.
- [ ] **Tracker updated** to `[x] DONE (sha)` in the same commit as the feature code.
- [ ] **No dead code.** If you stub something for later, leave a TODO with the ticket number. No orphaned imports or unused variables.

If any box is unchecked at merge time, don't merge. Fix it.

---

## 6. Browser verification protocol (UI tickets)

For any ticket that changes what a user sees or clicks, verify in a real browser before marking DONE. Use Playwright MCP — it's the same tool I use. Do not self-certify "LGTM" from code reading alone; UI bugs hide in rendering, hydration, and interaction.

### Setup (once)
1. Start backend: `cd backend && uv run uvicorn app.main:app --reload`
2. Start frontend: `cd frontend && pnpm dev` (port 3000 by default; 3003 if 3000 is busy)
3. Plant an authenticated admin session via Playwright MCP's `browser_evaluate` writing Zustand's `auth-storage` key into localStorage (the existing e2e/smoke scripts have the exact shape — grep `auth-storage` in the repo).

### Protocol (every UI ticket)
1. `browser_navigate` to the affected route.
2. `browser_snapshot` — capture the page tree. Read it. Confirm the element you added exists with the right `ref`, label, and role.
3. `browser_click` / `browser_type` — drive the new interaction. Capture the snapshot after every action.
4. `browser_take_screenshot` of the golden path. Save to `.playwright-mcp/` with a descriptive name (`3b-39-diff-view-after-edit.png`). These are gitignored by default.
5. `browser_console_messages` — **read every message**. Hydration warnings, 404s, uncaught errors all count as failures. Fix them before marking DONE.
6. `browser_network_requests` — confirm no 500s, no unexpected 4xx. If your feature made a new API call, verify the payload shape.
7. **Test at least two edge cases** besides the golden path: empty state, error state (kill the backend mid-request), long content, mobile viewport (`browser_resize` to 375×812).

If any step fails, do not mark DONE. Fix the bug, re-verify from step 1.

### What counts as "tested"
- Vitest green is **not** "tested" for a UI ticket. It's necessary, not sufficient.
- Type-check green is **not** "tested."
- A passing Playwright pass on the golden path **plus** two edge cases is "tested."

---

## 7. File ownership table

Two people editing the same file at the same time = merge conflicts and wasted time. If you need to touch a file in the **Mine** column, ping first and we'll coordinate.

| File / path | Owner |
|---|---|
| `backend/app/api/v1/routes/stream.py` | Mine (3A) |
| `backend/app/services/student_context_service.py` | Mine (3A) |
| `backend/app/agents/moa.py` and `app/agents/prompts/*` | Mine (3A) |
| `backend/app/models/user_preferences.py` | Mine (3A — adding `socratic_level`) |
| `backend/app/models/reflection.py` | Mine (3A — adding `kind` column) |
| `backend/app/services/preferences_service.py` | Mine (3A) |
| `frontend/src/app/(portal)/today/*` | Mine (3A) |
| `frontend/src/app/(portal)/chat/*` | Mine (3A) |
| `frontend/src/app/admin/students/[id]/*` | Mine (3A-18) |
| `frontend/src/components/features/global-command-palette.tsx` | Stable — don't touch unless ticketed |
| **Everything else in your 7 areas** | **You** |
| Shared (both can edit, coordinate): `docs/ROADMAP-P3-CRITIC.md`, `backend/alembic/versions/*` | Both |

---

## 8. Migrations — numbering rule

The tracker has a line near the top: `Next migration number to reserve: 00NN`. Before you run `alembic revision`, bump it by 1 and commit alone: `chore(tracker): reserve migration 0010 for feedback table`. That reservation commit lands first; your actual migration commit follows. This prevents two people picking the same number and one having to rebase.

Always also verify against the filesystem before trusting the tracker:
```bash
ls backend/alembic/versions/ | sort | tail -1
```

If you forget and collide, fix is simple:
```bash
git pull --rebase
# rename your generated file 0010_foo.py → 0011_foo.py
# edit `down_revision = 'XXXX'` to point at the new previous head
```

---

## 9. When to ping (don't silently guess)

Send a message before proceeding if:
- You need to touch a file in the "Mine" column.
- You want to drop a ticket that isn't already on the DROPPED list.
- You're adding a new table — even for tickets already described, the schema might need a second look.
- You're adding a third-party dependency (npm package, Python package). We prefer building from what's already in the lock files.
- The acceptance criterion in the ticket doesn't match what you discover in the code. Code wins; flag it so the tracker can be updated.
- A test is flaky. Flaky is a bug — don't retry, investigate.
- You hit a migration collision you can't cleanly rebase.

Otherwise, work head-down. The tracker is the source of truth for status; async is fine.

---

## 10. Worked example: how a good ticket looks

Take `3B-75 Week-on-week diff on Receipts`:

1. Critic question: *does this change student behavior or support?* — Yes, it lets students see what changed, which drives follow-through. Proceed.
2. Claim: edit tracker to `- [~] #75 Week-on-week diff (teammate, feat/p3-75-wow-diff)`. Commit.
3. Read the touched files: `backend/app/api/v1/routes/receipts.py`, `frontend/src/app/(portal)/receipts/page.tsx`.
4. Backend: add a `compute_week_over_week` pure function at the top of `backend/app/services/receipts_service.py` that takes two `ReceiptSummary` dataclasses and returns a `WeekOverWeekDiff` dataclass. Unit-test it with 3-4 cases (improvement, regression, no-change, new-user-first-week).
5. Wire it into the existing `GET /api/v1/receipts` response behind a new field `week_over_week`. Add Pydantic schema. Log on compute: `log.info("receipts.wow_computed", user_id=str(user.id), has_prior_week=prior is not None)`.
6. Frontend: add a small component in `components/features/receipts-wow-card.tsx`. Server Component. Consumes the new field.
7. `pnpm tsc --noEmit && pnpm lint && pnpm test` clean. `uv run pytest -x && uv run mypy app/ && uv run ruff check .` clean.
8. Browser-verify: navigate to `/receipts`, snapshot, confirm card renders. Test edge case: user with no prior week — card should say "first week, come back next week" gracefully. Screenshot both states.
9. Read console messages. None red.
10. Update tracker: `- [x] #75 Week-on-week diff DONE (abc1234)`.
11. Commit once: `feat(receipts): 3B-75 week-on-week diff card`. Include code + schema + tests + tracker line. Done.

Total cost: ~90 minutes. One PR. Reviewable in ten. Zero coordination cost with my stream.

---

## 11. Cost discipline

You and I are running two parallel coders. Context is the single most expensive thing per ticket.

- **Don't re-read the whole ticket list every session.** Read only the ticket you're working on, plus the files it touches.
- **Don't paste giant file contents into chat.** Use file references (`path:line`) and let the reader open what they need.
- **Don't spin up an agent just to summarize a file you could Read.** Direct tool use beats delegating.
- **Finish the ticket before switching.** Context re-hydration is the hidden tax on "let me just quickly…" — it usually isn't quick.

---

## 12. When in doubt

Re-read the non-negotiables (section 3) and the critic question (section 4). If those don't give you an answer, ping. Better a 2-minute clarification than a 2-hour rework.

Ship clean, ship slow, ship once.
