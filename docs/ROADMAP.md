# PAE Platform — Production Roadmap

**Goal:** Transform the platform from a generic LMS into a $1000-feel, student-obsessed learning workspace. Ship 180 improvements across ~6 months, one validated feature at a time.

**Mode of work:** Agents pick up tasks from this document, complete one ticket at a time, check it off, move on. Tasks are ordered by dependency. No agent may start a task whose dependencies are incomplete.

---

## Rules of Engagement (for all agents)

1. **One ticket at a time.** No multi-ticket PRs. Each ticket = one focused change = one commit or PR.
2. **Check dependencies.** Before starting, verify every `Depends on:` line is marked `[x] DONE`.
3. **Worktrees required for parallel work.** Each agent works in its own worktree: `git worktree add ../pae-<ticket-id> <branch>`. Never share a worktree.
4. **No overlap zones.** If a ticket touches a file currently owned by another in-flight ticket, wait. Files listed in `Touches:` are claimed until the ticket is merged.
5. **Every ticket ships with:** Storybook story (if UI), test (unit/integration/e2e as applicable), screenshot in PR description.
6. **Backend changes require migration.** Use Alembic. Never hand-edit DB.
7. **Mark tickets complete here** by changing `[ ]` → `[x] DONE (commit-sha)` when merged to main.
8. **Telemetry from day one.** Every user-facing feature emits a structured event. No event = ticket incomplete.

---

## Current State (baseline — 2026-04-17)

**Frontend routes present:** `(portal)/` → chat, courses, dashboard, exercises, lessons, progress. `(public)/` → about, agents, login, pricing, register.

**Backend routes:** admin, agents, auth, billing, courses, demo, exercises, health, lessons, oauth, stream, students, webhooks.

**DB models:** User, Course, Lesson, Exercise, ExerciseSubmission, Enrollment, StudentProgress, QuizResult, McqBank, AgentAction, Notification, Payment.

**Stack:** Next.js 15 (App Router, Tailwind 4, shadcn/ui, Zustand, React Query) + FastAPI + Postgres + Redis + LangGraph MOA + MiniMax LLM.

**What works:** Auth, basic chat with SSE streaming, markdown rendering with syntax highlight, mode chips.

**What's weak:** Dashboard is generic card grid. Courses are linear. Exercises are LeetCode-style. Progress is XP/streaks. No memory across chat sessions. No skill graph. No goal contract.

---

## Phase Structure

- **Phase 0 — Foundation (1 feature, solo):** Today screen + goal contract. Sets the design language.
- **Phase 1 — Paradigm (3 features, sequential):** Skill Map, Studio (merged chat+code), Receipts.
- **Phase 2 — Depth (15 features, parallel OK):** Key differentiators.
- **Phase 3 — Breadth (remaining 160 tickets, parallel OK):** Polish, community, career, instructor tools.

---

# PHASE 0 — FOUNDATION

**Goal:** Establish the design language. One person, one surface, no parallelism. When done, this is the template every other feature follows.

## P0-0: Design Research & Reference Library
- [ ] DONE
- **Depends on:** none
- **Touches:** `docs/design/` (new folder), `docs/design/references.md`, `docs/design/component-bar.md`, `docs/design/motion-spec.md`.
- **What:** Before any UI ships, produce a design reference pack the whole team (and agents) works from.
  1. Curate references from `ui-ux-pro-max`, `awesome-design.md`, Linear, Raycast, Arc, Posthog, Vercel, Stripe, Cron, Superhuman, Notion, Figma. Capture screenshots/links in `references.md` with notes on what each does well.
  2. `component-bar.md`: for each primitive (Button, Input, Select, Dialog, Tooltip, Table, Tabs, Toast, Command, etc.) define the "$1000 bar" — interaction states, motion, accessibility, keyboard, edge cases. Include do/don't examples.
  3. `motion-spec.md`: timing curves, duration tokens, entrance/exit patterns, gesture expectations.
- **Acceptance:** User reviews and signs off on the reference pack. This becomes mandatory reading for every subsequent UI ticket.

