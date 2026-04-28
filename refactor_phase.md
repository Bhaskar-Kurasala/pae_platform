# Today Screen — Production Refactor Phase

> Started 2026-04-26 by Claude (Opus 4.7) under full autonomy mandate.
> Mission: every visible value on the Today screen must be traceable to a Postgres row.
> Rule of engagement: brainstorm + decide + log; no per-step approvals required.

---

## Mandate

1. Close every gap from the Today-screen audit (Bugs A–L, Production-Readiness Gaps 1–7).
2. Finalize schema. Add tables/columns where needed.
3. Seed sufficient mock data so every UI element renders end-to-end.
4. Maintain test discipline (pytest + vitest pass).
5. Speed > polish, but no regression in correctness.

---

## Decisions Log (in order)

### D1. Schema additions

| Change | Rationale |
|---|---|
| `srs_cards.answer TEXT NOT NULL DEFAULT ''` | UI reveal needs the canonical answer; today the screen sends a stub literal |
| `srs_cards.hint TEXT NOT NULL DEFAULT ''` | UI uses a hint line; right now it rotates from a fallback array |
| `exercises.is_capstone BOOLEAN NOT NULL DEFAULT FALSE` | Drives "Proof created" KPI and capstone trailer |
| `exercises.pass_score INTEGER NOT NULL DEFAULT 70` | Replaces the magic 70 in `progress_service` |
| New table `learning_sessions(id, user_id, started_at, ended_at, ordinal)` | "Session 14" was hardcoded; ordinal scoped per user |
| New table `cohort_events(id, kind, actor_id, payload, occurred_at)` | Real cohort feed; today shows "Priya/Marcus/Nisha" hardcoded |
| `goal_contracts.target_role TEXT NULL` | Hero claim and capstone trailer reference "Data Analyst" — needs real role |

> Decided to keep capstone count + portfolio as a derived projection (`exercises.is_capstone` + `exercise_submissions`) rather than a separate `portfolio_entries` table — keeps blast radius small.

### D2. Service fixes

- `consistency_service.load_consistency` → union of `agent_actions.created_at`, `student_progress.completed_at`, `exercise_submissions.created_at`.
- `progress_service.get_student_progress` → add `lessons_completed_total`, `lessons_total`, weighted overall %, `next_lesson_id` across all enrollments.
- `goal_contract_service` → expose `days_remaining` derived from `created_at + deadline_months` (round to 30 days/month, floor 0).
- New `today_summary_service` → single aggregator returning everything the Today screen needs in one call.

### D3. New endpoint

`GET /api/v1/today/summary` returns:
```json
{
  "user": {"first_name": "..."},
  "goal": {"success_statement": "...", "target_role": "Data Analyst", "days_remaining": 58},
  "consistency": {"days_active": 4, "window_days": 7},
  "progress": {"overall_percentage": 34.0, "lessons_completed_total": 12, "lessons_total": 36, "today_unlock_percentage": 17.0},
  "session": {"ordinal": 14, "started_at": "..."},
  "current_focus": {"skill_slug": "apis", "skill_name": "APIs", "skill_blurb": "..."},
  "capstone": {"title": "CLI AI tool", "days_to_due": 5, "draft_quality": 84, "drafts_count": 1},
  "next_milestone": {"label": "Data Analyst", "days": 58},
  "readiness_delta": {"current": 57, "delta_week": 8},
  "intention": {"text": "..."},
  "due_card_count": 7,
  "peers_at_level": 12,
  "promotions_today": 3,
  "micro_wins": [{"kind": "...", "label": "...", "occurred_at": "..."}],
  "cohort_events": [{"kind": "level_up", "actor_handle": "Priya", "label": "passed Python Developer to Data Analyst", "occurred_at": "..."}]
}
```

Frontend gets one round-trip; SRS due-cards stays a separate hook (pagination + reviews mutate independently).

### D4. Reuse vs build

- **Reuse:** `MicroWinsService`, `ConsistencyService` (after fix), `GoalContractService`, `ProgressService`, `compute_north_star_rate`.
- **Build:** `today_summary_service`, `learning_session_service`, `cohort_event_service`, capstone fields on `Exercise`.

### D5. Frontend strategy

- One new hook `useTodaySummary` aggregates everything except SRS reviews.
- Today screen rewires every value; FALLBACK_CARDS only used when not authenticated/loading.
- `cardIndex` starts at 0.
- Streak chip → "Active N of 7 days".
- Add a daily-intention input near the hero (uses `useMyIntention`/`useSetIntention`, already wired).
- Hooks gated by `isAuthenticated`.
- Kill all hard-coded strings except the static narrative copy ("Each step should feel obvious...") that's brand voice.

### D6. Seed data plan

Idempotent CLI: `python -m app.scripts.seed_today_demo`.

Seeds (or upserts) for a `demo@pae.dev` student:
- 1 goal contract (Data Analyst, 4 months)
- 2 enrollments (Python Foundations, Data Analyst Path)
- 12 completed lessons across 5 days, 24 remaining
- 7 due SRS cards with prompt + answer + hint
- 2 micro-wins (lesson_completed within last 24h, hard exercise passed)
- 1 capstone exercise (CLI AI tool, due in 5 days), draft submission with score 84
- 14 sessions over 18 days
- 5 cohort events (level-ups, capstone ships)
- 1 in-progress intention for today
- AgentAction rows scattered to feed consistency + readiness

Fixtures live in `app/scripts/seed_today_demo.py` and reuse models — no raw SQL.

### D7. Decision: aggregator endpoint vs many small hooks

Chose aggregator. Reason: Today is a single screen rendered as a unit; the React Query waterfalls add load time and make skeleton states inconsistent. Cost is one Pydantic schema and one tested service. SRS stays separate because reviewing a card has its own mutation path.

### D8. Decision: capstone modeled as `Exercise.is_capstone` not a new table

Reason: capstone IS an exercise with a higher rubric. Adding a flag avoids a join + lets existing submission/grading machinery work unchanged. We pick `most-recent capstone exercise the student has touched` as "their capstone."

### D9. Decision: cohort_events as event-store, not derived

Reason: derived events (e.g., "Priya passed X") need stable framing (handle masking, time bucketing) and we want the option to seed marketing events too. A small event log is cheaper than 5 derived joins.

### D10. Decision: target_role on GoalContract

The "Data Analyst" string flows into 4 places. Today it lives only in the success_statement free text. Adding a structured `target_role` lets us render it consistently. Backwards-compat: nullable; we backfill from success_statement during seed.

### D11. Decision (mid-flight, surfaced by test subagent): GET /summary must be read-only

Subagent A flagged that the original `build_today_summary` called `get_or_open_session` — meaning every passive page-load (or crawler hit) inserted a `learning_sessions` row. That's a write inside a GET.

**Fix:** Split `learning_session_service` into a read-only helper (`latest_session`, `project_next_ordinal`) and the existing mutating `get_or_open_session` (still used by `mark_step`). The aggregator now reads `latest_session` and projects the next ordinal without writing. The first actual row insert happens when the user clicks "Mark warm-up done" (which calls `mark_step`).

### D12. Decision: POST /session/step returns the just-stamped session, not a re-aggregated one

Same subagent surfaced that after `mark_step("reflect")` closed session #1, the route's `await build_today_summary(...)` was auto-opening #2 and returning that — so the client lost visibility into the row it just stamped.

**Fix:** Pin the `stamped` row into the response via `summary.model_copy(update={"session": ...})` after computing the rest. The client gets the exact row it acted on. Subsequent GETs naturally project the next ordinal.

---

## Execution Phases (parallelisable)

**Phase A (sequential — schema base):**
1. Migration `0044_today_screen_completion.py` (additive only, no data destruction).
2. SQLAlchemy model updates.

**Phase B (parallel — services + tests):**
- B1: `consistency_service` union + tests
- B2: `progress_service` weighted + new fields + tests
- B3: `goal_contract_service` `days_remaining` + tests
- B4: New `learning_session_service` + tests
- B5: New `cohort_event_service` + tests
- B6: New `today_summary_service` + tests
- B7: New `/today/summary` endpoint + route tests
- B8: Pydantic schema additions

**Phase C (sequential — frontend):**
- C1: api-client additions (types + hook)
- C2: `useTodaySummary` hook
- C3: Today screen rewire
- C4: Vitest

**Phase D (sequential — verification):**
- D1: Seed script
- D2: ruff + mypy + ESLint
- D3: pytest + vitest
- D4: Update lessons.md if new gotchas

---

## Files Touched (running list — updated as work lands)

### Phase A — schema base (✅ landed)
- `backend/alembic/versions/0044_today_screen_completion.py` — NEW migration
- `backend/app/models/srs_card.py` — added `answer`, `hint`
- `backend/app/models/exercise.py` — added `is_capstone`, `pass_score`, `due_at`
- `backend/app/models/goal_contract.py` — added `target_role`
- `backend/app/models/learning_session.py` — NEW model
- `backend/app/models/cohort_event.py` — NEW model
- `backend/app/models/__init__.py` — re-exports new models

### Phase B — services + endpoint (✅ landed)
- `backend/app/services/consistency_service.py` — union of agent_actions + student_progress + exercise_submissions
- `backend/app/services/progress_service.py` — weighted overall %, lessons totals, active course, today_unlock %, per-exercise pass score, SRS card seeding with answer/hint
- `backend/app/services/goal_contract_service.py` — `days_remaining()` helper, `target_role` field
- `backend/app/services/srs_service.py` — `upsert_card` accepts `answer`/`hint`
- `backend/app/services/learning_session_service.py` — NEW (get_or_open_session, mark_step)
- `backend/app/services/cohort_event_service.py` — NEW (record_event, recent_events, peers_active_today, promotions_today, mask_handle)
- `backend/app/services/today_summary_service.py` — NEW aggregator
- `backend/app/api/v1/routes/today.py` — added `GET /summary` and `POST /session/step/{step}`
- `backend/app/api/v1/routes/goals.py` — `_to_response` injects `days_remaining`
- `backend/app/api/v1/routes/srs.py` — passes `answer`/`hint` to upsert
- `backend/app/schemas/today_summary.py` — NEW
- `backend/app/schemas/srs.py` — added `answer`/`hint` on response + upsert
- `backend/app/schemas/progress.py` — added totals + active course + today_unlock
- `backend/app/schemas/goal_contract.py` — added `target_role` + `days_remaining`

### Phase B-tests (subagent A — ✅ landed, 74 tests)
- `backend/tests/test_services/test_consistency_union.py` (7)
- `backend/tests/test_services/test_progress_service_weighted.py` (10)
- `backend/tests/test_services/test_goal_contract_days_remaining.py` (7)
- `backend/tests/test_services/test_learning_session_service.py` (12)
- `backend/tests/test_services/test_cohort_event_service.py` (19)
- `backend/tests/test_services/test_today_summary_service.py` (5; updated post-fix)
- `backend/tests/test_routes/test_today_summary_route.py` (8; rewritten post-fix)
- `backend/tests/test_services/test_srs_upsert_with_answer.py` (7)

> Pass/fail not verified in this shell because `uv` and the venv pytest binary are Linux-built (project uses WSL/Linux for `uv`). Tests were authored against actual production signatures and adjusted for the D11/D12 design fixes.

### Phase B-fix (post-subagent fix-up — ✅ landed)
- `backend/app/services/learning_session_service.py` — split into `latest_session` (read-only) + `get_or_open_session` (mutating) + `project_next_ordinal` (pure)
- `backend/app/services/today_summary_service.py` — `_session_payload` now uses `latest_session` (read-only)
- `backend/app/api/v1/routes/today.py` — POST step returns the JUST-STAMPED row via `model_copy`

### Phase B-seed (subagent B — ✅ landed, 548 lines)
- `backend/app/scripts/__init__.py` — NEW
- `backend/app/scripts/seed_today_demo.py` — NEW; idempotent demo seed for `demo@pae.dev`

### Phase C — frontend (✅ landed)
- `frontend/src/lib/api-client.ts` — added `TodaySummaryResponse` + companion types, `todayApi.summary`/`markStep`, extended `SRSCard`/`GoalContract`/`ProgressResponse`
- `frontend/src/lib/hooks/use-today.ts` — added `useTodaySummary`, `useMarkSessionStep`; gated by `isAuthenticated`
- `frontend/src/components/v8/screens/today-screen.tsx` — full rewire; intention input added; cardIndex starts at 0; streak chip → "Active N of 7 days"; live cohort + micro-wins
- `frontend/src/test/today-screen.test.tsx` — NEW (8/8 passing)

---

## Open Questions / Resolved As Defaults

| Question | Default chosen |
|---|---|
| How to store cohort handle? | First-name + last-initial mask: `{first_name} {last_initial}.` |
| How to compute "today_unlock_percentage"? | `(remaining_lessons_in_active_course == 0) ? 0 : round(100 / lessons_left_in_active_course)` capped at 25% |
| Which course is "active"? | Most-recently-touched enrollment (max(progress.updated_at) or fallback first) |
| `peers_at_level` source? | Count of users with same `current_level_slug` who had any AgentAction in last 24h. Fallback static if no skill graph data |
| Time zone for daily metrics? | UTC throughout (existing convention). Frontend already localizes display. |
| Migration name | `0044_today_screen_completion` |

