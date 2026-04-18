# Phase 3 — Critic Pass & Execution Plan

**Purpose:** Resumable state tracker. Started 2026-04-18. Each ticket has `[ ]` (not started), `[~]` (in progress), or `[x] DONE (sha)` (shipped).

**Principle (frustrated-critic):** every ticket must answer "does this change student behavior or support?" If the answer is "it's nice-to-have" or "it's a feature parity", it's dropped.

**Parallel work:** If you're the teammate shipping 3B in parallel, read [`CONTRIBUTING-P3.md`](CONTRIBUTING-P3.md) first. Your scope = Skill Map + Studio + Receipts + Admin + Infra + Meta + Career (39 tickets). My scope = all of 3A + remaining 3B areas. File ownership, claim protocol, migration numbering, and browser-verification protocol are all in that doc.

**Next migration number to reserve:** `0012` (current head: `0009_submission_sharing`; `0010_conversation_memory` (3A-2) + `0011_socratic_level` (3A-3) reserved — always verify with `ls backend/alembic/versions/ | sort | tail -1` before claiming, since Phase 3A is also adding migrations).

---

## Scope Summary

| Category | Count |
|---|---|
| KEEP (ship as-is) | 80 |
| NEW (added during critic pass) | 5 |
| FOLDED (merged into another ticket) | 18 |
| DROPPED (cosmetic / premature / wrong problem) | 45 |
| **Shippable tickets** | **85** |

---

## Execution Order

**Phase 3A — Student-behavior core (18 tickets, sequential, high-quality).**
Do these first. Each needs prompt iteration + edge case testing + live verification. No parallelism.

**Phase 3B — Platform depth (67 tickets, can parallelize later).**
Ship after 3A. Pure frontend polish, admin views, infra, receipts, map, studio polish, career — these are verifiable by rendering or running, not by behavior testing.

---

## PHASE 3A — Student-behavior core

Dependency gate: 3A-1 blocks 3A-2 through 3A-8.

### 3A-1: Student-state context injection (NEW)
- [x] DONE (3a74d62)
- **Why:** Every tutor call is currently mostly stateless per-session. Before prompt work, the tutor must see: active goal, skill mastery distribution, last 3 confusions, last reflection mood, preferred socratic level. This ticket is plumbing that makes everything downstream land.
- **Touches:** `backend/app/services/student_context_service.py` (new), `backend/app/api/v1/routes/stream.py` (inject into system prompt).
- **Edge cases:** new student (empty state), student with no goal yet, student with no reflections.
- **Acceptance:** system prompt shows the 6-line context block. Unit test for the pure builder.
- **Telemetry:** `tutor.context_injected { context_lines, missing_fields[] }`.

### 3A-2: Per-skill conversation memory (#51)
- [x] DONE (92f4f42)
- **Why:** Tutor forgets what you covered last time. Continuity = less wasted intro.
- **Touches:** new table `conversation_memory (user_id, skill_id, summary_text, last_updated)`, Alembic migration, `student_context_service` (load top 5 per session).
- **Edge cases:** no skill detected yet, first conversation ever.
- **Acceptance:** cross-session test — conversation 1 writes memory, conversation 2 sees it in context.
- **Telemetry:** `tutor.memory_loaded { skill_id, memory_age_hours }`.

### 3A-3: Socratic intensity slider (#68)
- [x] DONE (5c62a27)
- **Why:** Binary "strict socratic" toggle is too blunt. Level 0-3 lets students self-select push intensity per session.
- **Touches:** `user_preferences.socratic_level` column (migrate existing boolean: `true`→2, `false`→0), `components/features/socratic-slider.tsx` (replaces existing toggle), `stream.py` reads new column.
- **Acceptance:** existing users keep working via migration; new slider in preferences.
- **Telemetry:** `preference.socratic_level_changed { from, to }`.