## P0-0b: UI Component Library Audit
- [ ] DONE
- **Depends on:** P0-0
- **Touches:** `docs/design/component-audit.md` (new).
- **What:** Go through every component in `frontend/src/components/ui/` and `frontend/src/components/features/` and score it against the component-bar. For each: current state, gaps, priority to upgrade (P0/P1/P2), dependencies. Output is a table that drives P0.5 tickets.
- **Acceptance:** Every existing component has a row in the audit. User reviews priority ordering.

## P0-1: Goal Contract — Backend
- [ ] DONE
- **Depends on:** none
- **Touches:** `backend/app/models/goal_contract.py` (new), `backend/app/schemas/goal_contract.py` (new), `backend/app/api/v1/routes/goals.py` (new), `backend/app/main.py` (register router), new Alembic migration.
- **What:** New table `goal_contracts` with columns: `id`, `user_id FK`, `motivation (enum: career_switch/skill_up/curiosity/interview)`, `deadline_months (int)`, `success_statement (text)`, `created_at`, `updated_at`. CRUD endpoints: `POST/GET/PATCH /api/v1/goals/me`. One goal per user (upsert).
- **Telemetry:** `goal.created`, `goal.updated` events.
- **Acceptance:** Migration runs cleanly. `pytest backend/tests/api/test_goals.py` passes (write these tests). OpenAPI schema regenerated.

## P0-2: Goal Contract — Onboarding UI
- **Depends on:** P0-1
- **Touches:** `frontend/src/app/(portal)/onboarding/page.tsx` (new), `frontend/src/components/features/goal-contract-form.tsx` (new), `frontend/src/lib/api-client.ts` (regen).
- **What:** 3-step onboarding after register: (1) motivation buttons, (2) deadline chips, (3) success sentence textarea. Saves to backend. Auto-redirect to `/today` after save. Skippable — can fill later from Settings.
- **Design rule:** No card soup. Full-viewport centered flow. Large type. One decision per screen. Subtle progress bar (3 dots).
- **Telemetry:** `onboarding.step_viewed`, `onboarding.completed`, `onboarding.skipped`.
- **Acceptance:** Storybook story for `GoalContractForm`. Playwright e2e: register → onboarding → today. Mobile responsive.

## P0-3: Today Screen — Route + Shell
- **Depends on:** P0-1
- **Touches:** `frontend/src/app/(portal)/today/page.tsx` (new), `frontend/src/app/(portal)/layout.tsx` (add nav link, mark Today as default landing), `frontend/src/components/layouts/portal-sidebar.tsx` (if exists) or wherever nav lives.
- **What:** New route `/today`. Make it the default redirect after login (replaces `/dashboard` as landing, but do not delete dashboard yet). Empty shell for now — will be filled by subsequent tickets.
- **Acceptance:** Logged-in user lands on `/today`. Existing `/dashboard` still reachable.

## P0-4: Today Screen — Goal Banner
- **Depends on:** P0-3
- **Touches:** `frontend/src/components/features/today/goal-banner.tsx` (new), `frontend/src/app/(portal)/today/page.tsx`.
- **What:** Top strip shows: "You're working toward [success_statement] by [deadline]. [N] weeks remaining." If no goal → CTA to onboarding. Editable inline (click to edit).
- **Design rule:** Not a card. A full-width banner with generous whitespace. One accent color. Typography does the hierarchy.
- **Telemetry:** `today.goal_banner_clicked`, `today.goal_edited_inline`.

## P0-5: Today Screen — Next Action Card
- **Depends on:** P0-3
- **Touches:** `frontend/src/components/features/today/next-action.tsx` (new), `backend/app/api/v1/routes/students.py` (new endpoint `GET /students/me/next-action`).
- **What:** Backend computes a single next action for the user: resume last exercise, review a lesson, or a starter task if new. Frontend displays as a large, single focal point with a CTA button.
- **Logic (v1, simple):** If student has an unfinished exercise submission in last 7 days → resume that. Else if enrolled in a course with unfinished lesson → next lesson. Else → "Pick a course" nudge.
- **Telemetry:** `today.next_action_shown`, `today.next_action_clicked`.

