# Placement Quiz — operations guide

The placement quiz at `/placement-quiz` recommends a paid course track using
Alex Hormozi's Value Equation framework. This doc covers everything ops needs
to keep it running without touching component code.

---

## File map

```
frontend/src/app/(public)/placement-quiz/
├── page.tsx                         # Server wrapper — page metadata only
├── _quiz.tsx                        # State machine — DO NOT edit unless adding stages
├── _quiz-questions.ts               # ⚠ LOCKED COPY — every word a user reads in the quiz body
├── _quiz-config.ts                  # ✏ EDIT HERE — track meta, prices anchor, copy templates
├── _quiz-scoring.ts                 # Pure scoring functions — DO NOT edit without re-running tests
├── _analytics.ts                    # PostHog event names
├── __tests__/quiz-scoring.test.ts   # 32 tests gating scoring changes
└── _components/                     # UI primitives — do not edit copy here, edit _quiz-config.ts
```

---

## Common ops tasks

### Update a track's price

Don't edit this file. Prices come from the live `courses` table.

```sql
-- Set Data Analyst price to $99
UPDATE courses SET price_cents = 9900 WHERE slug = 'data-analyst';
```

The quiz reads price live via `useCourses()`. Cache TTL is short — change
appears within a minute on next page load.

### Update a track's marketing copy (tagline, "what's included" list, value-stack anchor)

Edit [`_quiz-config.ts`](../frontend/src/app/(public)/placement-quiz/_quiz-config.ts).
Each track has a `TrackMeta` block with `tagline`, `effortLine`, `included`,
`anchor`, `perDayLine`. No code changes needed. No tests need to re-run.

### Update result-screen prose templates (intro line, guarantee body, timestamp close)

Edit the `COPY` object at the bottom of [`_quiz-config.ts`](../frontend/src/app/(public)/placement-quiz/_quiz-config.ts).
Functions like `COPY.result.guarantee.body(dreamPhrase)` interpolate the
user's dream paraphrase — keep the function signature even if you rewrite the body.

### Enable the cohort urgency block (Block H)

When the backend exposes a real cohort schema, edit `COHORT` in
[`_quiz-config.ts`](../frontend/src/app/(public)/placement-quiz/_quiz-config.ts):

```ts
export const COHORT = {
  enabled: true,
  startsAt: "May 12",
  seatsLeft: 14,
} as const;
```

Block H renders automatically. Do NOT enable it with fake dates — the spec
explicitly says fake scarcity destroys trust faster than no scarcity.

### Update quiz question copy

Edit [`_quiz-questions.ts`](../frontend/src/app/(public)/placement-quiz/_quiz-questions.ts).

⚠ **Run tests after any edit:**
```bash
cd frontend && pnpm exec vitest run "src/app/(public)/placement-quiz"
```

If the test suite fails, you renamed a question id or option id and the
scoring logic can't find it. Either revert the rename or update
`_quiz-scoring.ts` to match.

---

## ⚠ UNVERIFIED STATS — must verify before paid traffic

The quiz currently displays stats sourced from the catalog page tooltips,
which were drafted with the v8 HTML mockup and **never verified against
real student outcome data**. Each stat carries a `verified: false` flag in
`_quiz-config.ts`. In dev/staging, the UI shows a yellow `[PLACEHOLDER]`
badge next to every unverified stat. The badge is hidden in production
builds (`NODE_ENV === "production"`) so do **not** rely on it as your
ship-block — use this checklist instead.

### Verification checklist

Before a paid marketing campaign drives traffic to `/placement-quiz`:

| Surface | File | Field | Status |
|---|---|---|---|
| Quiz Pillar 1 — `cohortSize` (Data Analyst) | `_quiz-config.ts` | `TRACKS.analyst.cohortSize` | ❌ Placeholder (312) |
| Quiz Pillar 1 — `successRate` (Data Analyst) | `_quiz-config.ts` | `TRACKS.analyst.successRate` | ❌ Placeholder (71%) |
| Quiz Pillar 1 — `averageOutcome` (Data Analyst) | `_quiz-config.ts` | `TRACKS.analyst.averageOutcome` | ❌ Placeholder ($78k) |
| Quiz Pillar 1 — `cohortSize` (Data Scientist) | `_quiz-config.ts` | `TRACKS.scientist.cohortSize` | ❌ Placeholder (186) |
| Quiz Pillar 1 — `successRate` (Data Scientist) | `_quiz-config.ts` | `TRACKS.scientist.successRate` | ❌ Placeholder (64%) |
| Quiz Pillar 1 — `averageOutcome` (Data Scientist) | `_quiz-config.ts` | `TRACKS.scientist.averageOutcome` | ❌ Placeholder ($112k) |
| Quiz Pillar 1 — `cohortSize` (ML Engineer) | `_quiz-config.ts` | `TRACKS.ml.cohortSize` | ❌ Placeholder (142) |
| Quiz Pillar 1 — `successRate` (ML Engineer) | `_quiz-config.ts` | `TRACKS.ml.successRate` | ❌ Placeholder (68%) |
| Quiz Pillar 1 — `averageOutcome` (ML Engineer) | `_quiz-config.ts` | `TRACKS.ml.averageOutcome` | ❌ Placeholder ($145k) |
| Quiz Pillar 1 — `cohortSize` (GenAI Engineer) | `_quiz-config.ts` | `TRACKS.genai.cohortSize` | ❌ Placeholder (94) |
| Quiz Pillar 1 — `successRate` (GenAI Engineer) | `_quiz-config.ts` | `TRACKS.genai.successRate` | ❌ Placeholder (73%) |
| Quiz Pillar 1 — `averageOutcome` (GenAI Engineer) | `_quiz-config.ts` | `TRACKS.genai.averageOutcome` | ❌ Placeholder ($180k+) |
| **Catalog tooltip — Median entry salary (Data Analyst $78k)** | `catalog-screen.tsx:164` | salary stat | ❌ **Also unverified — replace alongside quiz stats** |
| **Catalog tooltip — Open roles (Data Analyst 12,400)** | `catalog-screen.tsx:165` | role count | ❌ **Also unverified** |
| **Catalog tooltip — Placement rate (Data Analyst 76%)** | `catalog-screen.tsx:167` | placement % | ❌ **Also unverified** |
| **Catalog tooltip — Median salary (Data Scientist $112k)** | `catalog-screen.tsx:215` | salary stat | ❌ **Also unverified** |
| **Catalog tooltip — Median salary (ML Engineer $145k)** | `catalog-screen.tsx:266` | salary stat | ❌ **Also unverified** |
| **Catalog tooltip — Median salary (GenAI Engineer $180k+)** | `catalog-screen.tsx:317` | salary stat | ❌ **Also unverified** |
| **Catalog tooltip — Placement rate / completion (multiple)** | `catalog-screen.tsx:150,203` | percentages | ❌ **Also unverified** |