### 3A-4: Intent clarification + follow-up suggestions (#54 + #69)
- [ ] not started
- **Why:** Tutor gives answers when student wanted practice. Biggest single lever in the roadmap.
- **Touches:** MOA classifier returns confidence; if <0.7, stream emits a "clarify" event first with 3 pill options (direct answer / hint / challenge). At end of every substantive reply, emit 3 follow-up pills based on context.
- **Edge cases:** clarification disabled at socratic level 0; pills shouldn't appear for short/trivial messages.
- **Component:** `components/features/chat-suggestion-pills.tsx` (shared by clarify + follow-up).
- **Acceptance:** manually test 5 ambiguous queries; each shows clarify pills.
- **Telemetry:** `tutor.clarification_shown`, `tutor.followup_clicked { pill_index }`.

### 3A-5: Intent-before-debug (NEW)
- [ ] not started
- **Why:** Students paste errors and expect a fix. Tutor must ask "what were you trying to do?" first. Teaches debugging, not dependency.
- **Touches:** prompt instruction in `agents/prompts/coding_assistant.md` and `moa.py` routing rule (error-paste detection). Optional: a pre-response detector in `stream.py` that intercepts if student message contains `Traceback` or `error:` and appends the ask.
- **Acceptance:** paste a Python traceback; tutor first response asks intent.
- **Telemetry:** `tutor.intent_before_debug_triggered`.

### 3A-6: Disagreement pushback + misconception log (#55 + #67)
- [ ] not started
- **Why:** A yes-machine tutor is worse than no tutor. Must say "actually, that's wrong, here's why."
- **Touches:** prompt addition across all tutor agents; new guardrail in `stream.py` that checks for agreement with known-wrong patterns from `misconceptions` table; logs disagreement to `misconceptions (user_id, topic, student_assertion, tutor_correction, created_at)`.
- **Edge cases:** must only pushback when student makes a factual claim (not questions, not uncertainty).
- **Acceptance:** test with 3 wrong assertions ("embeddings are just one-hot encodings", etc.); tutor disagrees politely with evidence.
- **Telemetry:** `tutor.disagreement_logged { topic }`.

### 3A-7: Confidence calibration (NEW)
- [ ] not started
- **Why:** Overconfidence is the #1 predictor of gaps. After concept questions, tutor asks "how confident 1-5?" Collected as self-knowledge signal.
- **Touches:** prompt addition (socratic tutor asks post-answer), new row in `user_skill_states.confidence_reports` or separate table `confidence_reports (user_id, skill_id, value, asked_at, answered_at)`.
- **Acceptance:** after 2-3 answers in a session, tutor asks confidence once.
- **Telemetry:** `tutor.confidence_reported { skill_id, value }`.

### 3A-8: "I don't know" honesty guardrail (NEW)
- [ ] not started
- **Why:** Hallucinated answers erode trust forever. When RAG/context has no strong match, tutor must say so.
- **Touches:** prompt instruction block ("If you're not confident, say 'I'm not sure; let me think out loud' and offer 2-3 hypotheses"). Optional post-response check: if response confidence score (from self-reflection prompt) is <0.5, prepend a hedge.
- **Acceptance:** ask tutor about a made-up library; it says it's unsure rather than hallucinating.
- **Telemetry:** `tutor.honesty_hedge_triggered`.

### 3A-9: Self-explanation before grade (#87 + #88)
- [ ] not started
- **Why:** Seeing pass/fail short-circuits metacognition. "Why does this work?" before grade forces thinking.
- **Touches:** exercise submit flow — on submit, intercept with modal asking "in one sentence, why does your approach work?" Store in `reflections` with `kind='self_explanation'`. Show grade after.
- **Trigger points:** also after lesson completion (optional prompt).
- **Acceptance:** submit an exercise; modal appears; after typing, grade shown.
- **Telemetry:** `exercise.self_explanation_submitted { exercise_id, length }`.

### 3A-10: Post-lesson retrieval quiz (#95)
- [ ] not started
- **Why:** Testing effect — students remember 2x more with immediate recall.
- **Touches:** `POST /students/me/lessons/{id}/complete` now returns 3 MCQs from `mcq_bank` filtered to the lesson's skill. Frontend shows inline quiz. Answers update `user_skill_states.confidence`.
- **Edge cases:** no MCQs in bank for that skill → skip gracefully with a reflection prompt instead.
- **Acceptance:** complete a lesson; 2-min quiz appears.
- **Telemetry:** `lesson.retrieval_quiz_shown`, `lesson.retrieval_quiz_graded { correct, total }`.