## P0-6: Today Screen — Reflection Prompt
- **Depends on:** P0-3
- **Touches:** `frontend/src/components/features/today/reflection.tsx` (new), `backend/app/models/reflection.py` (new model), `backend/app/api/v1/routes/reflections.py` (new).
- **What:** Small card: "Yesterday you were working on X. Has it clicked? [yes / still confused / not sure]". Clicks log to `reflections` table. If "still confused" → deep-link into Studio with that topic loaded.
- **Telemetry:** `reflection.prompted`, `reflection.answered`.

## P0-7: Today Screen — Signal from Reality
- **Depends on:** P0-3
- **Touches:** `frontend/src/components/features/today/signal-card.tsx` (new), `backend/app/models/signal.py` (new), `backend/app/services/signal_service.py` (new), seed data file.
- **What:** Rotating daily card: an interview question, a real GitHub bug, an arxiv paper one-liner, a job posting. Stored in `signals` table, one shown per day per user (deterministic hash of `user_id + date`).
- **v1 content:** 30 hand-curated signals seeded via a fixture. No live fetching yet (defer to Phase 3).
- **Telemetry:** `signal.shown`, `signal.clicked`.

## P0-8: Today Screen — Polish Pass
- **Depends on:** P0-4, P0-5, P0-6, P0-7
- **Touches:** `frontend/src/app/(portal)/today/page.tsx`, all `today/*` components.
- **What:** Final design pass. Verify: no scroll on 1440×900, mobile layout stacks correctly, dark mode works, animations subtle (200ms max), typography hierarchy reads cold. Add micro-copy review.
- **Acceptance:** Design review with the user. This is the template for all future surfaces.

**Phase 0 complete when:** All P0 tickets `[x] DONE` and user signs off on the Today screen quality.

---

# PHASE 0.5 — UI COMPONENT LIBRARY UPGRADE

**Goal:** Before Phase 1 features ship, rebuild the primitive component layer so every downstream ticket inherits $1000-feel automatically. No feature work happens here — only component-level quality.

**Why this phase exists:** Current components are default shadcn/ui — functional but basic. Building Skill Map / Studio / Receipts on top of basic primitives will produce a basic-looking platform no matter how good the features are. Fix the foundation first.

**Parallelism:** High. Components are mostly independent — up to 5 agents can run in parallel worktrees.

## P0.5-01: Button system
- **Depends on:** P0-0, P0-0b
- **Touches:** `frontend/src/components/ui/button.tsx`, Storybook stories.
- **What:** Variants (primary, secondary, ghost, destructive, link). States (idle, hover, active, focus, loading, disabled, success). Loading spinner inline. Haptic-feel press animation (scale + shadow). Keyboard focus ring. Icon-left / icon-right / icon-only variants. Size scale (xs/sm/md/lg).
- **Acceptance:** All states visible in Storybook. Keyboard-only demo passes. Press animation feels tactile.

## P0.5-02: Input & Textarea
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/input.tsx`, `frontend/src/components/ui/textarea.tsx`.
- **What:** Label animation (float on focus). Inline validation states with icons. Character counter for textarea. Clear button. Paste-enhanced (e.g., URL detection). Autosize for textarea. Error/success color transitions.

## P0.5-03: Select & Combobox
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/select.tsx`, `frontend/src/components/ui/combobox.tsx`.
- **What:** Searchable. Keyboard navigation (arrow keys, Enter, Esc). Async options with loading state. Multi-select chips variant. Virtualized for long lists.

## P0.5-04: Dialog / Sheet / Drawer
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/dialog.tsx`, `frontend/src/components/ui/sheet.tsx`.
- **What:** Enter/exit animations (spring-based). Focus trap. Esc to close. Backdrop blur. Stacking support. Responsive: dialog on desktop, bottom sheet on mobile.

## P0.5-05: Tooltip & Popover
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/tooltip.tsx`, `frontend/src/components/ui/popover.tsx`.
- **What:** Smart positioning (flip on edge). Delay-open (300ms). Delay-close (100ms). Arrow. Keyboard accessible. No layout shift.

