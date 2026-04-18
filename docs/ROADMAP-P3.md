# Phase 3 — Breadth Execution Plan

**Status**: Phases 0, 0.5, 1, 2 complete. This doc turns the 160 idea-numbers from `ROADMAP.md` into concrete, assignable tickets.

**Principle**: every ticket is (1) independently shippable, (2) touches a bounded file set, (3) has acceptance criteria a reviewer can check, (4) emits at least one telemetry event if user-facing.

**Parallelism model**: 5 agents, each owns 1-3 areas with disjoint file sets. Within an area tickets run sequentially inside that worktree — parallelism is *between* areas, not *within*.

---

## Architectural Decisions (apply to every P3 ticket)

1. **No new frameworks.** Next.js 15 + FastAPI + Postgres + Redis + LangGraph + React Query + Zustand. Every ticket fits this stack.
2. **Service-first backend.** Routes stay ≤30 lines; logic lives in `app/services/*`. Every new feature = new service file or extends an existing one.
3. **Pure-function scoring where possible.** Prefer deterministic analytics over LLM calls (carry P2-14's soft-OR approach forward — see `at_risk_student_service.py`).
4. **Telemetry is not optional.** `agent_actions` table is the event sink. Every user-facing action emits `{event, user_id, ts, properties}`.
5. **Migrations via Alembic.** Never hand-edit DB. One migration per model change.
6. **Frontend tests via Vitest for pure logic; Playwright for flows.** Storybook for new components.
7. **Mobile = responsive, not separate app.** Every new screen tested at 375×667 and 1440×900.
8. **Accessibility gated.** Keyboard path + aria-labels on every interactive element. WCAG AA contrast.
9. **Feature flag for anything reversible.** Add `preferences.{flag}` boolean to `user_preferences` for reversible UX shifts (e.g., density toggle, strict socratic mode).
10. **No emoji in source / UI copy.** Carried from earlier feedback.

---

## Agent-to-Area Assignment

| Agent | Worktree branch | Areas | Tickets |
|---|---|---|---|
| **A1 — UI Polish** | `feature/p3-a1-ui` | UI/UX (#110-130), Mobile (#131-137) | 28 |
| **A2 — Admin & Engagement** | `feature/p3-a2-admin` | Instructor/Admin (#142-149), Engagement (#150-157) | 16 |
| **A3 — Platform** | `feature/p3-a3-platform` | Infrastructure (#158-167), Meta (#177-180) | 14 |
| **A4 — Learning Core** | `feature/p3-a4-learning` | AI Tutor (#51-70), Learning Mechanics (#85-96) | 28 |
| **A5 — Surfaces** | `feature/p3-a5-surfaces` | Onboarding (#3-7), Today (#11-14), Skill Map (#21-28), Studio (#31-50), Receipts (#75-83), Community (#97-108), Career (#168-176) | 74 |

**Why A5 is 74 tickets**: these are polish passes on surfaces already built in Phases 0/1/2. Each is small (≤1 day). A5 works serially through them; if the queue gets too long we split into A5a/A5b later.

---

## AREA 1 — UI/UX (A1, tickets #110-#130)

Touches primarily `frontend/src/components/ui/`, `frontend/src/components/features/`, `frontend/src/app/globals.css`.

- **#110 Global keyboard shortcut overlay** — `?` opens modal listing every shortcut in the app. `frontend/src/components/ui/shortcut-help.tsx` (new), wired via `useShortcut("?")`.
- **#111 Focus-visible ring everywhere** — audit every interactive element; ensure `focus-visible:ring-2 ring-primary ring-offset-2`. Touches `globals.css`, tailwind class migration.
- **#112 Skeleton-match ghost states** — every list/card has a shimmer skeleton matching its real layout. Touches `components/ui/skeleton.tsx`, `features/*`.
- **#113 Inline error recovery** — every React Query error renders a compact retry affordance with a one-line cause instead of a toast. `components/ui/inline-error.tsx` (new).
- **#114 Optimistic UI defaults** — mutations use `useMutation` `onMutate` → optimistic cache update; rollback on error. Apply to: reflection answer, goal edit, srs grade, course enroll.
- **#115 Undo toast for destructive actions** — delete/archive emits an undo toast for 5s. `lib/undo.ts` (new) wraps `mutationFn` with a deferred commit.
- **#116 Density toggle** — `comfortable`/`compact` stored on `user_preferences`. CSS vars switch row heights, paddings. Toggle in settings.
- **#117 Consistent empty states** — audit all list views; each uses `components/features/empty-state.tsx` with action CTA.
- **#118 Consistent page headers** — `components/ui/page-header.tsx` (new): H1 + subtitle + action slot. Replace ad-hoc headers on: dashboard, courses, exercises, receipts, map, studio, today.
- **#119 Command palette everywhere** — already built; verify palette is mounted on `(public)` routes too (currently portal-only). Register `Login`/`Register` commands for logged-out users.
- **#120 Route-level loading bar** — top-of-page progress bar on navigation. Uses `next/navigation`'s `useLinkStatus` (Next 15) or `NProgress`.
- **#121 Consistent section spacing** — tailwind `space-y-*` audit; 32px between major sections on all pages.
- **#122 Breadcrumbs** — `components/ui/breadcrumbs.tsx` (new). Auto-generated from route segments. Render above page-header on: lesson detail, exercise detail, admin subpages.
- **#123 Undo everywhere** — extend #115 pattern to: progress reset, reflection retract, goal unset.
- **#124 Smooth theme transitions** — `globals.css` `color-scheme` transitions 150ms. Prevent flash.
- **#125 Soft shadows audit** — replace hard borders with `shadow-[var(--elevation-*)]` where surface elevation is the point. Tailwind tokens already exist.
- **#126 Typography scale enforcement** — lint rule forbidding inline font-size; all text uses tailwind `text-{size}` tokens (12/14/16/20/28/40).
- **#127 Link vs button consistency** — anything that navigates = `<Link>`; anything that mutates = `<button>`. Audit and fix.
- **#128 Loading priority** — `next/image` `priority` on above-the-fold avatars; defer all others. Lighthouse score target 90+.
- **#129 Consistent toast channel** — replace any remaining `window.alert` or ad-hoc status divs with `toast()` from `sonner`.
- **#130 Dark mode QA pass** — sweep every screen at dark; fix contrast, broken tokens. Ship a `/design/dark-gallery` route that renders all components in dark for reviewer.

---

## AREA 2 — Mobile (A1, tickets #131-#137)

- **#131 Mobile sidebar drawer** — already exists in `portal-layout.tsx`; polish swipe-to-close and edge-swipe-to-open gestures. Uses `framer-motion` drag.
- **#132 Bottom nav on mobile** — 5-tab bar (Today, Map, Studio, Chat, Profile) for <md screens. `components/layouts/mobile-nav.tsx` (new).
- **#133 Pull-to-refresh** — on Today and Receipts lists. `lib/hooks/use-pull-refresh.ts` (new).
- **#134 Responsive tables** — `components/features/data-table.tsx` collapses rows to card stacks at <md. Used by admin students + admin at-risk.
- **#135 Tap targets ≥44px** — audit all buttons/icons; fix the offenders.
- **#136 Mobile keyboard handling** — textarea auto-grows; fixed inputs scroll into view on focus; dismiss keyboard on pane-switch.
- **#137 Offline fallback banner** — service-worker-free: just `navigator.onLine` + toast. Add to root layout.

---

## AREA 3 — Instructor/Admin (A2, tickets #142-#149)

Touches `backend/app/api/v1/routes/admin.py`, `frontend/src/app/admin/*`, new models under `app/models/`.

- **#142 Admin audit log viewer** — `/admin/audit-log` reads `agent_actions` table, searchable/filterable. Backend: `GET /admin/audit-log?user_id=&event=&from=&to=`. Frontend: paginated table with filters.
- **#143 Bulk student actions** — select students → suspend / reset progress / send notification. Backend: `POST /admin/students/bulk` with `{action, student_ids[]}`. Frontend: checkboxes on `/admin/students` + action bar.
- **#144 Course authoring UI** — admin CRUD for courses/lessons beyond the current read-only view. `/admin/courses/{id}/edit` with form that calls existing course+lesson routes.
- **#145 Exercise rubric editor** — inline JSON editor for `exercises.rubric` with preview. `/admin/exercises/{id}/rubric`.
- **#146 Student intervention notes** — admin-only text notes per student, stored in new `student_notes` table. UI: side panel on `/admin/students/{id}`.
- **#147 Cohort analytics** — `/admin/analytics/cohort` — choose date range → retention curve, completion curve, chat volume. Deterministic SQL aggregations, no LLM.
- **#148 Content performance** — `/admin/analytics/content` — per-lesson: views, completion %, avg question count, confusion score (reuses `confusion_heatmap_service`).
- **#149 Admin alert rules** — admin creates rules like "notify me if >10 at-risk students appear this week". Table: `admin_alert_rules`, evaluator runs in a Celery beat task.

---

## AREA 4 — Engagement (A2, tickets #150-#157)

- **#150 Daily streak without gamification** — show "you've shown up N days this week" on Today. No points, no loss aversion. Pure count from `agent_actions` activity.
- **#151 Weekly cadence prompts** — Sunday email: "Pick your 3 focus items for the week". Stores as `weekly_intentions` rows.
- **#152 Inactivity re-engagement** — existing `disrupt_prevention` agent; wire it to a weekly cron that sends to users inactive ≥7d.
- **#153 Email digest opt-in** — `user_preferences.email_digest_frequency` enum. UI in settings.
- **#154 Micro-wins surface** — on Today, show "You unblocked X yesterday" if misconception resolved. Deterministic lookup.
- **#155 Progress-sharing card** — export Today's state as a shareable PNG via Next.js OG-image generator. `/api/og/progress/{user_id}`.
- **#156 Public accomplishments profile** — opt-in `/u/{slug}` public page showing course completions + portfolio autopsy results.
- **#157 Weekly leaderboard (learning-depth based)** — ranks by concepts-touched × mastery-gain, not XP. Opt-in; visible only to those who joined.

---

## AREA 5 — Infrastructure (A3, tickets #158-#167)

- **#158 Structured logging audit** — every `print()`/`logging.getLogger()` replaced with `structlog` (per CLAUDE.md rule). grep-and-fix sweep.
- **#159 Request ID propagation** — middleware stamps `x-request-id`; every log line includes it; frontend fetch passes it back on retry.
- **#160 Health checks deepened** — `/health` returns `{db, redis, llm}` status. K8s-style liveness vs readiness.
- **#161 Rate limit tiering** — slowapi limits: `10/min` anon, `60/min` auth, `300/min` admin. Configurable via settings.
- **#162 DB connection pool tuning** — measure pool saturation; set `pool_size=20, max_overflow=10` baseline. Document in ADR.
- **#163 Redis key namespacing** — prefix every key with `pae:{env}:{feature}:`. Lint rule in a conftest scan.
- **#164 Backup & restore runbook** — `docs/ops/backup-restore.md`. `pg_dump`/`pg_restore` recipes + Redis snapshot.
- **#165 Cost monitoring** — log every Claude API call's input/output tokens to `agent_actions.metadata`. Admin dashboard aggregates $/day.
- **#166 Graceful shutdown** — FastAPI `lifespan` drains in-flight requests; Celery worker `SIGTERM` waits for current task.
- **#167 CI gates** — GitHub Actions: mypy, ruff, pytest, vitest, `pnpm build` all required green before merge.

---

## AREA 6 — Meta/Research (A3, tickets #177-#180)

- **#177 Feedback widget** — floating "Send feedback" on every portal page. Writes to `feedback` table. Admin triages in `/admin/feedback`.
- **#178 A/B experiment framework** — `experiments` table + `lib/experiments.ts` hook that reads active experiments and emits `experiment.exposed` events.
- **#179 Session replay opt-in** — self-hosted, no third-party. Store DOM-snapshot-every-2s deltas for users who opted in. Privacy-first: PII masked via attribute allowlist.
- **#180 Platform pulse dashboard** — `/admin/pulse` — single-screen health: DAU, conversion, chat volume, error rate, cost/day. Pure SQL + Tremor charts.

---

## AREA 7 — AI Tutor (A4, tickets #51-#70)

Touches `backend/app/api/v1/routes/stream.py`, `backend/app/agents/*`, `frontend/src/app/(portal)/chat/`.

- **#51 Multi-turn memory per skill** — tutor remembers last 5 convos per `user × skill`. Stores in `conversation_memory` table; injected into system prompt.
- **#52 Citation-grounded answers** — tutor responses include `[L12]`-style links to lesson anchors when answering from known content.
- **#53 Code-aware follow-ups** — when Studio code is in context, tutor suggests 3 clarifying questions as pill buttons below the stream.
- **#54 Intent clarification pass** — if MOA classifier confidence <0.6, tutor asks "Do you want (a) a direct answer, (b) a hint, (c) a challenge?" before replying.
- **#55 Disagreement pushback** — if student asserts something technically wrong, tutor disagrees politely with evidence. Prompt tweak + guardrail eval.
- **#56 Response length chip** — user toggles `short / normal / deep` mode. Persists to preferences.
- **#57 Explain-like-I-know-X** — user picks a skill they already know ("explain RAG like I know SQL"). Tutor analogizes to that skill.
- **#58 Multi-modal input** — paste an image (diagram, error screenshot). Claude vision API handles it.
- **#59 Voice input** — Web Speech API → transcription → chat. No TTS yet.
- **#60 Session summary button** — "Summarize what we covered" → 3-bullet recap saved to conversation metadata.
- **#61 Bookmarks** — star a tutor message; view bookmarks in `/chat/saved`.
- **#62 Share conversation** — export to markdown; copy link (view-only) to another user.
- **#63 Regenerate response** — "Try again" button on any AI message; keeps prior in history with a collapsed strike-through.
- **#64 Stop mid-stream** — already likely exists; verify and polish.
- **#67 Disagreement log** — when #55 fires, log to `misconceptions` table for instructor visibility.
- **#68 Socratic intensity slider** — 0=answers, 1=hints, 2=questions-only, 3=questions with leading scaffolds. Replaces the existing binary strict-socratic toggle.
- **#69 Follow-up questions auto-suggest** — at end of every tutor turn, show 3 suggested next questions based on context.
- **#70 Per-skill tutor persona** — assign each skill node a persona (e.g., "strict SRE" for ops, "gentle explainer" for fundamentals). Prompt injects it.

---

## AREA 8 — Learning Mechanics (A4, tickets #85-#96)

Touches `backend/app/services/srs_service.py`, new services, and frontend exercise/lesson surfaces.

- **#85 Interleaving prompts** — when student does 3 exercises in same skill, suggest switching to an adjacent skill. Deterministic rule.
- **#87 Elaborative interrogation** — on lesson complete, prompt "Why do you think this works?" before moving on. Store answer to `reflections`.
- **#88 Self-explanation prompts** — on exercise submit, "Explain your approach in one sentence" before seeing the grade.
- **#90 Desirable difficulty** — adaptive difficulty: if last 3 exercises passed first try, inject a harder one. Rule in `exercise_service`.
- **#91 Worked examples** — every exercise has an optional "show a worked example of a similar problem" reveal.
- **#92 Fading scaffolds** — carries P2-01's scaffolding decay further: the *number* of hint levels also decays over repeated attempts.
- **#93 Testing effect** — weekly "review last week" quiz assembled from SRS due cards. New cron.
- **#94 Concept map before content** — optional at start of lesson: "Here's the map of what you're about to learn". Uses skill graph.
- **#95 Post-lesson retrieval** — 2-minute recall quiz immediately after a lesson; answers update `user_skill_states.confidence`.
- **#96 Generative question bank** — students can submit questions about a lesson; admin-approved questions join `mcq_bank`.

---

## AREA 9 — Onboarding polish (A5, tickets #3-#7)

- **#3 Goal contract coach** — tutor-guided onboarding: instead of form fields, have MOA ask motivation/deadline/success in chat. Fallback to form if student skips chat.
- **#4 Prerequisite diagnostic opt-in** — P1-A-3 diagnostic is already built; add explicit "take 10-min diagnostic" CTA on onboarding step 4.
- **#5 Time-per-week commitment** — step added to onboarding: select 3-5/6-10/11+ hours. Stored on `goal_contracts.weekly_hours`.
- **#6 Accountability partner import** — optional: paste friend's email to invite as accountability partner. Creates pending `partnership` row.
- **#7 First-day success plan** — after onboarding, generate a 3-day starter plan using skill graph + goal. Shown on Today.

## AREA 10 — Today polish (A5, tickets #11-#14)

- **#11 Intention text** — daily "what do you want to accomplish today" free-text, 1-line. Stored in `daily_intentions`.
- **#12 Time-boxed focus** — 25-min pomodoro starter on Today ("Start a 25-min session"). Pure frontend timer; logs start/end to `focus_sessions`.
- **#13 End-of-day reflection** — card after 6pm local: "how did today go? [good / ok / rough]". Logs to `reflections` with `kind='day_end'`.
- **#14 Morning vs evening content** — Today card selection adjusts based on local hour: morning → intention + next action; evening → reflection + tomorrow preview.

## AREA 11 — Skill Map polish (A5, tickets #21-#28)

- **#21 Cluster collapse** — skill clusters collapse to category bubbles when zoomed out. React Flow layout change.
- **#22 Mastery legend** — color legend always visible bottom-right of map.
- **#24 Path saving** — user pins a path; shown on Today as "current path".
- **#25 Skill detail side panel** — click node → right drawer with attached lessons/exercises + mastery history.
- **#26 Prereq warning** — if user jumps to a node whose prereqs aren't met, warn with option to see prereq path.
- **#27 Progress rings on nodes** — each node shows a tiny ring representing mastery %.
- **#28 Search skills** — map has a searchbox that zooms-to-node on select.

## AREA 12 — Studio polish (A5, tickets #31, #39-#50)

- **#31 File tree** — left-most pane: project file tree for multi-file exercises.
- **#39 Diff view** — compare your solution vs a reference solution after passing.
- **#40 Inline tutor pins** — tutor can "pin" a comment to a specific code line; shown as gutter icon.
- **#41 Run history** — last 20 runs visible as a collapsible list with pass/fail chip.
- **#42 Local persistence** — autosave drafts to `localStorage` keyed by exercise id.
- **#43 Format on save** — hook `ruff format` via backend on blur for Python files.
- **#44 Lint as you type** — lightweight linter (via Monaco marker API) surfacing undefined names / unused imports.
- **#45 Live preview for prompts** — if exercise involves writing a Claude prompt, a "Try it" button sends to the API.
- **#46 Copy-with-context** — copy code → clipboard gets `// from: exercise.title` comment prefix.
- **#47 Keyboard shortcut map** — Studio `?` shortcut overlay listing Studio-specific shortcuts.
- **#48 Snippet insertion** — `/` command in editor inserts parameterized snippets (e.g., LangGraph StateGraph skeleton).
- **#49 Multi-tab editing** — tabs across the top of the editor for multiple open files.
- **#50 Per-exercise tutor context** — tutor system prompt auto-loads exercise description + test cases.

## AREA 13 — Receipts polish (A5, tickets #75-#83)

- **#75 Week-on-week diff** — side-by-side deltas vs previous week.
- **#76 Concept coverage map** — receipts page shows a miniaturized skill map colored by this week's activity.
- **#78 Gap analysis** — honest "you've avoided X for 3 weeks" card.
- **#79 Portfolio items surfaced** — top 3 completed exercises this week highlighted.
- **#81 Reflection aggregation** — all reflections this week, grouped.
- **#82 Time investment chart** — hours spent per area, stacked bar.
- **#83 Next-week suggestion** — generated 3-item focus list for next week.

## AREA 14 — Community (A5, tickets #97-#108)

- **#97 Study groups** — create/join groups of ≤8. `study_groups` table.
- **#98 Group chat** — per-group thread, stored in Postgres (not websockets yet — polling).
- **#99 Shared goals** — groups can declare a shared weekly goal.
- **#100 Mentor matching** — pair a group with an alumni mentor (future: manual matching via admin).
- **#101 Peer review exchange** — submit your exercise solution; get assigned 2 peers to review it; you must review 2 to unlock feedback. Double-blind.
- **#102 Question wall** — per-lesson Q&A thread visible to all enrolled students.
- **#103 Upvote answers** — on question wall; surfaces best answers.
- **#104 Helpfulness badge** — earn tokens for answers marked helpful; tokens grant priority tutor queueing during load (soft gating).
- **#105 Study sprints** — group-declared focused sessions (e.g., "Saturday 10-12 we all do RAG exercises").
- **#106 Group progress wall** — anonymized group-level mastery distribution.
- **#107 Showcase demo day** — monthly event slot for groups to present projects (calendar entry + signup).
- **#108 Community moderation queue** — admin view for flagged posts/messages.

## AREA 15 — Career (A5, tickets #168-#176)

- **#168 Resume builder** — one-click export of portfolio autopsy + skill mastery to a structured PDF resume.
- **#169 Interview question bank** — curated set of AI engineering interview questions, searchable, linked to skills.
- **#170 Mock-interview scheduling** — reuse P2 interview simulation; add calendar scheduling so you can pre-commit to sessions.
- **#171 Job board integration** — paste a JD; backend scores fit using your skill map. LLM-assisted.
- **#172 Skill gap vs JD** — from #171, highlights which skills the JD expects that you haven't touched.
- **#173 Learning plan for a JD** — from #172, generate a 4-week plan to close the gaps.
- **#174 LinkedIn blurb generator** — turn receipts into a 3-sentence LinkedIn-ready update per week.
- **#175 Portfolio public URL** — opt-in `/portfolio/{slug}` public page.
- **#176 Referral connections** — alumni opt-in to receive cold intros from current students; admin brokers.

---

## Cross-cutting model & schema additions

Aggregated new tables from the above (A3/A4 create migrations as each ticket lands):

| Table | Purpose | Added by |
|---|---|---|
| `user_preferences` | Feature flags (density, strict socratic, digest freq) | already exists — add columns |
| `student_notes` | Admin notes per student | #146 |
| `admin_alert_rules` | Admin-defined alerts | #149 |
| `weekly_intentions` | Weekly focus items | #151 |
| `daily_intentions` | Daily intention text | #11 |
| `focus_sessions` | Pomodoro timer logs | #12 |
| `conversation_memory` | Per-skill tutor memory | #51 |
| `experiments` | A/B flags | #178 |
| `feedback` | User feedback | #177 |
| `study_groups` | Community groups | #97 |
| `partnerships` | Accountability pairs | #6 |

---

## Parallel Worktree Bring-up

Each agent gets:
```bash
cd e:/Apps/pae_platform/pae_platform
git worktree add ../pae-a1 -b feature/p3-a1-ui
git worktree add ../pae-a2 -b feature/p3-a2-admin
git worktree add ../pae-a3 -b feature/p3-a3-platform
git worktree add ../pae-a4 -b feature/p3-a4-learning
git worktree add ../pae-a5 -b feature/p3-a5-surfaces
```

**Coordination protocol:**
- Each agent keeps a `docs/AGENT-{ID}-LOG.md` in its worktree listing completed ticket ids + commit shas.
- Shared files (e.g., `user_preferences.py`, `globals.css`, `portal-layout.tsx`) require a coordination note — agent pings on chat before editing. For P3, we pre-declare which agent owns each shared file to avoid this:

| File | Owner |
|---|---|
| `frontend/src/app/globals.css` | A1 |
| `frontend/src/components/layouts/portal-layout.tsx` | A1 |
| `backend/app/models/user_preferences.py` | A1 (A2/A4 append columns via separate migrations) |
| `backend/app/api/v1/routes/admin.py` | A2 |
| `backend/app/api/v1/routes/stream.py` | A4 |
| `frontend/src/app/(portal)/studio/*` | A5 |
| `frontend/src/app/(portal)/today/*` | A5 |

Any other file is free-game; first-to-touch wins, others rebase.

---

## Definition of Done (inherits from root ROADMAP.md)

Unchanged: tests pass, migration clean, Storybook for UI, telemetry firing, ROADMAP-P3 row marked `[x] DONE (sha)`.