### 3A-11: Daily intention (#11)
- [ ] not started
- **Why:** 1-line "what do you want to do today" sets the session frame.
- **Touches:** table `daily_intentions (user_id, date, text)` unique on (user_id, date), route `POST /today/intention`, `today-intention.tsx` component on Today page.
- **Acceptance:** set intention; reload; it persists. Next day: fresh prompt.
- **Telemetry:** `today.intention_set`, `today.intention_length`.

### 3A-12: End-of-day reflection (#13)
- [ ] not started
- **Why:** Captures felt experience, not just metrics. Evening card: "how did today go? good / ok / rough" + optional note.
- **Touches:** extend `reflections` table with `kind='day_end'`, component `today-day-end.tsx`, shows only after 6pm local.
- **Acceptance:** after 6pm, card appears on Today; submit persists.
- **Telemetry:** `today.day_end_answered { mood }`.

### 3A-13: Morning/evening Today rotation (#14)
- [ ] not started
- **Why:** Morning = intention + next action. Evening = reflection + tomorrow preview. Same page, different emphasis by hour.
- **Touches:** Today page reads local hour; conditionally shows intention card (morning) or day-end card (evening).
- **Acceptance:** mock system clock; verify rotation at 6pm.
- **Telemetry:** `today.variant_shown { variant: "morning"|"evening" }`.

### 3A-14: Consistency surfacing, no points (#150 reframed)
- [ ] not started
- **Why:** Replace the current streak number with honest data: "You showed up 4 of 7 days last week." No points, no loss aversion.
- **Touches:** existing streak widget on Today replaced; pure count from `agent_actions` (any activity = show-up).
- **Acceptance:** widget renders; reads right.
- **Telemetry:** `today.consistency_shown { days_this_week }`.

### 3A-15: Stuck-for-10-min intervention (NEW)
- [ ] not started
- **Why:** Students stuck silently = worst failure mode. Proactive "want a hint?" without forcing interruption.
- **Touches:** Studio page tracks time since last code change. At 10 min with no submission, non-blocking banner: "Stuck? Ask the tutor what to try." Clicking opens a pre-filled tutor prompt with current code.
- **Acceptance:** simulate 10-min inactivity; banner appears; dismissal + "ask tutor" path both work.
- **Telemetry:** `studio.stuck_intervention_shown`, `studio.stuck_intervention_ignored | accepted`.

### 3A-16: Gap analysis on Receipts (#78)
- [ ] not started
- **Why:** Honest "you've avoided X for 3 weeks" card. Students need to see what they're not doing, not just what they are.
- **Touches:** `receipts` page; backend computes skills with last_touched >21 days and mastery <0.5. Returns top 3.
- **Acceptance:** with test data, card shows 3 skills with "last touched" dates.
- **Telemetry:** `receipts.gap_analysis_shown { gap_count }`.

### 3A-17: Micro-wins tied to disagreement log (#154 + depends on 3A-6)
- [ ] not started
- **Why:** "You unblocked X yesterday" — specific, verifiable, not a badge.
- **Touches:** Today page shows micro-wins from last 48h: misconceptions resolved (tutor disagreed, student acknowledged), lesson completions, exercise passes on hard problems.
- **Acceptance:** trigger a disagreement, resolve it, see the micro-win on Today.
- **Telemetry:** `today.micro_win_shown { kind }`.

### 3A-18: Admin student intervention notes (#146)
- [ ] not started
- **Why:** The admin support ticket. Admin sees struggling student → writes "saw him stuck on embeddings, reached out 3/14." Continuity of support.
- **Touches:** table `student_notes (admin_id, student_id, body_md, created_at)`, `POST /admin/students/{id}/notes`, side panel on `/admin/students/{id}`.
- **Acceptance:** admin writes a note; reloads; it's there.
- **Telemetry:** `admin.student_note_added`.

---

## PHASE 3B — Platform depth

Grouped by area. Within each area, tickets are independent and can be done in any order. Parallelism is safe here because these are verification-by-rendering.