## P0.5-06: Toast / Notification system
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/toast.tsx`, `frontend/src/lib/toast.ts`.
- **What:** Slide-in from bottom-right. Stacking. Swipe to dismiss. Action buttons. Auto-dismiss with progress bar. Variants (info/success/warning/error). Use `sonner` library or build on Radix.

## P0.5-07: Table
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/table.tsx`, `frontend/src/components/features/data-table.tsx`.
- **What:** Sortable columns. Row hover + selection. Sticky header. Resizable columns. Column visibility toggle. Empty state illustration. Loading skeleton. Use `@tanstack/react-table`.

## P0.5-08: Tabs
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/tabs.tsx`.
- **What:** Animated underline indicator (layout animation). Keyboard navigation. Scrollable on overflow. Variants: pill / underline / segmented.

## P0.5-09: Card & Surface
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/card.tsx`.
- **What:** Hover lift (subtle, 2px translate). Interactive vs static variants. Skeleton variant. Gradient border option for emphasis. Reduce card usage overall — provide inline alternatives.

## P0.5-10: Command palette (Cmd+K)
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/command-palette.tsx`, `frontend/src/lib/commands.ts`.
- **What:** Global Cmd+K. Fuzzy search. Recent commands. Grouped actions. Keyboard-only navigation. Mount at root. Uses `cmdk` library.
- **Note:** This is the primitive. Actual command registrations come later as features land.

## P0.5-11: Code block & inline code
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/features/markdown-renderer.tsx` (already strong — polish pass).
- **What:** Line hover highlight. Copy button with success animation. Diff mode. Line linking (deep-link to line N). Language picker for live examples.

## P0.5-12: Avatar & user identity
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/features/user-avatar.tsx`.
- **What:** Image + fallback initials with deterministic color. Presence indicator (online/away). Size scale. Group stacking with overflow count.

## P0.5-13: Progress & loading
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/progress.tsx`, `frontend/src/components/ui/skeleton.tsx`, `frontend/src/components/ui/spinner.tsx`.
- **What:** Indeterminate + determinate. Shimmer skeleton matching real layout. Ghost states for each major surface. Spinner variants (inline / centered / overlay).