> **Catalog stats are NOT badged.** The placeholder-badge UI applies only to
> the quiz this round (per scope decision in conversation). Catalog cleanup
> is a separate task. Both surfaces must be verified before paid traffic
> hits the funnel — flagged here so ops doesn't ship one and forget the
> other.

### How to mark a stat as verified

```ts
// In _quiz-config.ts:
cohortSize: {
  value: 412,            // ← replace with real number
  verified: true,        // ← flip to true after ops sign-off
  note: "Verified 2026-05-01 against student-outcomes dashboard.",
},
```

The badge disappears in dev. Production was never showing it anyway.

---

## Scoring algorithm

| Q | Lever | Drives |
|---|---|---|
| Q1 (Pain Now) | Skill level (`beginner` / `some-basics` / `working-dev` / `mid-level`) | Confidence calculation |
| Q2 (Pain Future) | Commitment intensity (1–4) | Result-screen tone (intensity ≥ 3 emphasizes the closing line) |
| Q3 (Dream) | **Track recommendation — deterministic** | The track shown |
| Q4 (Not Your Fault) | Failure narrative (verbatim quoted) | Pillar 2 body — "Why this time is different" |
| Q5 (Speed) | Urgency mode (`decided` / `activating`) | CTA copy ("Enroll in X" vs. "Start X today") |

**Confidence range = 88–96 inclusive.** Honest narrowing: a quiz that
recommends a track shouldn't say "you're a 12% match" for that track. Within
the 88–96 band the percent is deterministic — same answers always produce the
same number, with a small per-track jitter so two tracks with identical raw
alignment don't print the same percentage.

---

## Analytics events

Wire these to whatever provider (`window.posthog` is auto-detected — works
with the existing diagnostic/jd-decoder/mock-interview analytics setup).

| Event | When | Properties |
|---|---|---|
| `quiz_started` | Begin button click on intro screen | — |
| `quiz_question_answered` | Each option pick | `question_id`, `answer_id`, `step` |
| `quiz_completed` | After loading screen, before result render | `track_slug`, `answers` (comma-joined), `purchase_mode` |
| `quiz_cta_clicked` | Primary "Enroll in X" / "Start X today" button | `cta_label`, `recommended_track` |
| `quiz_curriculum_clicked` | Secondary "See full curriculum first" link | `recommended_track` |

In dev (`NODE_ENV !== "production"`) events also log to `console.debug`
prefixed `[placement-quiz]`. PostHog takes priority when present.

---

## Architecture decisions worth knowing

- **The 2-second loading hold between Q5 and result is intentional.** Reducing
  it to instant breaks the perceived-value mechanic. Reduced-motion users
  get 400ms (not zero) — see `COPY.loading.holdMsReducedMotion`.
- **Q3 is the single deterministic track signal.** Q1 is *not* a tiebreaker
  in this design. Q3's 4 options map 1:1 to the 4 paid tracks; no ambiguity
  is possible.
- **Python Developer (free track) is excluded from quiz outputs.** A user
  who picks "Stuck. Never coded." (Q1 option 1) will still be recommended
  Data Analyst. Reasoning: recommending the free track to someone who just
  felt the pain of Q2 short-circuits the sales arc. Free-track exploration
  remains available on `/catalog`.
- **Cohort vs self-paced.** Both currently route through the same Stripe
  checkout. Cohort start dates aren't real yet — Block H is gated behind
  `COHORT.enabled = false`.
- **Echo card Q1 paraphrase example mismatch.** The spec example was for Q1
  option 3 ("restless in a role going nowhere"). All 4 paraphrases live in
  `_quiz-questions.ts` and were reviewed in conversation.