### 3B — UI/UX polish (11 tickets)

- [ ] #111 Focus-visible rings everywhere
- [ ] #112 Skeleton ghost states (dashboard, receipts, at-risk only)
- [ ] #113 Inline error recovery (+ folds #129 consistent toast channel)
- [ ] #114 Optimistic UI defaults (scoped: reflection, intention, SRS, bookmark)
- [ ] #115 Undo toast for destructive actions (+ folds #123)
- [ ] #117 Consistent empty states
- [ ] #118 Consistent page headers (+ folds #121 section spacing)
- [ ] #120 Route-level loading bar
- [ ] #124 Smooth theme transitions
- [ ] #127 Link vs button semantic audit
- [ ] #128 Loading priority on above-fold images
- [ ] #130 Dark mode QA pass

### 3B — Mobile (5 tickets)

- [ ] #131 Mobile sidebar drawer polish (swipe gestures)
- [ ] #132 Bottom nav on mobile
- [ ] #134 Responsive tables (admin students, at-risk)
- [ ] #135 Tap targets ≥44px
- [ ] #136 Mobile keyboard handling (autogrow, scroll-into-view)

### 3B — Admin (3 tickets)

- [ ] #142 Audit log viewer (minimal)
- [ ] #148 Content performance (per-lesson confusion/question stats)
- [ ] Course+rubric editor (folds #144 + #145, JSON textarea form)

### 3B — Engagement (4 tickets)

- [ ] #151 Weekly cadence prompts (+ folds #153 email digest opt-in)
- [ ] #152 Inactivity re-engagement (wire existing disrupt_prevention to cron)
- [ ] #154 Micro-wins surface (now in 3A-17, skip here)

### 3B — Infrastructure (8 tickets)

- [x] #158 Structured logging audit DONE
- [x] #159 Request ID propagation DONE
- [x] #160 Deep health checks (/health/live, /health/ready) DONE
- [x] #162 DB pool tuning (config line) DONE
- [x] #163 Redis key namespacing DONE
- [~] #164 Backup runbook (docs/ops/backup-restore.md) (p3b, feat/p3b-infra)
- [ ] #165 Cost monitoring (token usage to agent_actions.metadata)
- [ ] #167 CI gates audit

### 3B — Meta (2 tickets)

- [ ] #177 Feedback widget (floating button, feedback table, admin triage)
- [ ] #180 Pulse dashboard (single page, 5 numbers)

### 3B — Tutor extras (already in 3A core list)

Covered in 3A. No additional 3B tutor tickets.

### 3B — Learning mechanics (6 tickets, beyond 3A)

- [ ] #85 Interleaving prompts
- [ ] #90 Desirable difficulty
- [ ] #91 Worked examples
- [ ] #92 Fading scaffolds (extends P2-01 scaffolding decay)
- [ ] #93 Testing effect / weekly review quiz (Celery cron)
- [ ] NEW Stuck-for-10-min → in 3A-15 already

### 3B — Onboarding (3 tickets)

- [ ] #4 Diagnostic opt-in CTA
- [ ] #5 Time-per-week commitment
- [ ] #7 First-day plan (3-day starter from goal + skill graph)

### 3B — Today (covered in 3A)

### 3B — Skill Map (6 tickets)

- [ ] #21 Cluster collapse
- [ ] #22 Mastery legend
- [ ] #24 Path saving
- [ ] #25 Skill side panel (+ folds #28 search)
- [ ] #26 Prereq warning
- [ ] #27 Progress rings on nodes

### 3B — Studio (9 tickets)

- [ ] #39 Diff view (Monaco DiffEditor)
- [ ] #40 Inline tutor pins (gutter icons)
- [ ] #41 Run history (last 20, localStorage)
- [ ] #42 Local persistence / autosave
- [ ] #43 Format on save (ruff via backend)
- [ ] #44 Lint as you type (Monaco markers)
- [ ] #45 Live preview for prompts
- [ ] #48 Snippet insertion (5-10 canonical)
- [ ] #50 Per-exercise tutor auto-context

### 3B — Receipts (7 tickets)

- [ ] #75 Week-on-week diff
- [ ] #76 Concept coverage miniature skill map
- [ ] #79 Portfolio items this week
- [ ] #81 Reflection aggregation
- [ ] #82 Time investment chart
- [ ] #83 Next-week suggestion
- [ ] #78 Gap analysis → in 3A-16 already

### 3B — Community (2 tickets)

- [ ] #101 Peer review exchange (assignment logic on existing peer-gallery)
- [ ] #102 Question wall (+ folds #103 upvote, #108 flag)

### 3B — Career (5 tickets)

- [ ] #168 Resume builder (+ folds #174 LinkedIn blurb)
- [ ] #169 Interview question bank (searchable)
- [ ] #171 JD → fit score
- [ ] #172 Skill gap vs JD
- [ ] #173 Learning plan for JD

---

## DROPPED tickets (with reason)

**UI:** #110 keyboard help overlay (nobody uses it), #116 density toggle (no demand), #119 palette on public routes (tech flex), #122 breadcrumbs (shallow app), #125 soft shadows audit (pure aesthetic), #126 type lint rule (maintenance cost), #129 → folded

**Mobile:** #133 pull-to-refresh (janky web impl), #137 offline banner (no real offline)

**Admin:** #143 bulk actions (premature), #147 cohort analytics (no cohorts)

**Engagement:** #155 OG image (social flex), #156 public profile (ditto), #157 leaderboard (kills struggling students)

**Infra:** #161 rate limit tiering (premature), #166 graceful shutdown (premature)

**Meta:** #178 A/B framework (N too small), #179 session replay (privacy surface, premature)

**Tutor:** #53 → folded to 3A-4, #56 length chip (cosmetic), #57 explain-like-I-know-X (low freq), #58 image input (infra heavy), #59 voice (different modality), #62 share convo (social), #63 regenerate (slot-machine pattern), #70 per-skill persona (voice inconsistency)

**Learning:** #94 concept map before content (attention tax), #96 generative question bank (moderation nightmare)

**Onboarding:** #3 goal contract coach (adds friction), #6 partner (folded to community)

**Today:** #12 pomodoro (commodity)

**Community:** #97-#100 groups (N too small), #104 helpfulness tokens (gamification), #105 sprints (premature), #106 group wall (no groups), #107 demo day (event ops)

**Career:** #170 scheduling (not the blocker), #175 public URL (PDFs suffice), #176 referrals (event ops)

---

## Migration number reservations (3B)

| Number | Area | Ticket | Purpose |
|---|---|---|---|
| 0010 | meta | #177 | feedback table |
| 0011 | career | #168/#169 | resumes + interview_questions tables |

Next available: 0012

---

## Cross-cutting new tables introduced in 3A/3B

| Table | Ticket | Added |
|---|---|---|
| `conversation_memory` | 3A-2 | new |
| `misconceptions` | 3A-6 | may already exist; verify |
| `confidence_reports` | 3A-7 | new |
| `daily_intentions` | 3A-11 | new |
| `student_notes` | 3A-18 | new |
| `feedback` | 3B #177 | new |

Existing tables that grow columns:
- `user_preferences.socratic_level` (int 0-3, replaces bool `strict_socratic_mode`) — 3A-3
- `user_skill_states.confidence` (already present per schema check) — 3A-10 writes into it
- `reflections.kind` (enum adds `day_end`, `self_explanation`) — 3A-9, 3A-12

---

## Resumable state protocol

Before starting a ticket, change `[ ]` → `[~] in progress (sha_at_start)` on that line.
After merging, change `[~]` → `[x] DONE (final_sha)`.

If a session ends mid-ticket, the next session reads this file and either continues the `[~]` row or aborts/reverts.

**Every ticket commit message format:**
`feat|fix|chore(area): {ticket-id} {short desc}` — e.g., `feat(tutor): 3A-4 intent clarification + follow-up pills`.

---

## Definition of Done (carried from root ROADMAP)

- Tests pass (pytest + vitest).
- Migration clean on empty + existing DB (where applicable).
- Telemetry events firing.
- Screenshot / transcript in commit message where UX-relevant.
- No regression in existing screens (smoke test).
- This file updated.