## P0.5-14: Empty states
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/features/empty-state.tsx` (new).
- **What:** Reusable empty-state shell: illustration slot, heading, body, primary CTA. Library of illustrations (SVG, tasteful, not cartoonish). Used across all list views.

## P0.5-15: Form system
- **Depends on:** P0.5-01 through P0.5-03
- **Touches:** `frontend/src/components/ui/form.tsx`, `frontend/src/lib/forms.ts`.
- **What:** React Hook Form + Zod integration wrapper. Field-level errors. Submit loading state. Optimistic feedback. Dirty-state tracking with unsaved-changes warning.

## P0.5-16: Motion primitives
- **Depends on:** P0-0
- **Touches:** `frontend/src/components/ui/motion.tsx`, `frontend/src/lib/motion.ts`. Add `framer-motion` dep.
- **What:** Reusable motion components: `<FadeIn>`, `<SlideIn>`, `<Stagger>`, `<LayoutGroup>`. Timing tokens from motion-spec. Respects `prefers-reduced-motion`.

## P0.5-17: Keyboard shortcut system
- **Depends on:** P0-0b
- **Touches:** `frontend/src/lib/keyboard.ts`, `frontend/src/components/ui/kbd.tsx`.
- **What:** Global shortcut registry. Context-aware (disabled in inputs). `<Kbd>⌘K</Kbd>` visual component. Help overlay on `?`.

## P0.5-18: Theme tokens refresh
- **Depends on:** P0-0
- **Touches:** `frontend/src/app/globals.css`, `frontend/tailwind.config.ts` (if exists).
- **What:** Audit all CSS tokens against design system. Fix dark mode inconsistencies. Add elevation tokens (shadow scale). Add motion tokens.

## P0.5-19: Icon system
- **Depends on:** P0-0b
- **Touches:** `frontend/src/components/ui/icon.tsx`.
- **What:** Standardize on `lucide-react`. Wrapper component with size/color props. Aria-label enforced. Build icon registry to prevent random imports.

## P0.5-20: Storybook foundation upgrade
- **Depends on:** P0.5-01 through P0.5-19 (continuous)
- **Touches:** `frontend/.storybook/`, all stories.
- **What:** Every primitive above gets: default story, all-variants story, interactive playground, dark-mode toggle, viewport test. Storybook becomes the component source of truth.

**Phase 0.5 complete when:** Every ticket `[x] DONE`, Storybook is complete, user does a review pass comparing components side-by-side against Linear/Raycast/Arc references.

---

# PHASE 1 — PARADIGM SHIFT

**Goal:** Three surfaces that change what the platform *is*. Sequential — each builds on the previous. Pair mode OK (2 agents on clearly split concerns), never more.

## P1-A: Skill Map (replaces Courses grid)

### P1-A-1: Skill graph schema + seed
- **Depends on:** Phase 0 complete
- **Touches:** `backend/app/models/skill.py`, `backend/app/models/skill_edge.py`, `backend/app/models/user_skill_state.py`, Alembic migration, seed fixture.
- **What:** Tables `skills` (id, slug, name, description, difficulty), `skill_edges` (from_skill_id, to_skill_id, edge_type: prereq/related), `user_skill_states` (user_id, skill_id, mastery_level enum, confidence float, last_touched_at). Seed ~40 skills covering the AI engineering curriculum.

### P1-A-2: Skill graph API
- **Depends on:** P1-A-1
- **Touches:** `backend/app/api/v1/routes/skills.py`.
- **What:** `GET /skills/graph` (returns nodes + edges), `GET /skills/me` (my mastery map), `POST /skills/{id}/touch` (increment last_touched).

### P1-A-3: Skill graph diagnostic
- **Depends on:** P1-A-1
- **Touches:** `backend/app/services/diagnostic_service.py`, `backend/app/api/v1/routes/diagnostic.py`.
- **What:** 10-question adaptive quiz at onboarding (idea #2). Each answer updates `user_skill_states`. Optional — skippable.

### P1-A-4: Skill graph visual (frontend)
- **Depends on:** P1-A-2
- **Touches:** `frontend/src/app/(portal)/map/page.tsx`, `frontend/src/components/features/skill-map/*`.
- **What:** Interactive graph using React Flow (add dep). Nodes colored by mastery. Click node → side panel with attached content. Pan/zoom. Mobile: fallback to list view.

### P1-A-5: Content-to-skill linking
- **Depends on:** P1-A-1
- **Touches:** `backend/app/models/lesson.py`, `backend/app/models/exercise.py`, migration adds `skill_id` FK.
- **What:** Every existing lesson/exercise gets tagged to a skill node. Admin UI to manage tags (basic form for now).

### P1-A-6: Path overlay
- **Depends on:** P1-A-4, P0-1 (goal contract)
- **Touches:** `frontend/src/components/features/skill-map/path-overlay.tsx`.
- **What:** Given user's goal, highlight recommended learning path through graph. Dim off-path nodes.

## P1-B: Studio (merged chat + code + trace)

### P1-B-1: Studio route + layout
- **Depends on:** Phase 0 complete
- **Touches:** `frontend/src/app/(portal)/studio/page.tsx`, `frontend/src/components/features/studio/*`.
- **What:** Three-pane layout: code editor (left, ~50%), tutor chat (right, ~35%), execution trace (bottom, collapsible ~15%). Resizable panels.

### P1-B-2: Code editor integration
- **Depends on:** P1-B-1
- **Touches:** `frontend/src/components/features/studio/code-editor.tsx`. Add `@monaco-editor/react` dep.
- **What:** Monaco editor with Python syntax. File tabs. Save to `exercise_submissions` on blur.

### P1-B-3: Tutor context-awareness
- **Depends on:** P1-B-1
- **Touches:** `backend/app/api/v1/routes/stream.py`, `frontend/src/components/features/studio/studio-chat.tsx`.
- **What:** When user sends a message in Studio, current code is attached to context automatically. System prompt adjusted: "You can see the student's code. Reference specific lines. Ask what they tried."

### P1-B-4: Execution trace runner
- **Depends on:** P1-B-1
- **Touches:** `backend/app/api/v1/routes/execute.py` (new), `backend/app/services/sandbox_service.py` (new, uses existing code executor or Docker sandbox).
- **What:** `POST /execute` runs code in a sandbox (time + memory limits), returns stdout, stderr, variable snapshots at each line (via `sys.settrace` or similar for Python). Use existing sandbox infra if present; else minimal subprocess with timeout.

### P1-B-5: Trace visualizer UI
- **Depends on:** P1-B-4
- **Touches:** `frontend/src/components/features/studio/execution-trace.tsx`.
- **What:** Step-through UI. Slider over execution steps. Shows variables at each step. Tensor shapes highlighted.

## P1-C: Receipts (replaces Progress)

### P1-C-1: Kill XP/streaks/badges
- **Depends on:** Phase 0 complete
- **Touches:** `backend/app/models/student_progress.py`, `frontend/src/app/(portal)/progress/*`, migration to deprecate XP columns (don't drop yet — archive).
- **What:** Remove all XP/streak/badge UI. Stop emitting them. Keep data archived 90 days then drop.

### P1-C-2: Growth receipts data model
- **Depends on:** P1-C-1
- **Touches:** `backend/app/models/growth_snapshot.py`, weekly cron via `backend/app/tasks/`.
- **What:** Weekly snapshot table. Captures: mastery delta per skill, concepts touched, exercises completed, chat questions asked, common misconceptions. Cron runs Sunday 00:00 UTC per user.

### P1-C-3: Receipts page
- **Depends on:** P1-C-2
- **Touches:** `frontend/src/app/(portal)/receipts/page.tsx`.
- **What:** Timeline of weekly snapshots. "6 weeks ago vs today" side-by-side diff. Honest gap analysis ("you've avoided X for 3 weeks").

### P1-C-4: Weekly instructor letter (AI-generated)
- **Depends on:** P1-C-2
- **Touches:** `backend/app/services/instructor_letter_service.py`, cron task, email template.
- **What:** Every Sunday, generate a personal 200-word letter using the week's snapshot. Email + in-app notification.

**Phase 1 complete when:** All P1-A, P1-B, P1-C tickets `[x] DONE`. User has a skill map, a working Studio, and receipts instead of progress bars.

---

# PHASE 2 — DIFFERENTIATORS (15 features, parallel OK)

These can run in parallel worktrees once Phase 1 is done. Each has its own dependency list — respect it.

1. **P2-01 Scaffolding decay** — Tutor hints reduce over time per skill. (`stream.py`, `user_skill_states`)
2. **P2-02 Refuses-to-answer Socratic mode** — Tutor setting: never gives direct answers. (`stream.py`)
3. **P2-03 Ugly draft mode** — Studio toggle: forces bad-first-version workflow. (`studio/*`)
4. **P2-04 Senior engineer simulation** — Paired AI senior reviews your PR. (`agents/`, `studio/*`)
5. **P2-05 Spaced repetition engine** — Concepts resurface on forgetting curve. (new `srs_service.py`)
6. **P2-06 Retrieval practice default** — Every session starts with recall questions. (`today/*`)
7. **P2-07 Peer solutions gallery** — After passing, see 5 peer solutions. (`exercises/*`)
8. **P2-08 Code quality feedback** — Beyond pass/fail. (`execute.py`, new `quality_service.py`)
9. **P2-09 Misconception detection** — Patterns across wrong answers. (`stream.py`, new `misconception_service.py`)
10. **P2-10 Interview simulation mode** — Tutor plays interviewer. (`stream.py`, new route)
11. **P2-11 Teach-back mode** — Student explains to tutor. (`stream.py`)
12. **P2-12 Portfolio autopsy** — Auto-assembled portfolio from real work. (`receipts/*`, new service)
13. **P2-13 Confusion heatmap (admin)** — Which lessons generate most questions. (`admin/*`)
14. **P2-14 At-risk student list (admin)** — ML-detected churn risk. (`admin/*`, new service)
15. **P2-15 Command palette (Cmd+K)** — Jump anywhere. Use `cmdk` lib. (`components/ui/command-palette.tsx`)

Each of these gets expanded into its own sub-tickets when its turn comes. Do not pre-expand — details will shift based on Phase 1 learnings.

---

# PHASE 3 — BREADTH (remaining 160 ideas)

Grouped by area. Expanded into sub-tickets when Phase 2 completes. Numbered according to the original 180-list for traceability.

- **Onboarding & Goal-Setting:** #3, #4, #5, #6, #7
- **Today Screen:** #11, #12, #13, #14
- **Skill Map:** #21, #22, #24, #25, #26, #27, #28
- **Studio:** #31, #39, #40, #41, #42, #43, #44, #45, #46, #47, #48, #49, #50
- **AI Tutor:** #51, #52, #53, #54, #55, #56, #57, #58, #59, #60, #61, #62, #63, #64, #67, #68, #69, #70
- **Receipts:** #75, #76, #78, #79, #81, #82, #83
- **Learning Mechanics:** #85, #87, #88, #90, #91, #92, #93, #94, #95, #96
- **Community:** #97, #98, #99, #100, #101, #102, #103, #104, #105, #106, #107, #108
- **UI/UX:** #110, #111, #112, #113, #114, #115, #116, #117, #118, #119, #120, #121, #122, #123, #124, #125, #126, #127, #128, #129, #130
- **Mobile:** #131, #132, #133, #134, #135, #136, #137
- **Instructor/Admin:** #142, #143, #144, #145, #146, #147, #148, #149
- **Engagement:** #150, #151, #152, #153, #154, #155, #156, #157
- **Infrastructure:** #158, #159, #160, #161, #162, #163, #164, #165, #166, #167
- **Career Bridge:** #168, #169, #170, #171, #172, #173, #174, #175, #176
- **Meta/Research:** #177, #178, #179, #180

---

# Parallel Worktree Protocol

When running agents in parallel (Phase 2+):

```bash
# Spawn agent for ticket P2-01:
cd e:/Apps/pae_platform/pae_platform
git worktree add ../pae-p2-01 -b feature/p2-01-scaffolding-decay
# Agent works in ../pae-p2-01, commits, opens PR, gets reviewed, merges.
git worktree remove ../pae-p2-01
```

**Rules:**
- One worktree per ticket. Name: `pae-<ticket-id>`.
- Branch name: `feature/<ticket-id>-<short-slug>`.
- Before starting, agent verifies `Touches:` files are not claimed by another in-flight ticket (check open PRs + this doc).
- Agent updates this doc when merging: `[ ]` → `[x] DONE (commit-sha)`.
- PR template includes: screenshot, telemetry event list, dependency verification.

---

# Design System (applies to all UI tickets)

To achieve $1000-feel, every UI ticket respects these rules. Deviations require justification.

**Typography:**
- System: Inter var, JetBrains Mono for code.
- Scale: 12 / 14 / 16 / 20 / 28 / 40 px. No other sizes.
- Weight-driven hierarchy, not border-driven.

**Spacing:** 4px base grid. 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64.

**Motion:** 150ms for micro (hover, press). 250ms for transitions. 400ms max. `cubic-bezier(0.32, 0.72, 0, 1)` for all.

**Color:** One accent (teal #1D9E75) used sparingly. Grayscale does the heavy lifting. Dark mode first-class.

**Density:** Default is comfortable. Power-user density toggle later (idea #116).

**Interaction:**
- Optimistic UI updates always.
- Sub-200ms response on every interaction.
- Keyboard shortcuts for every action (idea #110).
- No modals when a sheet or inline expansion works.
- Undo everywhere (idea #123).

**Accessibility:** WCAG AA minimum. Keyboard navigation tested. Screen reader labels on every icon button.

---

# Telemetry Standard

Every user-facing action emits:
```json
{
  "event": "surface.action",
  "user_id": "...",
  "timestamp": "...",
  "properties": { ... }
}
```

Stored in `agent_actions` table (extend if needed). Dashboarded in admin view (Phase 2).

---

# Definition of Done (per ticket)

- [ ] Code merged to main via PR.
- [ ] Migration runs cleanly on empty + existing DB.
- [ ] Tests pass in CI.
- [ ] Storybook story (for UI).
- [ ] Screenshot in PR.
- [ ] Telemetry events firing (verified in dev).
- [ ] This doc updated: `[x] DONE (sha)`.
- [ ] No regression in existing screens (smoke tested).