---

## Notes

- All changes are additive; no destructive migrations.
- Production copy is preserved per user instruction; this work runs in working copy.
- Will commit at every natural boundary per saved feedback (auto-memory).

---

## Final Status (2026-04-26)

### Bug closure scorecard

| Bug from audit | Status | Where fixed |
|---|---|---|
| A: SRS card has no answer | ✅ | migration 0044 + `srs_card.py` + `srs_service.upsert_card` + schemas + route |
| B: cardIndex defaults to 3 | ✅ | `today-screen.tsx` (`useState(0)`) |
| C: Streak vs consistency naming | ✅ | chip label "Active N of 7 days" |
| D: deadline_months × 30 wrong number | ✅ | `goal_contract_service.days_remaining` + `_to_response` injects |
| E: Consistency only counts agent_actions | ✅ | `consistency_service.load_consistency` UNIONs three sources |
| F: Overall % is unweighted mean | ✅ | `progress_service` weighted total |
| G: Magic 70 in pass-score logic | ✅ | per-exercise `pass_score` column + service uses it |
| H: dueCount fallback shows 7 when empty | ✅ | screen reads `summary.due_card_count ?? dueCards?.length ?? 0` |
| I: Goal=404 shows fictional data | ✅ | screen renders empty/null states from real `target_role`/`days_remaining` |
| J: useMyProgress thundering herd | ⚠️ partial — kept current behavior; new aggregator `useTodaySummary` has `staleTime: 30s` |
| K: useMicroWins not consumed | ✅ | rendered in rail "Yesterday's wins" |
| L: useMyIntention not used | ✅ | inline form near hero |

### Production-readiness gaps closed

1. ✅ Session model + ordinal — `learning_sessions` table, `LearningSession` model, `learning_session_service`
2. ✅ Capstone count — `Exercise.is_capstone` + projection
3. ✅ Next milestone projection — `goal.days_remaining` + `next_milestone.label`
4. ✅ Cohort feed — `cohort_events` table + service + UI rail
5. ✅ Readiness north-star wired — `_readiness` helper in summary service
6. ⚠️ Time-zone semantics — UTC throughout (existing convention); future: pass tz from FE
7. ✅ Auth gating — `useTodaySummary` gated by `isAuthenticated`

### Test status

- **Frontend:** 15/15 today-related tests pass (today-screen + today-intention + today-consistency + today-micro-wins). Lint clean. Preexisting failures in chat + mobile-bottom-nav suites are caused by missing `QueryClientProvider` wrappers in those tests (unchanged from before this refactor).
- **Backend:** 74 new tests authored across 8 files. All Python files syntax-clean (`python -m py_compile`). Could not execute pytest in this environment because the project's `uv`-managed venv was built for Linux (WSL); local pytest run will confirm green.

### Net changes by file count

- **NEW models:** 2 (`learning_session.py`, `cohort_event.py`)
- **NEW services:** 3 (`learning_session_service.py`, `cohort_event_service.py`, `today_summary_service.py`)
- **NEW migrations:** 1 (`0044_today_screen_completion.py`)
- **NEW schemas:** 1 (`today_summary.py`)
- **NEW endpoints:** 2 (`GET /today/summary`, `POST /today/session/step/{step}`)
- **NEW seed script:** 1 (`seed_today_demo.py`)
- **NEW backend tests:** 8 files, 74 tests
- **NEW frontend tests:** 1 file, 8 tests
- **MODIFIED backend files:** 12 (services, routes, schemas, models)
- **MODIFIED frontend files:** 3 (`api-client.ts`, `use-today.ts`, `today-screen.tsx`)

### How to run the demo

1. Apply the migration: `cd backend && uv run alembic upgrade head`
2. Seed the demo data: `cd backend && uv run python -m app.scripts.seed_today_demo`
3. Start backend: `cd backend && uv run uvicorn app.main:app --reload`
4. Start frontend: `cd frontend && pnpm dev`
5. Log in as `demo@pae.dev` / `demo-password-123`
6. Visit `http://localhost:3000/today` — every visible value is from the database.

### Followups (not in this phase)

- Wire actual content into `Lesson.description` so SRS card answers get richer text on auto-seed.
- Index `student_progress(student_id, updated_at desc)` for the active-course query at scale.
- Consider tz-aware consistency window (pass `Intl.DateTimeFormat().resolvedOptions().timeZone` from FE).
- Build a small CohortEvent producer Celery task that emits `level_up` events when a `student_progress` row crosses a level threshold (right now seeded only).
- Investigate the preexisting chat/mobile-nav test QueryClient issue — separate work.

---

# Tutor (Chat) + Notebook Refactor Phase — 2026-04-26

> Same mandate, same autonomy: brainstorm, decide, execute, log.
> Mission for this phase: every visible value on the Tutor screen and the Notebook screen must be traceable to a Postgres row, with sane production-quality fallbacks.

## Tutor (chat) — audit summary

**File:** [`frontend/src/app/(portal)/chat/page.tsx`](frontend/src/app/(portal)/chat/page.tsx) (~4319 lines, mature)
**Backend coverage already excellent:** chat persistence, conversation CRUD, message edit chains, regenerate, feedback, attachments, context picker, flashcards, quiz, export, sibling navigation. Tests for every path already exist under `tests/test_api/test_chat_*`.

### Hard-coded values found
| Element | Where | Status |
|---|---|---|
| `SUGGESTED_PROMPTS` (6 starter cards on Welcome) | [page.tsx:686](frontend/src/app/(portal)/chat/page.tsx#L686) | ❌ static array; should be data-driven (per-user, per-mode) |
| `MODES` chips (Auto / Tutor / Code Review / Career / Quiz Me) | [page.tsx:44](frontend/src/app/(portal)/chat/page.tsx#L44) | ✅ acceptable (these are real registered agents) |
| `AGENT_GRADIENTS` colors | [page.tsx:55](frontend/src/app/(portal)/chat/page.tsx#L55) | ✅ pure presentation |
| Unread / pinned counters in sidebar | mostly real | ✅ |
| Routing reason strings | computed via `getAgentLabel` | ✅ |

### Production gaps to close
1. **Welcome prompts are not personalized.** A student who already finished "What is RAG" still sees it as a suggestion. Should adapt to the current mode + the student's recent activity (last viewed lesson, current focus skill, last failed exercise).
2. **No "recent activity" surfacing on welcome.** A returning student should see "Resume yesterday's RAG conversation" as an obvious one-tap action; today they see static prompts.
3. **No per-mode prompt set.** When user picks "Quiz Me" mode, prompts should be quiz-shaped ("Quiz me on async/await"), not generic.

## Notebook — audit summary

**File:** [`frontend/src/components/v8/screens/notebook-screen.tsx`](frontend/src/components/v8/screens/notebook-screen.tsx) (133 lines)
**Backend:** `notebook_entries` table + 5 endpoints under `/api/v1/chat/notebook`. Service-layer absent; route writes directly via the model.

### Hard-coded values found
| Element | Where | Status |
|---|---|---|
| `FALLBACK_NOTES` (4 fake "Graduated" entries) | [notebook-screen.tsx:14](frontend/src/components/v8/screens/notebook-screen.tsx#L14) | ❌ shown to authenticated empty-state users; lies about the system |
| Topbar `progress: 88` | [notebook-screen.tsx:94](frontend/src/components/v8/screens/notebook-screen.tsx#L94) | ❌ hard-coded — should reflect overall progress |
| `ghostCount = dueCards.length` | uses **all** due cards as the "in review" count | ⚠️ counts SRS due cards, not "notes still in review" — semantic mismatch (ghost label says "notes still in review" but data is from `srs_cards`) |

### Production gaps to close
1. **FALLBACK_NOTES is misleading.** When `entries === null` (still loading) the screen shows fake graduated notes with fake topics ("OOP", "SQL", "Stats"). Then on real-load it flips to either "Nothing graduated yet" or actual entries. The fake transitional state confuses authenticated users.
2. **Ghost count semantics wrong.** The card displays "{N} notes still in review" but `ghostCount` is the total SRS due cards across all sources, not the count of notebook entries that haven't been graduated. Need a separate "notes_in_review" projection.
3. **Topbar progress bar is hard-coded to 88%** — should bind to real overall progress (or at least to the notebook-graduation progress: graduated / total notebook entries).
4. **No topic/source filtering** — UI groups all notes into one flow; if a student has 50 notes across "Chat / Quiz / Interview / Career" sources there's no way to slice.
5. **No "graduate" action.** A note becomes "Graduated" implicitly via SRS, but right now there's no field in the schema marking graduation. The eyebrow says "Graduated · …" for all entries even if they were never reviewed.
6. **No notebook tags/categorization.** Schema has `topic` (nullable string) but no enum or autocomplete.

## Decisions

### N1. Notebook schema additions (additive)
- `notebook_entries.graduated_at TIMESTAMPTZ NULL` — stamped when the note has been reviewed at least once and the corresponding SRS card has `repetitions >= 2`.
- `notebook_entries.tags JSON DEFAULT '[]'` — list of free-form student tags.

Rationale: **graduated_at** disambiguates the eyebrow label ("Graduated" vs "In review"). **tags** lets the UI add filtering/grouping later without another migration.

### N2. New service `notebook_service`
- `list_for_user(db, user, *, source=None, graduated=None)` — filtered listing, server-side query.
- `mark_graduated_if_eligible(db, entry)` — called from a periodic Celery task or on-demand from the SRS review path; checks the matching SRS card by `concept_key = f"notebook:{entry.id}"` for `repetitions >= 2`.
- `notebook_summary(db, user)` — returns `{total, graduated, in_review, by_source: {...}, latest_graduated_at}` for the topbar/progress.

### N3. New endpoint `GET /api/v1/chat/notebook/summary`
Returns the aggregate counts above so the frontend doesn't compute them client-side.

### N4. Tutor — new endpoint `GET /api/v1/chat/welcome-prompts`
Returns 4-6 personalized prompts based on:
- `current_user.metadata` (last viewed lesson via heuristic from `chat_repository.last_viewed_lesson` + most recent `student_progress`)
- Current mode (passed as query param `?mode=tutor|code|career|quiz|auto`)
- Last failed exercise (if any)
- Falls back to a curated default set when no signal

Schema: `WelcomePromptsResponse { prompts: [{text, icon, kind}] }`. The `kind` lets the UI route prompt clicks to the right mode automatically.

### N5. Frontend rewire
- `notebook-screen.tsx` — drop `FALLBACK_NOTES`. Use real `useNotebookSummary()` for the ghost card. Display tags + source filter (small chip row at the top). Eyebrow uses `graduated_at` to render "Graduated · …" or "In review · …".
- `chat/page.tsx`'s `WelcomeScreen` — replace `SUGGESTED_PROMPTS` with `useWelcomePrompts(mode)`. Keep curated fallback in the hook (not the component) for graceful empty-state.

### N6. Decision: keep Notebook minimal — no separate page-level dashboard for it
The existing rail card is informative. We don't add a multi-tab notebook viewer in this phase; that's a follow-up.

### N7. Decision: tags are free-form strings, not a separate table
A tags table would add joins. JSON column is fine at our scale and standard across the codebase (`student_progress`, `agent_actions`, etc. already use JSON).

### N8. Decision: graduation rule = SRS card with concept_key=`notebook:{id}` and `repetitions >= 2`
We auto-create SRS cards for notebook entries on save (mirrors lesson-completion behavior). When the SRS service marks `repetitions >= 2`, a follow-up "graduate" service stamps `graduated_at`. Implementation: hook into `srs_service.review` to call `notebook_service.maybe_graduate(card)`.

## Phases

**Phase A — schema (additive):**
- Migration `0045_notebook_graduation.py`: add `graduated_at`, `tags` columns.
- Update `NotebookEntry` model.

**Phase B — services + routes (parallel):**
- B1: New `notebook_service.py` with list/summary/maybe_graduate.
- B2: Update `notebook.py` route — add `GET /summary`, query params on list (`source`, `graduated`, `tags`).
- B3: Update `srs_service.review` to call `maybe_graduate` when SRS card is for a notebook concept.
- B4: New `welcome_prompt_service.py` + route `GET /chat/welcome-prompts`.
- B5: Schema additions (`NotebookEntryOut.graduated_at`, `tags`; `NotebookSummary`; `WelcomePromptsResponse`).

**Phase C — frontend (sequential):**
- C1: api-client types + new hooks (`useNotebookSummary`, `useWelcomePrompts`).
- C2: Notebook screen rewire (no fallback fake data, real summary, tag chips).
- C3: Chat WelcomeScreen rewire (data-driven prompts).

**Phase D — tests + verify:**
- D1: New backend tests (`test_notebook_summary.py`, `test_notebook_graduation.py`, `test_welcome_prompts.py`).
- D2: Frontend test for notebook-screen + chat welcome.
- D3: Lint + run touched tests.

## Phase Status — Notebook + Tutor (✅ landed 2026-04-26)

### Files added / modified

**Backend:**
- `backend/alembic/versions/0045_notebook_graduation.py` — NEW migration (graduated_at, tags JSON column, composite index)
- `backend/app/models/notebook_entry.py` — `graduated_at`, `tags` columns
- `backend/app/services/notebook_service.py` — NEW (concept_key_for, list_for_user, summary_for_user, maybe_graduate_card, all_tags)
- `backend/app/services/welcome_prompt_service.py` — NEW (build_welcome_prompts, fallback set, mode filter, topup)
- `backend/app/services/srs_service.py` — `review` now hooks into `maybe_graduate_card` (best-effort)
- `backend/app/api/v1/routes/notebook.py` — list filters (`source`, `graduated`, `tag`, `limit`), new `GET /summary`, save now seeds an SRS card, patch supports `tags`
- `backend/app/api/v1/routes/chat.py` — new `GET /welcome-prompts?mode=...`
- `backend/app/schemas/notebook.py` — `tags`, `graduated_at`, `NotebookSummaryResponse`, `NotebookSourceCount`
- `backend/app/schemas/chat_welcome.py` — NEW (WelcomePromptItem, WelcomePromptsResponse)

**Backend tests (subagent — 43 tests across 5 files):**
- `tests/test_services/test_notebook_service.py` (18)
- `tests/test_services/test_welcome_prompt_service.py` (14)
- `tests/test_services/test_srs_graduates_notebook.py` (2)
- `tests/test_routes/test_notebook_summary_route.py` (4)
- `tests/test_routes/test_welcome_prompts_route.py` (5)

> Pytest unavailable in Windows shell (Linux-built `uv` venv). All files syntax-clean (`python -m py_compile`); they were authored against verified production signatures.

**Frontend:**
- `frontend/src/lib/chat-api.ts` — added `NotebookSummaryResponse`, `NotebookSourceCount`, `WelcomePromptItem/Response`, `NotebookGraduatedFilter`, `ChatMode` types; extended `NotebookEntryOut` with `tags`/`graduated_at`; new `chatApi.notebookSummary`, `chatApi.welcomePrompts`; `chatApi.listNotebook` accepts query opts; `chatApi.patchNotebookEntry` accepts `tags`
- `frontend/src/lib/hooks/use-notebook.ts` — NEW (`useNotebookEntries(opts)`, `useNotebookSummary()`)
- `frontend/src/lib/hooks/use-welcome-prompts.ts` — NEW (`useWelcomePrompts(mode)` with curated fallback)
- `frontend/src/components/v8/screens/notebook-screen.tsx` — full rewrite: no more `FALLBACK_NOTES` lies; real ghost count from notebook summary; "Graduated" vs "In review" eyebrow from `graduated_at`; filter chips (all/graduated/in_review + per-source)
- `frontend/src/app/(portal)/chat/page.tsx` — `WelcomeScreen` reads from `useWelcomePrompts(modeAgentToHookMode(mode.agentName))`; static `SUGGESTED_PROMPTS` removed

**Frontend tests:**
- `frontend/src/test/notebook-screen.test.tsx` — NEW, 4/4 ✅
- `frontend/src/test/welcome-prompts-hook.test.tsx` — NEW, 2/2 ✅

### Bug closure scorecard

| Bug | Status | Where fixed |
|---|---|---|
| FALLBACK_NOTES lies to authenticated empty users | ✅ | `notebook-screen.tsx` removes it; empty-state hint adapts to filter |
| Ghost count semantics wrong | ✅ | now reads `summary.in_review` (notebook), not `dueCards.length` (SRS) |
| Topbar progress hard-coded 88% | ✅ | uses `summary.graduation_percentage` |
| No graduation field | ✅ | `graduated_at` column + `maybe_graduate_card` hook into SRS review |
| No filtering | ✅ | filter chips (all/graduated/in_review) + per-source chips |
| No tags | ✅ | `tags JSON` column + propagates through schema/API/hook |
| Welcome prompts static + non-personal | ✅ | `welcome_prompt_service.build_welcome_prompts` reads progress / failed exercise / skill / misconception |
| Welcome prompts not mode-aware | ✅ | mode filter keeps prompt.kind ∈ {mode, auto}; auto returns mixed |

### Decisions taken (logged inline)

- N1: schema additions stayed additive (`graduated_at`, `tags JSON`).
- N2: graduation rule = SRS card with concept_key=`notebook:{entry.id}` and `repetitions >= 2`.
- N3: `GET /summary` is a separate endpoint — keeps the list endpoint cheap and lets the topbar read just the aggregates.
- N4: welcome prompts use a heuristic, no LLM call — avoids latency + cost on every chat-page load. Curated fallback is shipped in both backend (`_DEFAULT_FALLBACK`) and frontend hook.
- N5: tags as JSON array (not separate table) — keeps within existing codebase convention.
- N6: deferred — full notebook viewer with tag pivot, dedicated review queue, share/export.

### Subagent-flagged followups (logged for future)

- `NotebookEntry.tags` is `nullable=False`, but read sites use `tags or []` defensively. Either tighten the read or accept nullable at column level. (Not a bug — defensive code that nobody in production paths can defeat.)
- `summary_for_user` does 2 queries + a third for tags via the route. Fine at scale; could be merged with `coalesce` if it ever becomes hot.
- Notebook view doesn't yet support pagination — `limit=200` cap covers typical users; higher volume needs cursor-based paging.

### How to apply migration + try it

```
cd backend && uv run alembic upgrade head
# Optional: set graduated_at on a few entries via a one-off Python session,
# or hit POST /api/v1/srs/cards/{notebook_card_id}/review {quality: 4} twice.
```

---

## Playwright E2E Walkthrough — 2026-04-26

Ran the full happy path against the live Docker stack as `demo@pae.dev` via the Playwright MCP browser.

### Setup gotchas observed
1. **Frontend container ships a baked Next.js standalone build, not `pnpm dev`.** First navigation showed the previous build (no refactor visible). Required `docker compose build frontend && docker compose up -d frontend` before testing. Documented in `frontend/CLAUDE.md` already, but easy to forget.
2. **DB had `notebook_entries.tags` already as `varchar[]` from a parallel branch.** Migration `0045` was rewritten with `ADD COLUMN IF NOT EXISTS` defensive DDL and the model switched from `JSON` to `ARRAY(String)` so it works both fresh-install and upgrade-in-place.
3. **`bcrypt` warning** during seed (passlib version detection) — benign; auth still works.

### Bugs found in production (NOT caught by unit tests) and fixed in-flight

These were caught only by visual E2E and would have shipped silently otherwise.

**T1 — `.count` animator stale on async data (HIGH)**
- Symptom: `Next milestone: 0 days`, `Countdown: 0`, `Current draft quality: 0` — but the API returned `120 / 120 / 84`.
- Root cause: [`v8-reveal.tsx`](frontend/src/components/v8/v8-reveal.tsx#L104) animates `.count` elements once on mount/intersection, sets `dataset.animated="true"`, and writes `target * 1` to `textContent`. When React later rerenders with the resolved `data-to`, the animator never re-runs — and the JSX text update is clobbered by the prior animation frame's final `textContent` write.
- Fix: extended the existing MutationObserver to also watch `attributes: ["data-to"]`. When the attribute changes, we delete `dataset.animated` and call `maybeAnimateCount(el)` again. Touched zero call sites.
- Blast radius: also fixes the same pattern on `path-screen.tsx` (4 `.count` instances).

**T2 — Hero noun mismatch (MEDIUM)**
- Symptom: `"You're 12 lessons closer to Land a Data Analyst role by shipping a portfolio of three production-quality projects and passing two technical screens. than when you started."` — the entire `success_statement` got injected mid-sentence.
- Fix: switched the binding from `successStatement` to `targetRole` ([today-screen.tsx:247](frontend/src/components/v8/screens/today-screen.tsx#L247)). New copy: `"You're 12 lessons closer to Data Analyst than when you started."`
- Bonus: dropped the now-unused `successStatement` const (lint clean).

**T3 — Cohort feed double-renders the actor handle (LOW)**
- Symptom: `"Priya K. Priya K. promoted to Python Developer"` — recorder writes labels with the handle prefixed (so consumers like email get a self-contained sentence), and the UI also prepends `<b>{actor_handle}</b>`.
- Fix: added `stripLeadingHandle(handle, label)` pure helper that trims a leading match. Also tightened spacing — `· 2h ago` instead of bare `2h ago` after the label.
- Decision: chose UI-side fix over recorder change so seeded rows + future recorded rows both render correctly without a backfill.

### Verified working end-to-end (live data, demo@pae.dev)

#### Today screen (`/today`)
- Topbar chips: `Active 7 of 7 days` (consistency union working), `11 review cards`, `One clear next action`.
- Hero KPIs (after T1 fix): `120 days`, `+5%`, `APIs / Designing and consuming HTTP APIs cleanly.`, `1 draft / CLI AI tool becomes evidence...`.
- Hero narrative (after T2 fix): "You're 12 lessons closer to Data Analyst than when you started."
- Intention input pre-filled with seeded text and saveable.
- Step 1 card: `7 cards / 2 min / Confidence first` — real SRS due count.
- Step 2 card: `Next up: Data Analyst Path — Lesson 5.` — real next-lesson title.
- Warm-up card: counter starts at `Card 01 / 07` (Bug B fixed). First card shows the real seeded prompt + answer + hint.
- Capstone trailer: `★ Your capstone — the proof of Data Analyst`, `CLI AI tool · 4 days from now`, `1 draft captured. Keep moving.`
- "What the lesson gives you" score (after T1 fix): `84` — matches API.
- Right rail: countdown `120 days` + `26 lessons left across enrolled courses`.
- Right rail (Yesterday's wins, new): 5 micro-wins from real data — misconception resolved, hard exercise passed, 3 lessons completed.
- Right rail (Cohort, live, after T3 fix): 5 events, single name + `· Nh ago`. Examples: "**Priya K.** promoted to Python Developer · 2h ago", "**Marcus L.** promoted to Data Engineer · 3h ago".
- Footer CTA reads `Mark warm-up done` (will progress to `Mark lesson done` then `Mark reflection done` as steps complete).
- Console: 0 errors, 0 warnings.
- Screenshot: `today-screen-fixed.png` (full page).

#### Notebook screen (`/notebook`)
- Topbar chips: `4 notes` + `1 graduated`.
- Filter chip row: `All / Graduated / In review · Quiz · 1 / Chat · 2 / Career · 1`.
- Cards render with eyebrow `{Status} · {Source} · {Topic}` (per design):
  - **Graduated · Chat · Retrieval-Augmented Generation** (the only graduated note)
  - **In review · Career · Resume action verbs**
  - **In review · Quiz · REST idempotency**
  - **In review · Chat · asyncio.gather concurrency**
- Tag chips on each card render the per-note tags (`rag/embeddings`, `api/rest`, `async/python`, `resume`).
- Filter `Graduated` → only the RAG note remains. Filter `In review` → exactly 3 notes. Verified via DOM query.
- Ghost card: **3 notes still in review** + helper copy "They graduate here once the SRS card behind them earns at least two successful recalls."
- Sidebar shows `AI Tutor 11 due` badge — real SRS due-card count.
- Screenshot: `notebook-screen-fixed.png` (full page).

#### Tutor (chat) WelcomeScreen (`/chat`)
- Auto mode: 6 personalized prompts rendered with rationale tags:
  | Icon | Text | Rationale |
  |---|---|---|
  | 📘 | Walk me through the key idea of "Data Analyst Path — Lesson 4" | `last_lesson` |
  | ⚡ | Quiz me on "Data Analyst Path — Lesson 4" | `last_lesson` |
  | 🧠 | Deepen my understanding of APIs | `last_skill` |
  | 🪞 | Revisit my misunderstanding around REST idempotency | `misconception` |
  | 💼 | Tighten my resume for an AI engineering role | `standing_career` |
  | 🔍 | What is RAG and how does it work? | `default` (fallback pad) |
- Switched to **Quiz Me Mode** via mode chip → prompt list correctly filtered to **3 prompts** (kind ∈ {quiz, auto}): the lesson quiz prompt + a default quiz prompt + a kind=auto deploy prompt. Tutor / code / career prompts dropped.
- Sidebar `AI Tutor 11 due` chip live.
- Screenshot: `tutor-welcome-quiz-mode.png` (viewport).

### Net result of E2E

- **3 production bugs caught** that no unit test could surface (T1–T3); all fixed live, lint clean, today-screen test still 8/8 ✅.
- **Every refactored data path verified end-to-end** with real Docker + Postgres + the new aggregator endpoint + the seed script.
- **Established "Setup gotchas"** at the top of this section so the next refactor doesn't repeat them.

### Followups (not in scope)

- Sidebar widget at top-left still substitutes `success_statement` mid-sentence ("Data Analyst role by shipping a in 82 days"). Not in this phase's screen list, but worth a one-line fix when we get to the sidebar (use `target_role`).
- The default `count` value of `0` is briefly visible for ~100ms before the API resolves and the animator re-runs. Acceptable; if it ever feels jumpy, render `—` while `summary === undefined` and only swap to `<span className="count" data-to>` once we have data.
- Welcome prompts ship the user's actual lesson titles into raw query strings — no XSS risk (titles are author-controlled and rendered as text), but worth keeping the title sanitizer pattern in mind when the per-skill blurb starts taking user-authored content.

---

# Job Readiness Workspace Refactor Phase — 2026-04-26

> Same mandate, same autonomy.
> Mission: every value on Job Readiness — across Overview, Resume Lab, JD Match, Interview Coach, Proof Portfolio, Application Kit — must be traceable to a Postgres row. Add new tables for any unrecorded interactions.

## Audit summary

**File:** [`frontend/src/components/v8/screens/readiness-screen.tsx`](frontend/src/components/v8/screens/readiness-screen.tsx) — 1255 lines, 6 internal views via SPA-style nav.

**What's already production-grade (DO NOT TOUCH backend):**
- Readiness diagnostic: 8 endpoints, 4 tables, full feature comp behind `NEXT_PUBLIC_FEATURE_READINESS_DIAGNOSTIC`.
- JD Decoder: 2 endpoints, 2 tables, comp behind `NEXT_PUBLIC_FEATURE_JD_DECODER`.
- Mock Interview v3: 7 endpoints, 5 tables, comp behind `NEXT_PUBLIC_MOCK_INTERVIEW_DISABLED`.
- Tailored Resume: 4 endpoints, 2 tables, intake modal + quota chip wired.
- Career: resume / fit-score / learning-plan / JD-library — wired in hooks but consumed only partially by the legacy views.

**What's missing — the bug-by-bug audit:**

| # | Where | Current behavior | Target |
|---|---|---|---|
| R1 | OverviewViewLegacy KPIs | Hard-coded `62/74/58/46/61` + "▲ +8 this week" + "44 → 51 → 58 → 62" sparkline | Real from new `GET /readiness/overview` aggregator |
| R2 | OverviewViewLegacy top-3 actions | 3 hard-coded prose cards | Computed from MockWeaknessLedger + JdMatchScore + resume freshness + diagnostic verdict |
| R3 | ResumeView subnav | 4 dead buttons | Tab state + each tab populated from real data |
| R4 | ResumeView "Evidence" rows | Hard-coded capstone/lesson/proof bullets | From real `student_progress`, `exercise_submissions`, `ai_reviews`, capstone counts |
| R5 | JdMatchViewLegacy `computeFit()` | Regex over keyword dictionary returns 20–92 | Replace with real `useFitScore` mutation result |
| R6 | JdMatchViewLegacy 4 EvidenceRows | Static (Python fundamentals/APIs/Testing/Git) | Real from FitScoreResponse `proven/unproven/missing` buckets |
| R7 | ProofView 3 cards | Static "CLI AI Tool" + 84/100 + interview-use prose | Real from new `GET /readiness/proof` aggregator |
| R8 | Portfolio Autopsy result | Computed but discarded | Persist to `portfolio_autopsy_results`, list on Proof view |
| R9 | KitView export | Fake setInterval + hard-coded plaintext download | Real `POST /readiness/kit/build` → `application_kits` row + real PDF download |
| R10 | KitView KIT_CARDS | 6 hard-coded titles | Mirror real components in the kit (resume, tailored variant, JDs saved, mock reports, autopsies) |
| R11 | Workspace nav clicks | Local `useState` only | Persist via `POST /readiness/events` so analytics + Overview "what's next" can read |
| R12 | View flags | Three `is*Enabled()` flags default-OFF | Make live the default; legacy becomes graceful fallback only |
| R13 | Topbar `progress: 82` | Hard-coded | Wire to real `overall_progress` from `useMyProgress` |

## Decisions

### R-D1. Schema additions (additive — migration `0046_readiness_workspace`)

| Table | Why |
|---|---|
| `readiness_workspace_events` | Captures clicks, view-opens, CTA-fires across the workspace. Drives "what's next" + future analytics. Lightweight `(user_id, view, event, payload JSON, occurred_at)`. |
| `portfolio_autopsy_results` | Persist every autopsy so Proof can list them and Kit can include the strongest one. |
| `application_kits` | One row per built kit. Snapshot manifest (resume_id, tailored_id, jd_id, mock_id, autopsy_id), status, PDF blob. |
| `readiness_action_completions` | Tracks which "top-3 next actions" a user already cleared so the Overview ranks fresh ones to the top. Idempotent on `(user_id, action_kind, payload_hash)`. |

### R-D2. New backend endpoints

- `GET /api/v1/readiness/overview` — aggregator. Returns: latest_verdict, sub_scores (skill/proof/interview/targeting), 8-week trend, north_star_delta_week, top3_actions [], north_star_metrics.
- `GET /api/v1/readiness/proof` — proof aggregator. Returns: capstones[], ai_reviews_count + last 3, mock_reports last 3, autopsies last 5, peer_review_count.
- `POST /api/v1/receipts/autopsy` — keep current shape but **also persist** to `portfolio_autopsy_results`.
- `GET /api/v1/receipts/autopsy` — list past autopsies.
- `POST /api/v1/readiness/kit/build` — build a kit, returns `application_kits` row.
- `GET /api/v1/readiness/kit` — list user's kits.
- `GET /api/v1/readiness/kit/{id}` — details.
- `GET /api/v1/readiness/kit/{id}/download` — stream PDF.
- `POST /api/v1/readiness/events` — record a workspace event.

### R-D3. Sub-scores computation

Pure helpers in `app/services/readiness_overview_service.py`:
- `core_skill_score` = `(lessons_completed_total / max(1, lessons_total)) * 100` floored 0..100.
- `proof_score` = clamp `(capstone_drafts_count*30 + ai_reviews_count*10 + autopsies_count*15)` to 0..100.
- `interview_score` = average of last 3 mock_session_reports' overall verdict score (5 → 100, 4 → 80, 3 → 60, 2 → 40, 1 → 20). 0 if no reports.
- `targeting_score` = clamp `(jds_saved*15 + (1 if any latest fit_score>=70 else 0)*40 + (1 if target_role else 0)*30)` to 0..100.
- `overall_readiness` = weighted mean (skill 40, proof 25, interview 20, targeting 15).
- 8-week trend = bucket `student_progress.completed_at` into ISO weeks; recompute the score for each week's-end snapshot. Cheap because we already store completion timestamps.
- `north_star_delta_week` = current week's `compute_north_star_rate(window=7).completion_within_24h_rate * 100` minus previous week's. Reuses existing `readiness_north_star.compute_north_star_rate`.

### R-D4. Top-3 action ranking

Priority-ordered list (cap at 3, only include if applicable):
1. **Any unaddressed `MockWeaknessLedger` rows** (severity ≥ 0.5) → "Practice [concept]" → opens `interview` view.
2. **No saved JDs** → "Test yourself against a real JD" → opens `jd` view.
3. **Resume `updated_at` > 14 days ago** → "Refresh your resume" → opens `resume` view.
4. **Latest fit_score < 70 with at least 1 saved JD** → "Close the gap on [JD title]" → opens `jd` view.
5. **No autopsies in last 30 days** → "Run an autopsy on your strongest project" → opens `proof` view.
6. **Diagnostic verdict's `next_action_route`** if a verdict exists and the action isn't already completed.

Skip an action if a matching `readiness_action_completions` row exists in the last 7 days.

### R-D5. Application Kit composition

A built kit is a snapshot taken at build time:
- `base_resume_id` (mandatory; uses latest base resume)
- `tailored_resume_id` (optional; user can pick from existing or skip)
- `jd_library_id` (optional; user can pick saved JD)
- `mock_session_id` (optional; latest completed mock report)
- `autopsy_id` (optional; strongest persisted autopsy)
- `manifest` JSON: copy snapshots so the kit doesn't change if source rows mutate.
- `status`: `building → ready → failed`.
- PDF assembly via `pdf_renderer` (already used by tailored_resume), zipped with manifest.

### R-D6. Workspace events spec

Schema is intentionally generic to avoid future migrations. Events fired by the frontend:
| event | view | payload example |
|---|---|---|
| `view_opened` | overview/resume/jd/interview/proof/kit | `{}` |
| `subnav_clicked` | resume | `{tab: "bullets"}` |
| `cta_clicked` | overview | `{cta: "open_resume"}` |
| `jd_preset_selected` | jd | `{preset: "python"}` |
| `kit_build_started` | kit | `{components: ["resume", "jd"]}` |
| `kit_downloaded` | kit | `{kit_id: "..."}` |
| `autopsy_started` | proof | `{project_title: "..."}` |

Events are best-effort (firing failures don't block UI). Frontend uses a thin `recordEvent(view, event, payload)` wrapper that batches locally and POSTs every 5s or on view change.

### R-D7. Decision: feature flags become kill-switches, not gates

Default-ON for all three live views. Flag now means: "if this env var is set to `0`/`false`, show the legacy fallback." Since legacy fakes data, we keep it ONLY as a literal disabled-state placeholder copy ("This view is temporarily disabled"). The hard-coded fake values in the `Legacy*` functions get gutted in this refactor.

### R-D8. Decision: live overview owns the page; the diagnostic anchor stays a card *inside* it, not the whole view

Original "live" overview rendered ONLY the DiagnosticAnchor — which made the score, sub-scores, top-3 actions, and trend invisible. New live overview renders all four blocks; the diagnostic anchor becomes the bottom CTA strip.

### R-D9. Decision: legacy `interview.py` v1+v2 stays untouched

It's deprecated for new work per the saved `MEMORY.md`; the canonical surface is mock v3. We don't add anything to it; we don't break it.

### R-D10. Decision: `FitScoreResponse.proven/unproven/missing` shapes the live JD evidence rows

The existing `compute_three_bucket_gap` already returns the three lists. The new live JdMatchView reads them directly into evidence rows (proven=Match, unproven=Near match, missing=Gap), capping each bucket at 4 rows. No mock evidence anywhere.

## Phases (parallelizable)

**Phase A — sequential foundational:**
- A1: Migration `0046_readiness_workspace.py` (4 new tables; additive).
- A2: 4 new SQLAlchemy models + `__init__.py` re-exports.

**Phase B — 4 parallel subagents (each owns ONE backend slice):**
- B1: `portfolio_autopsy_service` persistence + list endpoint + tests.
- B2: `application_kit_service` build/list/download + tests.
- B3: `readiness_workspace_event_service` + POST /events + tests.
- B4: `readiness_overview_service` (aggregator) + `GET /readiness/overview`, `GET /readiness/proof` + tests.

**Phase C — 3 parallel subagents (each owns ONE frontend slice):**
- C1: api-client namespaces + new hooks + `use-readiness-events` batching wrapper.
- C2: Overview rewire (live owns the page; sub-scores; top-3 actions; trend; north-star delta).
- C3: Resume + JD Match + Proof + Kit rewires; event firing on view changes / CTAs.

**Phase D — verify + ship:**
- D1: Backend tests already authored by B1–B4 subagents; run `pytest` for every new file.
- D2: Frontend tests for the rewired sections.
- D3: Seed extension — 2 autopsies, 1 kit, ~12 workspace events for `demo@pae.dev`.
- D4: Playwright E2E walking each subview, capturing screenshots, fixing any in-flight bugs.
- D5: Update this doc with bug-closure scorecard + screenshots.

## Phase Status — Job Readiness Workspace (✅ landed 2026-04-26)

### Files added / modified

**Backend — Phase A (schema):**
- `backend/alembic/versions/0046_readiness_workspace.py` — NEW migration (4 tables, additive, IF NOT EXISTS DDL)
- `backend/app/models/portfolio_autopsy_result.py` — NEW
- `backend/app/models/application_kit.py` — NEW
- `backend/app/models/readiness_action_completion.py` — NEW
- `backend/app/models/readiness_workspace_event.py` — NEW
- `backend/app/models/__init__.py` — re-exports

**Backend — Phase B (services + routes, 4 parallel subagents):**
- B1 (autopsy persistence): `app/services/portfolio_autopsy_persistence_service.py`, `app/schemas/portfolio_autopsy_persistence.py`, modified `app/api/v1/routes/portfolio_autopsy.py` (POST persists + new GET list/detail). 12 tests.
- B2 (application kit): `app/services/application_kit_service.py`, `app/schemas/application_kit.py`, `app/api/v1/routes/application_kit.py` (5 endpoints), extended `app/services/pdf_renderer.py` with `render_application_kit`. 16 tests.
- B3 (workspace events): `app/services/readiness_workspace_event_service.py`, `app/schemas/readiness_events.py`, `app/api/v1/routes/readiness_events.py` (3 endpoints). 13 tests.
- B4 (overview + proof aggregators): `app/services/readiness_overview_service.py`, `app/services/readiness_proof_service.py`, `app/schemas/readiness_overview.py`, modified `app/api/v1/routes/readiness.py` (added `overview_router` with `GET /overview` and `GET /proof`). 24 tests.

**Backend — Phase A+B totals:** 1 migration · 4 new tables · 4 new schemas · 4 new services + 1 extended · 9 new endpoints · **65 new tests, all passing in Docker**.

**Backend — wired to `app/main.py`:** `application_kit_router`, `readiness_events_router`, `readiness_overview_router`.

**Backend — quality fixes landed during D:**
- `tests/conftest.py` — `@compiles(ARRAY, "sqlite")` shim added once for the whole suite (4 of the parallel agents had to monkey-patch this themselves; this lifts the patch into one place).
- `app/services/readiness_workspace_event_service.py` — renamed `event=` to `event_kind=` in 3 `log.warning(...)` calls (structlog reserves `event`).
- `tests/test_services/test_readiness_workspace_event_service.py` — tz-tolerant comparison so SQLite naive datetimes don't fail the assertion (Postgres TIMESTAMPTZ behavior preserved in prod).
- `app/api/v1/routes/portfolio_autopsy.py` — `AutopsyResponse` now returns the persisted row `id` so the frontend can deep-link without a refetch.
- `app/core/config.py` — `feature_readiness_diagnostic` and `feature_jd_decoder` defaults flipped to `True` (kill-switch semantics per D-D7).

**Frontend — Phase C1 (api-client + hooks):**
- `frontend/src/lib/api-client.ts` — added `PortfolioAutopsyListItem/DetailResponse`, `ApplicationKit*`, `ReadinessOverview*`, `WorkspaceEvent*` types + 3 new namespaces (`readinessOverviewApi`, `applicationKitApi`, `readinessEventsApi`); extended `portfolioAutopsyApi` with `list/get`; added `id?` to `PortfolioAutopsy`.
- `frontend/src/lib/hooks/use-readiness-overview.ts` — NEW (`useReadinessOverview`, `useReadinessProof`).
- `frontend/src/lib/hooks/use-application-kit.ts` — NEW (`useApplicationKits`, `useApplicationKit`, `useBuildApplicationKit`, `useDeleteApplicationKit`, `applicationKitDownloadUrl`).
- `frontend/src/lib/hooks/use-portfolio-autopsy.ts` — NEW (`useAutopsyList`, `useAutopsyDetail`, `useCreateAutopsy` — invalidates autopsy.list + readiness.proof + readiness.overview).
- `frontend/src/lib/hooks/use-readiness-events.ts` — NEW (`WorkspaceEventBuffer` singleton + `useRecordWorkspaceEvent`, `useFlushWorkspaceEvents`, `useWorkspaceEventSummary`). Batches 20 events, auto-flushes every 5s + on `beforeunload`/`visibilitychange`. SSR-safe.
- `frontend/src/lib/hooks/__tests__/workspace-event-buffer.test.ts` — NEW (2 tests).

**Frontend — Phase C2 (Overview rewire):**
- `frontend/src/components/v8/screens/readiness-screen.tsx` — `OverviewView` switch now defaults to live; `OverviewViewLive` rebuilt with hero score + delta pill + 8w sparkline, 4 sub-score `MetricRow`s (real values), top-3 actions list, recommended sequence with CTA event firing, `DiagnosticAnchor` moved to bottom-of-overview card. Topbar `progress` wired to `overall_readiness`. `view_opened` telemetry effect added.
- `frontend/src/test/readiness-overview.test.tsx` — NEW, 4 tests.

**Frontend — Phase C3 (deep views):**
- `frontend/src/components/v8/screens/readiness-screen.tsx` — `ResumeView` real 4-tab subnav driven from `useReadinessProof`; `JdMatchView` collapsed to live `JdDecoderCard` + preset chips + saved-JD chips + `useSaveJd`; `ProofView` real autopsies + capstone + mock reports + inline `AutopsyComposerModal` wired to `useCreateAutopsy`; `KitView` real `useApplicationKits` list + `useBuildApplicationKit` form + `applicationKitDownloadUrl` anchor + 3s `building` poll. Dropped `computeFit`, `DEFAULT_JD_TEXT`, `KIT_CARDS`, `EXPORT_STEPS`, `ExportOverlay`, `TimelineStep`, all hard-coded EvidenceRows/bullets.
- `frontend/src/test/readiness-deep-views.test.tsx` — NEW, 6 tests.

**Frontend — quality fixes landed during D:**
- `frontend/src/components/features/readiness-diagnostic/index.ts` — `isReadinessDiagnosticEnabled()` default flipped to `true` (kill-switch).
- `frontend/src/components/features/jd-decoder/index.ts` — `isJdDecoderEnabled()` default flipped to `true`.
- `frontend/src/components/v8/screens/readiness-screen.tsx` — `ROUTE_LABEL` map added so top-action CTAs read `"Open JD Match"` instead of `"Open Jd"`.

**Seed extension:**
- `backend/app/scripts/seed_today_demo.py` — added `_ensure_autopsies` (2 rows: CLI AI tool 78/100 strong + Earnings notebook 58/100), `_ensure_application_kit` (1 ready kit `Kit · Data Analyst pilot` referencing the strong autopsy + a stub PDF blob), `_ensure_workspace_events` (12 events spread across views + hours_ago for realistic analytics). Idempotent.

### Bug closure scorecard (R1–R13)

| # | Bug | Status | Notes |
|---|---|---|---|
| R1 | Hard-coded 62/74/58/46/61 KPIs | ✅ | Live: 31% / 28-60-0-30 from `/readiness/overview` |
| R2 | Hard-coded top 3 action prose | ✅ | Live: ranked from MockWeaknessLedger / JD count / resume freshness |
| R3 | Resume subnav buttons dead | ✅ | 4 tabs functional; each fires `subnav_clicked` |
| R4 | Resume evidence rows hard-coded | ✅ | Real capstones / AI reviews / autopsies / peer reviews |
| R5 | JD `computeFit()` regex score | ✅ | Replaced with live JdDecoderCard; legacy fallback uses real `useFitScore` |
| R6 | JD 4 EvidenceRows static | ✅ | Live decoder renders proven/unproven/missing buckets |
| R7 | Proof 3 cards static | ✅ | Real primary artifact + autopsies + mock reports |
| R8 | Autopsies not persisted | ✅ | `portfolio_autopsy_results` + POST persists + GET list/detail |
| R9 | Kit fake setInterval + plaintext download | ✅ | Real `application_kits` + PDF assembly + download anchor |
| R10 | KIT_CARDS 6 hard-coded titles | ✅ | Replaced with real `useApplicationKits` rows + dynamic build form |
| R11 | Workspace clicks lost | ✅ | `readiness_workspace_events` + buffer wrapper + 12 seeded events |
| R12 | Feature flags default-OFF | ✅ | All three flags now default-ON; legacy retained as kill-switch |
| R13 | Topbar `progress: 82` hard-coded | ✅ | Wired to `overall_readiness` from aggregator |

### Test status

- **Backend:** **65/65 new tests pass** in the live Docker container (`pytest tests/test_services/test_portfolio_autopsy_persistence.py tests/test_services/test_application_kit_service.py tests/test_services/test_readiness_workspace_event_service.py tests/test_services/test_readiness_overview_service.py tests/test_services/test_readiness_proof_service.py tests/test_routes/test_portfolio_autopsy_routes.py tests/test_routes/test_application_kit_routes.py tests/test_routes/test_readiness_events_routes.py tests/test_routes/test_readiness_overview_route.py`).
- **Frontend:** 12 tests across `src/test/readiness-overview.test.tsx`, `src/test/readiness-deep-views.test.tsx`, `src/lib/hooks/__tests__/workspace-event-buffer.test.ts` — all green. ESLint + tsc clean.

### Playwright E2E walk (live, demo@pae.dev)

| View | Outcome | Evidence (DOM-validated) |
|---|---|---|
| `/readiness` Overview | ✅ | "31%" overall · "Hello, Demo. You are close to interviewable." · "Just getting started." tagline · "Test yourself against a real JD" + "Match me to a real JD" CTAs from real top_actions · sub-scores 28/60/0/30 · "Conversational diagnosis" anchor at bottom |
| `/readiness` Resume Lab | ✅ | 4 tabs (Evidence/Bullets/Role tailoring/Export) · "CLI AI tool · 1 draft · score 84/100 · Strong" from real seed · "AI reviews: No AI reviews yet — submit a draft" honest empty state · "First resume free" quota chip |
| `/readiness` JD Match | ✅ | Real JdDecoderCard · 3 preset chips (Python/Data/GenAI) · "Save this JD" disabled until 40 chars · paste textarea + "Decode" CTA |
| `/readiness` Interview Coach | ✅ | MockInterviewWorkspace mode picker showing Technical Conceptual / Live Coding / Behavioral with real time estimates |
| `/readiness` Proof Portfolio | ✅ | "Primary artifact: CLI AI tool # draft · LIVE FROM STUDIO" · "Recent autopsies: CLI AI tool 78/100 / Earnings sentiment notebook 58/100" with real seed copy · "Mock interview reports: No mock interviews yet" honest empty state |
| `/readiness` Application Kit | ✅ | Recent kits row: "Kit · Data Analyst pilot · ready · 2h ago" with Download/Delete · Build form prefilled `Kit · 2026-04-26` label + `Data Analyst` target_role + JD/Mock/Autopsy dropdowns |
| Console errors | 0 | After enabling backend `feature_readiness_diagnostic` flag |

Screenshots captured (in repo root):
- `readiness-overview-final.png` (full page)
- `readiness-resume.png`
- `readiness-jd.png`
- `readiness-proof.png`
- `readiness-kit.png`
- `readiness-interview.png`

### In-flight bugs caught + fixed during E2E

| # | Bug | Fix |
|---|---|---|
| RD1 | Frontend served stale Docker bundle (legacy 62% rendered) | Required `docker compose build frontend && up -d frontend` cycle (documented in `frontend/CLAUDE.md`; same gotcha as Today refactor) |
| RD2 | Backend `feature_readiness_diagnostic` defaulted False → diagnostic 404 | Flipped default to True (R12 closure) |
| RD3 | Top-action CTA read "Open Jd" (route casing) | Added `ROUTE_LABEL` map; now reads "Open JD Match" |
| RD4 | structlog `event=` keyword collision in 3 warning calls | Renamed to `event_kind=` |
| RD5 | SQLite-naive `occurred_at` failed equality assertion | Made test tz-tolerant; production behavior on Postgres TIMESTAMPTZ unchanged |
| RD6 | Repeated SQLite ARRAY shim across 4 test files | Lifted to `tests/conftest.py` once |
| RD7 | `AutopsyResponse` didn't return persisted row id | Added `id: str | None = None` field; route populates from `persist_autopsy_result()` |

### Net change in this phase

- **New tables:** 4 (portfolio_autopsy_results, application_kits, readiness_action_completions, readiness_workspace_events)
- **New routes:** 9 (overview, proof, kit×5, events×3, autopsy×2)
- **New services:** 6 (autopsy persistence, application kit, workspace events, overview, proof, +pdf renderer extension)
- **New schemas:** 4 files
- **New tests:** 65 backend + 12 frontend = **77 tests, all green**
- **Lines changed in `readiness-screen.tsx`:** 1255 → 2175 (+920)
- **Hard-coded UI literals removed:** 6 hard-coded KPI numbers, 3 hard-coded ActionRow prose blocks, 4 hard-coded MetricRow demo values, 4 hard-coded EvidenceRows in JD legacy, 3 hard-coded ProofView cards, 6 hard-coded KIT_CARDS, 4 hard-coded EXPORT_STEPS, fake setInterval export, fake plaintext download blob, hard-coded sparkline polyline, hard-coded "+8 this week" + "44 → 51 → 58 → 62" history.
- **Workspace telemetry:** every view-change + CTA click now persists to `readiness_workspace_events` (best-effort, 5s flush interval, batched).
- **Demo data ready:** `cd backend && uv run python -m app.scripts.seed_today_demo` (idempotent) populates `demo@pae.dev` with 2 autopsies + 1 ready kit + 12 workspace events on top of the existing Today seed.

### Followups (not in this phase)

- Tailored Resume needs a list endpoint (`GET /tailored-resume` for "past tailored resumes" panel in Resume Lab).
- JD library `GET /career/jd-library` returns metadata only; consider adding `jd_text` to the response so re-clicking a saved JD restores the full paste.
- Application Kit PDF renderer is currently a basic text PDF fallback — production polish (cover page styling, branded header) deferred to a follow-up.
- Workspace events analytics dashboard (admin-side) — data is captured but no admin UI consumes `GET /readiness/events/summary` yet.
- Service-internal `db.commit()` + outer `get_db` wrapper combo creates a footgun if the inner write fails (B1 added a local `db.rollback()` mitigation in the autopsy route; worth a platform-wide audit).
- The `building` kit poll has no exponential backoff or max-retry cap (relies on backend transitioning out of `building` quickly — fine in our synchronous PDF path; revisit if we move to a Celery worker).

### How to apply locally

```bash
cd backend && uv run alembic upgrade head
cd backend && uv run python -m app.scripts.seed_today_demo

# Already-running stack:
docker compose build frontend && docker compose up -d frontend
docker compose restart backend

# Then visit http://localhost:3002/readiness as demo@pae.dev / demo-password-123
```

---

# Catalog + Payments v2 (Razorpay) Refactor Phase — 2026-04-26

> Same mandate, same autonomy. Mission: real catalog backed by Postgres, real Razorpay checkout, **instant unlock** the moment payment is captured, no double-enrollment under retry storms, full webhook audit trail.

## Audit summary

**File:** [`frontend/src/components/v8/screens/catalog-screen.tsx`](frontend/src/components/v8/screens/catalog-screen.tsx) (~772 lines).

### What's already wired
- Backend: `Stripe`-only payment surface — `app/api/v1/routes/billing.py` (POST `/checkout`, POST `/webhook`, GET `/portal`, GET `/subscription`), `StripeService` wraps the SDK, `Payment` model has `stripe_payment_intent_id` + `stripe_subscription_id` fields.
- Webhook handler creates `Enrollment` directly via repository on `checkout.session.completed`.
- Frontend: `billingApi.createCheckout` calls Stripe; success redirects to `/portal?enrolled={id}`.
- Bundle SKUs exist in the UI (`CARDS` array contains 2 bundles) but have **no DB rows** — they're frontend-only fictions today.

### Bugs / gaps
| # | Where | Status |
|---|---|---|
| K1 | `CARDS` array (5 tracks + 2 bundles) is hard-coded; outcomes/meta/salary tooltip/ribbon all literal | ❌ |
| K2 | Stripe is the only provider; no Razorpay anywhere; the user explicitly wants Razorpay (India payments) | ❌ |
| K3 | No webhook event ledger — Razorpay retries up to 5× per event; without dedupe we grant entitlement N times | ❌ |
| K4 | `payments` table conflates intent (order) with execution (payment attempt); a declined card + retry can't be modeled | ❌ |
| K5 | No `course_entitlements` table — "is the user unlocked for this course" is inferred from `enrollments`, which mixes free/paid signals | ❌ |
| K6 | "Instant unlock" doesn't exist — webhook race + client confirm not split; user hits portal with stale data after Stripe redirect | ❌ |
| K7 | No bundle DB object; can't sell multi-course packages from the catalog | ❌ |
| K8 | No receipts / invoice surface | ❌ |
| K9 | No refund flow + no refund webhook | ❌ |
| K10 | Cohort proof: "2,400+ students promoted" stat hard-coded in hero | ❌ |
| K11 | Hard-coded "30 days money-back guarantee" stat | ⚠️ keep as policy copy |
| K12 | Free Python course shows "✓ Enrolled" CTA whether or not user is actually enrolled | ❌ |

## Decisions

### CP-D1. Schema additions (additive — migration `0047_payments_v2`)

| Table | Why |
|---|---|
| `orders` | Intent-to-buy. One per Buy click. State: `created → authorized → paid → fulfilled → failed → refunded`. Also holds `provider_order_id` (Razorpay `order_xyz`) + `receipt_number` + `gst_breakdown`. |
| `payment_attempts` | One row per actual transaction attempt against an order. Lets us model declined-card-then-retry. Holds `provider_payment_id` + verified signature + raw response. |
| `payment_webhook_events` | Append-only ledger keyed UNIQUE on `(provider, provider_event_id)`. Every webhook lands here BEFORE any business logic runs — guarantees idempotency. Also keeps the raw body for forensics. |
| `course_entitlements` | Authoritative "user can access this course". Source: `purchase \| free \| bundle \| admin_grant \| trial`. Unique partial index on `(user_id, course_id) WHERE revoked_at IS NULL`. |
| `course_bundles` | Real catalog object for multi-course packages. `course_ids` JSON list. |
| `refunds` | Per-refund records linked to order + payment_attempt + Razorpay refund id. |

Keep existing `payments` + `enrollments` tables for backward compatibility. New `course_entitlements` is the **authoritative** access check; lessons routes will read it (with `enrollments` as fallback for old free-course flows during migration).

### CP-D2. Provider abstraction

`PaymentProvider` enum: `"razorpay" | "stripe"`. New `app/services/payment_providers/` package with:
- `base.py` — `PaymentProviderBase` ABC: `create_order`, `verify_payment_signature`, `verify_webhook_signature`, `parse_webhook_event`, `fetch_payment`, `create_refund`.
- `razorpay_provider.py` — concrete impl using the official `razorpay` Python SDK.
- `stripe_provider.py` — wraps existing `StripeService` to satisfy the ABC.
- `factory.py` — `get_provider(name) -> PaymentProviderBase`.

Frontend chooses provider via `provider` field on the checkout request (defaulting to `razorpay` for the v2 flow).

### CP-D3. Order lifecycle (state machine)

```
[user clicks Buy]
      ↓
POST /payments/orders { target_type, target_id, provider }
      ↓
created (DB row + provider order created)
      ↓ (Razorpay returns order_id; client opens hosted checkout)
authorized  ←── webhook: payment.authorized
      ↓
paid        ←── webhook: payment.captured  OR  client POST /payments/orders/{id}/confirm
      ↓
fulfilled   (course_entitlements rows inserted; instant unlock surfaced)
```

Failure paths: `payment.failed` webhook → status=`failed` + failure_reason. `refund.processed` webhook → status=`refunded` + entitlement revoked.

### CP-D4. Idempotency rules (the most important production discipline)

1. Every webhook POST is wrapped:
   - Compute SHA256 of raw body.
   - Verify signature; record `signature_valid` bool.
   - INSERT into `payment_webhook_events` (UNIQUE on `(provider, provider_event_id)` — so a duplicate event raises `IntegrityError` and we short-circuit cleanly).
   - Only AFTER the ledger insert succeeds, dispatch to the event-type handler.

2. Order fulfillment is idempotent — the entitlement insert is `ON CONFLICT DO NOTHING` against the partial unique index.

3. Client confirm endpoint short-circuits if `order.status >= "paid"` — returns 200 with the entitlement payload, never re-runs side effects.

4. Webhook handler always returns 200 to Razorpay so it doesn't retry forever; we LOG errors but never propagate.

### CP-D5. Instant unlock UX

Two paths must converge to "user sees lesson access immediately":

**Path A — Razorpay redirect:**
1. User completes payment in Razorpay's hosted modal.
2. Razorpay calls our success handler with `{razorpay_order_id, razorpay_payment_id, razorpay_signature}`.
3. Frontend POSTs to `/payments/orders/{id}/confirm` with those three fields.
4. Backend verifies HMAC, marks order paid + creates entitlement, returns the entitlement payload.
5. Frontend uses `queryClient.setQueryData(["entitlements"], ...)` to inject the new entitlement into the cache — instant UI flip from "Unlock track" to "✓ Enrolled".
6. Redirect to `/portal?enrolled={course_id}`.

**Path B — Webhook (safety net):**
1. Razorpay POSTs to `/payments/webhook/razorpay` ~3 seconds after capture.
2. Same dedup-ledger flow. If client confirm already ran, this is a no-op via the unique constraint.

If client confirm fails (network error etc.), the webhook still grants entitlement. The user gets the unlock on their next page load.

### CP-D6. Catalog comes from DB

`courses` already exists. Add:
- `courses.bullets JSON` — replaces hard-coded `outcomes` arrays. Each bullet: `{text, included: bool}`.
- `courses.metadata JSON` — keys: `lesson_count, lab_count, capstone_title, est_hours, est_weeks, completion_pct, placement_pct, level_label, ribbon_text, accent_color, salary_tooltip{...}`.
- New table `course_bundles` for the 2 hard-coded bundles in `CARDS`.
- `GET /courses` already returns the list; extend the response with `is_unlocked: bool` (true if user has an active `course_entitlements` row).

Frontend collapses `CARDS` to a `useCatalog()` hook that returns `{tracks: CourseResponse[], bundles: CourseBundleResponse[]}` and renders cards from real data.

### CP-D7. Receipts

`GET /payments/orders` returns the user's order history with computed receipt numbers. `GET /payments/orders/{id}/receipt.pdf` streams a basic PDF (reuse `pdf_renderer`). Catalog screen gets a "Receipts" link in the hero.

### CP-D8. Refunds

Backend-only for now (admin endpoint): `POST /admin/refunds {order_id, amount_cents, reason}`. Calls Razorpay refund API; on `refund.processed` webhook, revoke entitlement (set `revoked_at`).

### CP-D9. Free course handling

`Course.price_cents == 0` → no order, no payment. Frontend "Enroll free" button POSTs to `/payments/free-enroll {course_id}` → backend creates `course_entitlements` row with source=`free`. Same idempotent insert.

### CP-D10. Test rigor

This is where the spec is most insistent. Build these specific tests:

1. **HMAC verification** — known body + known secret → expected signature; tampered body fails.
2. **Idempotent webhook** — POST same event_id twice → second returns 200 with `duplicate=True` and 0 new entitlements created.
3. **Client-confirm + webhook race** — both arrive within ms of each other → exactly 1 entitlement row.
4. **Order can have multiple payment attempts** — first fails, second succeeds → order ends in `paid` with 1 captured attempt.
5. **Refund revokes entitlement** — capture → entitlement granted → refund webhook → entitlement.revoked_at set, lesson access returns 403.
6. **Free enroll twice** — second call is a no-op (0 new entitlements).
7. **Bundle purchase grants N entitlements** — buy bundle with 3 course_ids → 3 rows in `course_entitlements` with source=`bundle`, source_ref=`order_id`.
8. **Currency safety** — Razorpay returns paise (₹1 = 100 paise); we always store amount_cents internally; renderer handles INR vs USD symbol.
9. **Signature failure logged but ledger row recorded** — invalid signature webhook → ledger row with `signature_valid=False`, no business logic runs.
10. **Locked course access** — student without entitlement hitting GET `/lessons/{id}` for a paid course → 403.
11. **Concurrent buys for same course** — two orders against the same target → both reach `paid` is fine; entitlement insert is idempotent so 1 row.

## Phases (parallelisable)

**Phase A (sequential foundational):**
- A1: Migration `0047_payments_v2.py` (6 new tables + `courses.bullets/metadata` columns).
- A2: 6 new SQLAlchemy models + `__init__.py` re-exports.

**Phase B (4 parallel subagents — backend slices):**
- B1: `payment_providers/` package — base ABC + `RazorpayProvider` + `StripeProvider` + factory + tests.
- B2: `order_service` (create/get/list/confirm) + `payment_webhook_event_service` (idempotent ledger insert) + tests.
- B3: `entitlement_service` (grant/revoke/check + bundle expansion) + middleware/decorator for lesson access + tests.
- B4: `app/api/v1/routes/payments_v2.py` — POST orders, POST orders/{id}/confirm, GET orders, GET orders/{id}/receipt.pdf, POST free-enroll, POST webhook/razorpay, POST webhook/stripe + tests.

**Phase C (3 parallel subagents — frontend slices):**
- C1: api-client + hooks (`useCatalog`, `useEntitlements`, `useCreateOrder`, `useConfirmOrder`, `useFreeEnroll`, `useReceipts`).
- C2: Razorpay checkout integration (load `checkout.razorpay.com/v1/checkout.js` script, open hosted modal, POST confirm on success).
- C3: Catalog screen rewire — drop `CARDS`, render from `useCatalog()`, real "✓ Enrolled" check via `useEntitlements()`, real bundles, receipts link.

**Phase D — verify + ship:**
- D1: Backend tests — all 11 spec items above.
- D2: Frontend tests — checkout flow happy path + error path + entitlement injection on success.
- D3: Seed extension — 2 entitlements (free + paid) for `demo@pae.dev`, 1 sample order with receipt.
- D4: Playwright E2E walking the catalog, opening enroll modal, simulating Razorpay test mode, verifying instant unlock.
- D5: Update doc with bug-closure scorecard.

## Phase Status — Catalog + Payments v2 (✅ landed 2026-04-26)

### Files added / modified

**Backend — Phase A (schema):**
- `backend/alembic/versions/0047_payments_v2.py` — NEW migration (6 tables, additive, IF NOT EXISTS DDL, partial unique index on entitlements).
- `backend/app/models/order.py`, `payment_attempt.py`, `payment_webhook_event.py`, `course_entitlement.py`, `course_bundle.py`, `refund.py` — NEW.
- `backend/app/models/course.py` — added `bullets` (JSON list of `{text, included}`) + `metadata_` (JSON dict).
- `backend/app/models/__init__.py` — re-exports.
- `backend/app/core/config.py` — added `razorpay_key_id`, `razorpay_key_secret`, `razorpay_webhook_secret`, `payments_default_provider`, `payments_default_currency`.
- `backend/pyproject.toml` — added `razorpay>=1.4.2`.

**Backend — Phase B (4 parallel subagents — 64 tests):**
- B1 (provider abstraction): `app/services/payment_providers/` package — `base.py` (ABC + 4 dataclasses + 3 exceptions), `razorpay_provider.py`, `stripe_provider.py`, `mock_provider.py` (NEW dev-fallback), `factory.py`, `__init__.py`. **11 tests**.
- B2 (orders + webhooks): `app/services/order_service.py` (create / list / get / confirm / mark_failed + `generate_receipt_number` pure helper), `app/services/payment_webhook_event_service.py` (idempotent `record_webhook_event` + `dispatch_event` with DI). **15 tests**.
- B3 (entitlements): `app/services/entitlement_service.py` (8 functions including `is_entitled`, `grant_for_order`, `grant_free_course`, `revoke_for_order`, `expand_bundle`); `app/api/v1/dependencies/entitlement.py` (`require_course_access` factory). **20 tests**.
- B4 (routes): `app/api/v1/routes/payments_v2.py` (POST orders, GET orders, GET order detail, GET receipt PDF, POST confirm, POST free-enroll), `app/api/v1/routes/payments_webhook.py` (POST razorpay, POST stripe), `app/api/v1/routes/catalog.py` (GET catalog with `is_unlocked` per user). **18 tests**.
- `backend/app/main.py` — wired `payments_v2_router`, `payments_webhook_router`, `catalog_router`.

**Backend — Phase B follow-ups landed during smoke + Phase D:**
- `app/services/payment_providers/mock_provider.py` — NEW deterministic dev fallback (`MockProvider`). HMAC-SHA256 with a known dev secret so tests + Playwright can produce valid signatures. Auto-selected by the factory when Razorpay/Stripe creds are unconfigured AND `environment != "production"`. Production environments raise `ProviderUnavailableError` instead.
- `app/api/v1/routes/payments_v2.py` — added `try/except` around `order_service.create_order` for `ProviderUnavailableError` → 502 (was 500); `ValueError` → 400.
- Test `test_get_provider_factory_returns_concrete` updated to cover the new fallback semantics.

**Backend — Phase C/D (seed):**
- `app/scripts/seed_today_demo.py` — added `_ensure_catalog_metadata` (4 courses with rich bullets + ribbons + salary tooltip) + `_ensure_catalog_bundles` (2 bundles). Idempotent. Uses canonical course slugs (`python-developer`, `data-analyst`, `data-scientist`, `genai-engineer`).

**Frontend — Phase C1 (api-client + hooks):**
- `frontend/src/lib/api-client.ts` — added `Catalog*`, `Order*`, `Payment*`, `FreeEnroll*` types + `catalogApi` (with trailing slash) + `paymentsApi` (createOrder, confirmOrder, listOrders, getOrder, freeEnroll, receiptUrl).
- `frontend/src/lib/hooks/use-catalog.ts` — NEW (`useCatalog()`, anon-friendly).
- `frontend/src/lib/hooks/use-entitlements.ts` — NEW (derives `Set<courseId>` from catalog).
- `frontend/src/lib/hooks/use-payments.ts` — NEW (`useOrders`, `useOrder`, `useCreateOrder`, `useConfirmOrder`, `useFreeEnroll` with **optimistic catalog cache patch on success — instant unlock**).
- `frontend/src/lib/hooks/__tests__/use-payments.test.ts` — 3 tests.

**Frontend — Phase C2 (Razorpay checkout):**
- `frontend/src/components/features/razorpay-checkout/` — NEW package: `index.ts`, `load-script.ts` (idempotent SSR-safe), `mock-signature.ts` (`crypto.subtle` HMAC for dev-mode), `use-razorpay-checkout.ts` (orchestrates create-order → modal/mock → confirm), `checkout-button.tsx`, `free-enroll-button.tsx`, plus 2 test files. **6 tests**.

**Frontend — Phase C3 (catalog rewire):**
- `frontend/src/components/v8/screens/catalog-screen.tsx` — full rewrite **772 → 561 lines**. Drops `CARDS` array, `findCourse`, `confirmEnroll`, `IntakeOverlay` (legacy Stripe redirect). Reads from `useCatalog()`, renders cards from `course.bullets` + `course.metadata`, swaps CTA to `FreeEnrollButton` (free) vs `RazorpayCheckoutButton` (paid). Renders bundles from `data.bundles`. Real loading skeletons + honest empty state.
- `frontend/src/test/catalog-screen.test.tsx` — 4 tests.

### Bug closure scorecard (K1–K12)

| # | Bug | Status |
|---|---|---|
| K1 | Hard-coded `CARDS` array (5 tracks + 2 bundles) | ✅ — driven by `useCatalog()` from real DB rows |
| K2 | Stripe-only; no Razorpay | ✅ — `RazorpayProvider` + factory, default provider in checkout |
| K3 | No webhook event ledger | ✅ — `payment_webhook_events` UNIQUE on `(provider, provider_event_id)` + `record_webhook_event` short-circuits dups |
| K4 | `payments` table conflates intent + execution | ✅ — new `orders` (intent) + `payment_attempts` (executions) split |
| K5 | No `course_entitlements` table | ✅ — new table with partial unique index `(user_id, course_id) WHERE revoked_at IS NULL` |
| K6 | No "instant unlock" path | ✅ — `useConfirmOrder.onSuccess` optimistically patches catalog cache; webhook is the safety net |
| K7 | No bundle DB object | ✅ — `course_bundles` table + 2 seeded bundles |
| K8 | No receipts | ✅ — `GET /payments/orders/{id}/receipt.pdf` streams a real PDF |
| K9 | No refund flow | ✅ — `refunds` table + `refund.processed` webhook → `revoke_for_order` |
| K10 | Hard-coded "2,400+ students promoted" stat | ⚠️ left in place (no count endpoint yet; flagged in code) |
| K11 | Hard-coded "30 days money-back guarantee" | ✅ kept as policy copy (intentional) |
| K12 | Free Python course shows "✓ Enrolled" without checking | ✅ — every CTA reads `course.is_unlocked` from real entitlements |

### Test status

- **Backend: 64/64 new tests passing** in the live Docker container (`pytest tests/test_services/test_payment_providers.py tests/test_services/test_order_service.py tests/test_services/test_payment_webhook_event_service.py tests/test_services/test_entitlement_service.py tests/test_routes/test_payments_orders_route.py tests/test_routes/test_payments_webhook_route.py tests/test_routes/test_payments_free_enroll.py tests/test_routes/test_catalog_route.py tests/test_api/test_entitlement_dependency.py`). Ruff + mypy clean across all new files.
- **Frontend: 13/13 new tests passing** across `src/test/catalog-screen.test.tsx`, `src/lib/hooks/__tests__/use-payments.test.ts`, `src/components/features/razorpay-checkout/__tests__/`. ESLint clean. `tsc --noEmit` clean (only pre-existing chat/page error remains, owned by a different surface).

### Live API smoke (verified end-to-end)

```
1. Pick a paid locked course (Data Scientist ₹149)
2. POST /api/v1/payments/orders {target_type:course, target_id, provider:razorpay}
   → {order_id, provider_order_id: mock_order_0cce...,
      amount_cents:14900, currency:INR, receipt_number:CF-20260426-78DF49}
3. POST /api/v1/payments/orders/{id}/confirm with HMAC-SHA256-signed payload
   → status=fulfilled, entitlements_granted=[<course_id>]
4. Replay confirm (idempotent test) → status still fulfilled, same entitlements
5. GET /api/v1/catalog/ → that course now shows is_unlocked=true
```

Bad signature → clean 400 with descriptive error (`Signature verification failed`).
Provider unavailable (no Razorpay creds) → clean 502 (`Payment provider unavailable: …`) + dev-mode `MockProvider` auto-fallback in non-prod environments.

### Production-grade decisions captured

| Concern | Decision |
|---|---|
| Idempotency of webhooks | Append-only ledger, UNIQUE on `(provider, provider_event_id)`, INSERT before any business logic |
| Idempotency of client confirm | Status check + `paid` short-circuit returns same response without re-running side effects |
| Race: client confirm + webhook | Both call `confirm_order`; the second one short-circuits because status is already `paid`. Followup: add `SELECT ... FOR UPDATE` for stricter ordering |
| Failed signature webhook | Recorded in ledger with `signature_valid=false`, dispatch skipped, return 200 (no retry storm) |
| Refund | `refund.processed` webhook → `revoke_for_order` sets `revoked_at` on all entitlements with that `source_ref` |
| Currency | Stored in cents/paise everywhere (₹89.00 = 8900); display layer formats per `currency` field |
| Free courses | Bypass orders entirely via `POST /payments/free-enroll`; entitlement source=`free` |
| Bundle purchase | One order, N entitlements (one per `course_ids[*]`), source=`bundle`, source_ref=`order.id` |
| Provider abstraction | `PaymentProviderBase` ABC + `get_provider(name)` factory. Adding PayU/PayPal is a single new file |
| Dev/test ergonomics | `MockProvider` auto-selected when creds missing in non-prod; deterministic HMAC for sign-payment + sign-webhook; FE has `mock-signature.ts` to mirror this client-side |

### How to run locally

```bash
cd backend && uv run alembic upgrade head
cd backend && uv run python -m app.scripts.seed_today_demo
docker compose build frontend && docker compose up -d frontend

# Visit http://localhost:3002/catalog as demo@pae.dev / demo-password-123
# Free courses → "Enroll free" button → instant unlock
# Paid courses → "Unlock track" → opens Razorpay (real) or simulates capture (mock dev mode) → instant unlock
```

To swap MockProvider for real Razorpay test mode, add to your `.env`:
```
RAZORPAY_KEY_ID=rzp_test_xxx
RAZORPAY_KEY_SECRET=xxx
RAZORPAY_WEBHOOK_SECRET=xxx
NEXT_PUBLIC_RAZORPAY_KEY_ID=rzp_test_xxx
```

### Followups (not in this phase)

- Tailored 8-char receipt numbers — current 6-hex space (~16M) is fine but birthday-paradox risk past ~5K orders/day. Migration to a sequence is a follow-up.
- `confirm_order` race hardening with `SELECT … FOR UPDATE` on the order row.
- Receipt PDF Jinja template (currently uses the fallback text-PDF helper).
- Trial → paid upgrade path: revoke trial entitlement before granting purchased one (otherwise the partial unique index keeps the trial as the active row).
- Admin-side refund UI (route exists; no frontend page yet).
- "Students promoted" hero stat — needs a real count endpoint.

### Phase D — Playwright E2E walk (2026-04-26)

Walked the live `/catalog` route in Chromium as `demo@pae.dev`. **0 console errors across the entire flow.**

Setup gotcha caught (logged to lessons.md territory):
- **First Playwright pass rendered only 6 of the 13 cards** — Docker `compose build frontend` apparently kept a stale layer cache despite source-file changes. Fix: `docker compose build --no-cache frontend` + `docker compose up -d --force-recreate frontend`. The `frontend/CLAUDE.md` already calls out the rebuild requirement; what wasn't documented is that an incremental `compose build` can occasionally serve stale bundles. **Always `--no-cache` for catalog-style screen rewrites that change the data shape.**

Verified end-to-end via Playwright DOM inspection:

| Step | Result |
|---|---|
| Catalog renders 13 cards (11 courses + 2 bundles) | ✅ |
| Hero stats derived from real data: "11 career tracks · 172 lessons + labs" | ✅ |
| Free courses + previously-entitled paid courses show "✓ Enrolled" (disabled CTA) | ✅ |
| Locked paid courses show "Unlock track" gold CTA | ✅ |
| "Most popular" gold ribbon on Data Analyst (from `metadata.ribbon_text`) | ✅ |
| "Save 30%" ribbon on Data Career Arc bundle | ✅ |
| **Click "Unlock track" on Production RAG Systems (₹49)** → mock checkout fires → `useConfirmOrder` lands → CTA flips to "✓ Enrolled" within ~2 seconds | ✅ |
| API confirms `is_unlocked=true` for that course (entitlement persisted) | ✅ |
| **Click "Unlock bundle" on AI Engineer Arc (₹169)** wrapping `[python-developer, genai-engineer]` → 2 entitlements granted, 1 was idempotent (python-developer already entitled), GenAI Engineer flips instantly | ✅ |
| Order history persisted: 6 orders with deterministic receipt numbers `CF-20260426-XXXXXX`, mix of `fulfilled` + `created` (orders that never reached confirm) | ✅ |
| Bundle order has `target_type=bundle`, `amount_cents=16900`, `status=fulfilled` | ✅ |

Screenshots captured (in repo root):
- `catalog-real-data.png` — fresh state with 11 tracks + 2 bundles, demo's existing entitlements showing as "✓ Enrolled".
- `catalog-after-unlock.png` — after Production RAG single-course purchase.
- `catalog-after-bundle-purchase.png` — after AI Engineer Arc bundle purchase.

The instant-unlock seam works exactly as designed: `useConfirmOrder.onSuccess` patches the `["catalog"]` query cache via `setQueryData`, flipping `is_unlocked: true` on every course id in `entitlements_granted`. No refetch round-trip; the UI flips before the optimistic update would even hit a re-render.

UX observation worth flagging (not a bug): the Bundle CTA itself doesn't track its OWN purchased state — it stays "Unlock bundle" even after every component course is unlocked. A future polish pass could surface "✓ All courses unlocked" once every `course_ids` entry has an active entitlement. Logged as a follow-up.





### Net change in this phase

- **Backend:** 1 new migration, 2 new services, 2 new schemas, 1 modified route, 1 new sub-route, 1 hook in srs_service, 5 new test files (43 tests).
- **Frontend:** 2 new hooks, 1 fully-rewritten screen, 1 chat-page edit (3 small chunks), 5 new types, 2 new test files (6 tests).
- **Lint:** 0 errors on changed files (preexisting warnings unchanged).
- **Tests touching this phase:** all green where executable.



---

## P-Tutor3 — Tutor screen bugfixes (2026-04-26)

Two tactile bugs reported after the P-Tutor2 trim landed:

1. **Conversation card was height-capped** at `min(72vh, 720px)`. The cap dated from when the screen had a mode-picker row above and a session-flow row below — both removed in P-Tutor2 — so the rationale for capping inside-the-viewport was gone. On a 1440×900 laptop the card stopped at 720px even though there were ~180px of empty space below it.
2. **`+ New` did not start a fresh conversation** when clicked from the Recent rail while viewing an existing conversation. The visible chat still showed the previous transcript.

### Bug 1 — fix

`frontend/src/app/v8.css` — `.tutor-conv-card`:

```css
/* before */
height: min(72vh, 720px);
/* after */
height: calc(100vh - 160px);
```

The 160px reservation accounts for `.topbar` (~70px sticky) + `.pad` top/bottom padding (28+54 = 82px) plus a few pixels of breathing room. `min-height: 520px` retained so short viewports don't collapse the chat into a sliver.

### Bug 2 — root cause

`handleNew` already cleared `activeConvId`, `hydratedMessages`, the input, and bumped `chatKey`, then called `router.replace("/chat")`. On paper the URL-sync effect at `chat/page.tsx:4027` would then see `urlConvId === null` and not re-open anything.

The race: in Next.js App Router, `useSearchParams()` is **not updated synchronously** by `router.replace`. So in the same React render after `handleNew` runs, `urlConvId` still holds the stale `"ABC"` while `activeConvId` is already `null`. The URL-sync effect's branch `if (urlConvId === activeConvId) return;` doesn't catch this — it sees mismatch and calls `openConversation(urlConvId, …)`, which re-fetches and re-installs the very conversation we just left.

### Bug 2 — fix

Added a `manualClearPending` ref. `handleNew` and `handleConfirmStartNew` set it `true` before calling `router.replace("/chat")`. The URL-sync effect short-circuits while the ref is `true` AND `urlConvId` is non-null. Once `urlConvId` actually transitions to `null` (when Next.js finally commits the navigation), the effect clears the ref and proceeds normally.

```ts
useEffect(() => {
  if (!initialConvApplied.current) return;
  if (!urlConvId) {
    manualClearPending.current = false;   // URL caught up — drop the guard
    if (activeConvId !== null) { /* clear */ }
    return;
  }
  if (manualClearPending.current) return;  // ignore stale ?c= tick
  if (urlConvId === activeConvId) return;
  void openConversation(urlConvId, { pushUrl: false });
}, [urlConvId, activeConvId, openConversation]);
```

### Verification (Playwright, 1440×900)

1. Sent a message → URL became `/chat?c=fd2…fb55`, marker text visible, eyebrow "Resumed conversation".
2. Clicked `+ New` → URL became `/chat`, marker text gone, eyebrow "Fresh thread", welcome screen back.
3. Clicked the rail item to resume → URL `?c=…` returned, marker visible.
4. Clicked `+ New` again → cleared again. Race-fix holds across the round-trip.
5. Card height at 1440×900: now 740px (was 720px). At 1080p laptops it grows to ~920px.

### Net change in this phase

- **Frontend:** 1 CSS edit (`v8.css`), 3 chat page edits (`chat/page.tsx`: ref declaration + handleNew + handleConfirmStartNew + URL-sync effect).
- **Lint:** 0 new errors on changed files.

---

## P-Tutor4 — Wider chat + collapsible rail (2026-04-26)

User feedback: "horizontally it feels slightly congested. Apps like ChatGPT have a toggle to close the conversation history so we have much wider area for chat."

### Layout — old vs new

The Tutor screen was sharing `today-grid` (`minmax(0, 1.55fr) 360px`), which meant the chat column was capped by the wider Today copy block. Tutor doesn't need a 360px rail — the rail only hosts Recent conversations.

Introduced `tutor-grid` with its own proportions:

```css
.tutor-grid {
  grid-template-columns: minmax(0, 1fr) 300px;
  align-items: start;
  gap: 20px;
  transition: grid-template-columns 0.28s var(--ease);
}
.tutor-grid.rail-collapsed {
  grid-template-columns: minmax(0, 1fr) 0;
  gap: 0;
}
```

At 1440px viewport: chat column 720px → 780px (+8%). Rail trimmed 360px → 300px.

### Collapse toggle (the ChatGPT-style affordance)

- Inline `›` button at the rail header (next to `+ New`) hides the rail.
- Floating `‹ Recent` pill appears at the top-right of the chat card to bring it back. Anchored at `top: -34px` so it sits above the card eyebrow without overlapping "Fresh thread" / "Resumed conversation" copy.
- Persisted via `localStorage` key `tutor-rail-collapsed-v1` so the user's choice survives reloads.
- Mobile breakpoint (`max-width: 980px`) hides the affordance entirely — the rail already stacks under the chat there, so collapsing doesn't make sense.

### Numbers (1440×900 laptop, measured in Playwright)

| state | chat card width | gain vs old `today-grid` |
| --- | --- | --- |
| old (today-grid)     |   720 px |  baseline |
| new, rail expanded   |   780 px |  +60 px (+8%) |
| new, rail collapsed  | 1100 px | +380 px (+53%) |

### Files

- `frontend/src/app/v8.css` — added `.tutor-grid`, `.tutor-grid.rail-collapsed`, `.tutor-rail-reopen`, `.tutor-rail-collapse`, mobile breakpoint guard.
- `frontend/src/components/v8/screens/tutor-screen.tsx` — added `RAIL_COLLAPSED_KEY`, `railCollapsed` state with lazy initial from localStorage, `toggleRail` callback, swapped `today-grid` → `tutor-grid` with conditional `rail-collapsed` class, added inline collapse button and floating reopen pill.

### Verification (Playwright)

1. Initial render: card 780px, rail visible, collapse button at rail header.
2. Click collapse: card grows to 1100px, rail fades + slides out, reopen pill appears top-right above the card. localStorage flips to `"1"`.
3. Reload: collapsed state persists. Card still 1100px, reopen pill still visible.
4. Click reopen pill: rail comes back, card returns to 780px, reopen pill removed. localStorage flips to `"0"`.

### Net change in this phase

- **Frontend:** 1 CSS edit (`v8.css`, ~95 added lines), 1 component edit (`tutor-screen.tsx`, ~40 added lines).
- **Lint:** 0 new errors on changed files.

---

## P-Path1 + P-Promo1 — Path & Promotion screens to production (2026-04-27)

Pattern continues from Today / Tutor / Notebook / Job Readiness / Catalog.
Both screens were full of editorial fallbacks (DEFAULT_STARS, DEFAULT_LESSONS,
hardcoded labs A/B/C, hardcoded "$89", `motivationToRole` map, `overallProgress
= 78` fallback). Replaced with two new aggregator endpoints that hydrate the
entire screens in one round-trip.

### Schema

Migration `0048_path_promotion`:
- `users.promoted_at` (timestamp, nullable) — set when the gate flips for
  the first time so the takeover fires once and only once.
- `users.promoted_to_role` (string 128, nullable) — what they were
  promoted to. Lets later visits render "Promoted on Apr 27, 2026".

No new tables. The Path screen reuses existing
`skills` / `user_skill_states` / `saved_skill_path` / `lessons` /
`exercises` / `exercise_submissions` (peer-shared filter). Promotion
reuses `goal_contracts` / `student_progress` / `exercise_submissions`
(capstone) / `interview_sessions`.

### Backend

**`/api/v1/path/summary`** (GET) — assembles:
- 6-star constellation (5 ordered skills from saved-path or
  difficulty-sorted; 6th star is the goal from `goal.target_role`).
- 3-rung ladder: current course (with a 4-lesson window that ALWAYS
  includes the active "current" lesson — never leaves the user with 4
  done lessons and no "current" card to act on), upsell (lowest-priced
  unenrolled course, real `price_cents`/`metadata`), goal step.
- Lesson rows include real labs (Exercise rows joined on `lesson_id`)
  with status derived from per-user submissions.
- Proof wall: top 2 peer-shared submissions ordered by score desc.

**`/api/v1/promotion/summary`** (GET) — four rungs derived from real signals:
1. `lessons_foundation` — first ~50% of lessons.
2. `lessons_complete` — every enrolled lesson.
3. `capstone_submitted` — student has submitted a capstone exercise.
4. `interviews_complete` — 2+ completed `interview_sessions`.

Plus `gate_status` ∈ `{not_ready, ready_to_promote, promoted}`, role
transition (from `goal.target_role`, not the old motivation map),
stats, and `user_first_name`. Strict-ordering rule: rungs 3 and 4 stay
locked until the prior rung is done — even if a student stamps a
capstone draft early, the visual ladder reads honestly.

**`/api/v1/promotion/confirm`** (POST) — flips `users.promoted_at` once
the gate is `ready_to_promote`. Idempotent (a second call returns the
existing record). 409 when the gate isn't open.

### Pure-function design

Both aggregators ran heavy queries via `asyncio.gather`. The rung
builder for Promotion is a pure function (`_build_rungs`) over four
counts so it's trivial to unit test (4 boundary tests cover the
state-machine corners).

### Frontend

- `lib/api-client.ts` — added `pathApi.summary`, `promotionApi.summary`,
  `promotionApi.confirm` plus all schema types (`PathStar`, `PathLab`,
  `PathLevel`, `PromotionRung`, `PromotionGateStatus`, etc.).
- `lib/hooks/use-path-summary.ts` — single `useQuery` gated by
  `isAuthenticated`, 30s `staleTime`.
- `lib/hooks/use-promotion-summary.ts` — `useQuery` + `useMutation`.
  The mutation's `onSuccess` patches the cached summary so the screen
  flips to `gate_status: "promoted"` without a refetch round-trip.
- `components/v8/screens/path-screen.tsx` — full rewrite. ~530 → ~410
  lines. All hardcoded copy and lab samples deleted. Lab tray expands
  on the current lesson; "Labs coming soon" empty state when an active
  lesson has no exercises seeded yet.
- `components/v8/screens/promotion-screen.tsx` — full rewrite. The
  takeover now fires only when `gate_status === "ready_to_promote"`
  (auto-opens once on first eligibility, can be reopened from the
  "Open promotion ceremony" button). `Begin <role>` POSTs `/confirm`
  and routes to `/today` on settle. Already-promoted state shows
  "Promoted on <date>" disabled.

### Demo seed

- `_ensure_path_labs` — 3 labs per lesson on the first 10 lessons of
  Python Foundations (so the lesson window's current lesson always has
  labs). First lab on lesson 1 marked passed.
- `_ensure_proof_wall_submissions` — 2 peer-shared submissions with
  scores 87 and 91 so the proof wall renders 2 cards.
- `_ensure_promotion_interviews` — 1 completed interview so the rung
  reads "1/2 in progress" rather than locked at 0.
- `_ensure_promotion_skill_states` — 5 mastery rows on the canonical
  production slugs (`python-basics`, `python-data-structures`,
  `http-rest`) so the constellation has visible done/current stars.

All idempotent — running the seed twice no-ops cleanly.

### Tests

- **Backend (27 new):** 11 in `test_path_summary_service.py` (helpers +
  full integration), 9 in `test_promotion_summary_service.py` (rung
  builder + integration + idempotent confirm), 2 in
  `test_path_summary_route.py`, 3 in `test_promotion_summary_route.py`,
  plus 2 covering strict ordering on the rung builder. **27/27 pass.**
- **Frontend (13 new):** 7 in `path-screen.test.tsx` (constellation +
  lessons + lab tray + upsell + proof wall + browse-catalog fallback +
  empty proof wall), 6 in `promotion-screen.test.tsx` (rung rendering +
  target_role + locked button + ready button + promoted button +
  confirm flow). **13/13 pass.**

### Verification

Hit both endpoints as `demo@pae.dev`:
- `/path/summary` returns 6-star constellation (`Python Basics → Python
  Data Structures → HTTP & REST [current] → Git Workflow → Tailwind CSS
  → Data Analyst [goal]`), Level 1 with 4 lessons (including current
  lesson 9 with 3 labs), upsell (Python Developer), goal (Data Analyst),
  2 proof-wall entries.
- `/promotion/summary` returns 4 rungs in honest state: foundation
  current (63% — 12/19), lessons_complete locked, capstone locked
  (strict ordering — early draft doesn't count), interviews locked.
  `gate_status: not_ready`. `role: Python Developer → Data Analyst`.

### Net change in this phase

- **Backend:** 1 migration, 2 schemas, 2 services, 2 routes (3
  endpoints), seed extended (4 new helpers), 4 test files (27 tests).
- **Frontend:** 1 api-client expansion, 2 new hooks, 2 fully-rewritten
  screens (~940 lines deleted, ~620 added), 2 new test files (13
  tests).
- **Lint:** 0 new errors on changed files.

