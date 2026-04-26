# "Am I Ready?" Diagnostic Agent + JD Decoder — Implementation Notes (Phase 1 MVP)

**Date shipped:** 2026-04-25
**Specs:**
- [diagnostic-agent.md](diagnostic-agent.md)
- [jd-decoder-agent.md](jd-decoder-agent.md)
- [job-readiness-page-strategy.md](job-readiness-page-strategy.md)
**Companion:**
- [cost-log-refactor.IMPLEMENTATION_NOTES.md](cost-log-refactor.IMPLEMENTATION_NOTES.md)
- [mock-interview-agent.IMPLEMENTATION_NOTES.md](mock-interview-agent.IMPLEMENTATION_NOTES.md)
- [tailored-resume-agent.IMPLEMENTATION_NOTES.md](tailored-resume-agent.IMPLEMENTATION_NOTES.md)

---

## What was built

Phase 1 MVP of two paired agents that together anchor the Job Readiness
page:

* **"Am I Ready?" Diagnostic Agent** — conversational front door.
  Reads the student's verified platform data, asks 3–6 follow-up
  questions, returns a structured verdict (headline + evidence chips +
  single deep-linked next action). Cross-session memory references
  prior verdicts when relevant. Anti-sycophancy guardrails (warning-
  only for MVP; CI-blocking gated on calibration). Cost cap ₹15
  per session.

* **JD Decoder Agent** — paste-text JD analysis: real must-haves vs.
  wishlist, template filler explained, seniority signal, culture
  signals, per-student match score using the same verified-data
  snapshot. Standalone use AND inline-from-diagnostic when the
  student references a JD. Cost cap ₹8 per decode. Hash-keyed
  cache shared across users.

Both agents land behind feature flags
(`feature_readiness_diagnostic`, `feature_jd_decoder` /
`NEXT_PUBLIC_FEATURE_READINESS_DIAGNOSTIC`,
`NEXT_PUBLIC_FEATURE_JD_DECODER`) so rollout is explicit.

---

## File layout

### Backend (new)

```
backend/
├── alembic/versions/0040_agent_invocation_log.py   # cost-log refactor (commit 0)
├── alembic/versions/0041_readiness_diagnostic.py   # 6 readiness/JD tables
├── app/
│   ├── models/
│   │   ├── agent_invocation_log.py                 # unified per-LLM-call cost log
│   │   ├── migration_gate.py                       # durable parallel-read gate
│   │   ├── readiness.py                            # 4 readiness tables
│   │   └── jd_decoder.py                           # 2 JD tables
│   ├── schemas/
│   │   ├── readiness.py                            # diagnostic + north-star schemas
│   │   └── jd_decoder.py                           # decoder request/response
│   ├── agents/
│   │   ├── readiness_sub_agents.py                 # JDAnalyst, MatchScorer,
│   │   │                                            #   DiagnosticInterviewer,
│   │   │                                            #   VerdictGenerator
│   │   └── prompts/
│   │       ├── readiness_jd_analyst.md
│   │       ├── readiness_match_scorer.md
│   │       ├── readiness_interviewer.md
│   │       └── readiness_verdict.md
│   ├── services/
│   │   ├── agent_invocation_logger.py              # dual-write helper + parity gate
│   │   ├── student_snapshot_service.py             # StudentSnapshot (TTL 1h)
│   │   ├── readiness_evidence_validator.py         # generalized 2-pass validator
│   │   ├── readiness_orchestrator.py               # session lifecycle + finalize
│   │   ├── readiness_memory_service.py             # prior_session_hint + history
│   │   ├── readiness_action_router.py              # NextActionCatalog
│   │   ├── readiness_anti_sycophancy.py            # phrase + structural checks
│   │   ├── readiness_north_star.py                 # click beacon + completion
│   │   ├── jd_decoder_service.py                   # decoder orchestrator
│   │   └── jd_culture_signals.py                   # pattern library + LLM merge
│   └── api/v1/routes/
│       ├── readiness.py                            # /readiness/diagnostic/...
│       └── jd_decoder.py                           # /readiness/jd/...
└── tests/
    ├── test_models/test_readiness_models.py
    └── test_services/
        ├── test_agent_invocation_log_dual_write.py
        ├── test_student_snapshot.py
        ├── test_readiness_evidence_validator.py
        ├── test_readiness_orchestrator.py
        ├── test_readiness_memory.py
        ├── test_readiness_action_router.py
        ├── test_readiness_anti_sycophancy.py
        ├── test_readiness_north_star.py
        └── test_jd_decoder.py
```

### Frontend (new)

```
frontend/src/
├── lib/
│   ├── copy/readiness.ts                           # shared voice across both agents
│   └── hooks/use-readiness.ts                      # all hooks for both surfaces
└── components/features/
    ├── jd-decoder/
    │   ├── index.ts
    │   ├── analytics.ts
    │   ├── decoder-card.tsx
    │   ├── analysis-grid.tsx
    │   └── match-score-gauge.tsx
    └── readiness-diagnostic/
        ├── index.ts
        ├── analytics.ts
        ├── diagnostic-anchor.tsx                   # state machine + bundling
        ├── conversation.tsx
        ├── verdict-card.tsx
        ├── memory-banner.tsx
        └── past-diagnoses-drawer.tsx
```

`components/v8/screens/readiness-screen.tsx` was edited to flag-gate
`OverviewView` and `JdMatchView` swaps. Legacy demo bodies preserved
as `OverviewViewLegacy` / `JdMatchViewLegacy` so flag-off environments
don't go empty during rollout. Drop the legacy components in a follow-
up once the flags are on by default.

---

## Model choices, latency, cost

| Sub-agent | Tier | Model | Tokens (est) | Cost / call (est) | Latency target |
|---|---|---|---|---|---|
| `DiagnosticInterviewer` | fast | claude-haiku-4-5 | ~600 in / ~120 out | ≈ ₹0.50–0.80 | <1.5s/turn |
| `VerdictGenerator` | smart | claude-sonnet-4-6 | ~1500 in / ~400 out | ≈ ₹4–5 | 3–5s |
| `JDAnalyst` | smart | claude-sonnet-4-6 | ~1200 in / ~500 out | ≈ ₹4–5 | 4–6s |
| `MatchScorer` | smart | claude-sonnet-4-6 | ~1400 in / ~250 out | ≈ ₹3–4 | 3–5s |
| `parse_jd` (existing) | fast | claude-haiku-4-5 | already counted | ~₹0.10 | <2s |
| Evidence validator (LLM pass) | fast | claude-haiku-4-5 | ~800 in / ~80 out | ≈ ₹0.5 | <2s, optional |

**Per-session diagnostic total (estimated):**

* Interviewer × 4–6 turns: ₹2–5
* Verdict generator × 1: ₹4–5
* Validator (deterministic only for verdicts in MVP): ₹0
* **Typical: ₹6–10. Hard cap: ₹15.**

**Per-decode total (estimated):**

* parse_jd: ₹0.10
* JDAnalyst: ₹4–5
* MatchScorer: ₹3–4
* Validator (deterministic): ₹0
* **Typical: ₹7–9. Hard cap: ₹8.** Cache hits short-circuit to just
  MatchScorer (~₹3–4).

> **Latency and cost numbers above are estimates from token-budget math.
> Actual production p95s are not yet measured.** Per the live-LLM
> verification protocol below, observed values from the first 10–20
> production sessions go in this table during the first follow-up PR
> after launch.

---

## Latency-feel design

The conversational layer's user-perceived smoothness depends on
indicator framing as much as raw latency:

* **Per-turn wait (~1.5s):** calm italic `"Reading your work…"`
  indicator with three static dots. No spinner, no animated dots.
  Animation here would undermine the page's calm voice.
* **Verdict generation (3–5s):** larger Fraunces-italic
  `"Pulling the picture together…"` indicator. The wait should feel
  like *reading*, not stalling. Snapshot summary stays visible
  during the wait so the student sees what the agent is reading.
* **JD decode inline (5–8s):** decoder card has its own
  `"Reading the JD…"` button label during the call. No explicit
  thinking indicator — the loading button + disabled chat input
  conveys the state.

---

## Spec deviations and why

### 1. Voice not implemented in MVP
Per spec — diagnostic is short-form text. Mock interview's voice layer
(`use-voice-layer.ts`) exists and could be reused trivially, but adds
cost and latency without meaningful gain at this conversation length.
Phase 2 candidate if user feedback demands it.

### 2. Capstones modeled as `0` placeholder
No first-class `Capstone` model exists yet. `StudentSnapshot.capstones_shipped`
is `0` with a `TODO` comment. When capstones become first-class (own
table or Exercise tag), the integration point is a single function in
`student_snapshot_service._count_capstones`. The diagnostic verdict
prompt is allowlist-aware so a real count surfaces automatically once
the model lands.

### 3. Peer reviews — counts only, never quoted
Per the data-shape Q2 default. Snapshot exposes `peer_review_count` +
`peer_review_avg_rating`; comment text is never serialized. Test
`test_peer_review_counts_only_no_quotes` enforces. Privacy + sentiment-
misreading risk drove the decision; the value of quoting is low (counts
already convey "people are engaging with your work").

### 4. Time-on-task is heuristic, not instrumented
`time_on_task_minutes = (watch_time_seconds // 60) + exercises × 8min`.
No IDE-time signal. Spec Q3 default. If the verdict generator wants
finer signal in Phase 2, a separate IDE-time pipeline would be needed.

### 5. Anti-sycophancy gate is warning-only, not CI-blocking
Per locked decision in commit 0. Flags persist on
`ReadinessVerdict.sycophancy_flags`; verdicts ship regardless. Promotion
criteria below.

### 6. Validator runs deterministic-only on verdicts
The two-pass validator (deterministic + LLM verifier) ships with the JD
decoder's match-score path but the verdict generator skips the LLM pass
for cost. The deterministic allowlist check catches the structural
failure; the LLM pass is reserved for prose-level fact checks that the
diagnostic's evidence-chip structure already constrains.

### 7. Frontend has no component-level unit tests
The existing `mock-interview/` and `tailored-resume/` features have no
component tests either. CLAUDE.md aspires to "ALL components must have
Storybook stories"; that aspiration is not enforced anywhere on this
page in practice. **We followed the project's actual convention rather
than the documented one.** Component tests for the diagnostic flow
(idle → conversation → verdict, JD-decoder embedding, click beacon
firing on CTA) belong in a Phase 2 testing pass — flagged below.

### 8. No streaming for interviewer turn responses
The hook fetches the full response in one round-trip. Adding SSE
streaming for ~1.5s of latency adds infrastructure for marginal feel
improvement. Phase 2 candidate; trigger: latency budget exceeds 1.5s
under real load.

### 9. Apply-flow telemetry doesn't exist yet
The `ready_but_stalling` and `ready_to_apply` intents fall back to
"tailored resume OR mock session" as completion proxies. A direct
apply-flow signal (Application Tracker, recruiter-outreach event, etc.)
would be a more honest measurement. Phase 2 candidate.

---

## Open questions

* **Auto-trigger after major events?** Spec asks whether the
  diagnostic should auto-trigger after a capstone ships or a streak
  breaks. MVP is pull-based. Auto-trigger would change the cost
  profile (more sessions / less consent) — defer to data after
  launch.
* **Verdict shareability.** Whether verdicts should be sharable with
  mentors / peers. Privacy implications; not implemented in MVP.
* **Memory opt-in.** Spec asks whether memory references should be
  opt-in. MVP defaults to on. Watch first 50 sessions for student
  reaction.
* **Conflicting input vs. data.** How to handle "I'm ready" student
  input against "no, you're not" snapshot data. Current verdict
  prompt has rule 4 ("surface gaps explicitly when present") which
  resolves it: data wins, conversation softens delivery. Watch live
  sessions for whether this lands warmly enough.

---

## Phase 2 candidates (with promotion triggers)

| Item | Trigger to revisit |
|---|---|
| Voice for diagnostic | User feedback demands it |
| SSE streaming for interviewer turns | Real-load p95 turn latency >1.5s |
| LLM-pass validator on verdicts | Anti-sycophancy false-negative rate ≥10% |
| Backend cron for completion check | Lazy page-load path leaves >20% of clicks uncounted |
| URL-based JD fetching | Paste-text usage saturates and growth flattens |
| Capstones as first-class model | Curriculum team ships the design |
| Apply-flow telemetry | First cohort hits offer stage; need real signal |
| First-class component tests | Test debt is felt during a refactor |
| Vector-store memory | Memory hit rate <30% on returning students |
| Anti-sycophancy LLM judge | Phrase-blacklist FN rate ≥10% |

---

## Tracking issues

### Anti-sycophancy CI gate promotion to blocking
**Currently:** warning + log + persisted flags on every verdict.
**Promotion criteria:** false-positive rate **<5%** on a held-out set
of 20 verdicts manually labeled as "honest." Calibrate against the
first ~50 real verdicts before flipping.
**Owner:** TBD.
**Open issue:** create when the diagnostic ships and verdicts start
landing.

### Resume-agent `cap_exceeded` → `failed` asymmetry
Documented in [cost-log-refactor.IMPLEMENTATION_NOTES.md](cost-log-refactor.IMPLEMENTATION_NOTES.md).
The diagnostic + JD decoder both correctly emit `STATUS_CAP_EXCEEDED`
when their circuit breakers fire. Resume agent still emits
`STATUS_FAILED` on cap (preserving legacy semantics). Resolve during
the post-flip cleanup migration.

### Cost-log dual-write sunset
**Target:** 2026-05-09 (calendar aspiration).
**Actual flip condition:** `migration_gates.flipped = true` for
`agent_invocation_log_quota_parity`. Documented in detail in the
companion notes.

### `_ensure_aware` SQLite-vs-Postgres datetime helper
Same coercion is now duplicated across `student_snapshot_service.py`,
`mock_memory_service.py`, and `readiness_north_star.py`. Worth pulling
to a shared util in `app/core/datetime_utils.py` next time someone is
in the area. Not a regression in either correctness or lint —
opportunistic refactor.

---

## Live LLM verification protocol

Static analysis cannot verify prompt behavior. Run **5–10 real
diagnostic sessions** in staging before public launch, varying:

* **Snapshot data:** thin (≤2 lessons, 0 exercises, 0 mocks),
  medium (~10 lessons, 5 exercises, 1–2 mocks), strong (20+ lessons,
  capstones, multiple mocks)
* **Prior sessions:** with and without (memory surfacing exercise)
* **JD references:** at least 2 sessions where the student mentions a
  JD mid-conversation (decoder bundling exercise)

**Watch list — the three failure modes most likely to slip through
prompt review:**

1. **Anti-sycophancy phrases sneaking through that aren't in the
   blacklist.** The phrase blacklist is 25-ish entries; LLMs drift
   to close substitutes. If the first 10 sessions surface a new
   sycophantic family ("you're crushing it!" → "you're absolutely
   crushing it!"), add the family to `_FORBIDDEN_PHRASES` in
   `readiness_anti_sycophancy.py`.
2. **6-turn cap not firing reliably.** The interviewer prompt has
   the cap rule (§5) AND the orchestrator hard-forces it. Check
   that real sessions hit `ready_for_verdict=true` by turn 6 from
   the agent's own decision, not just from the orchestrator's
   override. If the override fires more than 50% of the time, the
   prompt isn't internalizing the cap — tighten rule 5.
3. **`evidence_id` citation on first attempt.** The verdict
   generator's prompt is explicit about the allowlist. Watch the
   `validation_failed_retrying` log line — if retry-rate is >25%
   on real verdicts, the prompt's allowlist instruction needs a
   stronger position (move to the SYSTEM block top, not the
   user-prompt context).

If any of these three sneak through, the prompts get tightened
**before public launch**, not after.

---

## Test surface (commit-by-commit summary)

| Commit | Tests added | Pass count |
|---|---|---|
| 0 — cost log refactor | 9 | dual-write + parity gate |
| 1 — data models | 4 | model smoke (FK cycle, hash unique, null score) |
| 2 — StudentSnapshot | 7 | TTL caching, peer-quote guard, gap-only memory |
| 3 — Evidence validator | 6 | allowlist, case-insensitive, malformed input |
| 4 — JD decoder | 6 | cache, culture pre-pass, thin-data, retry |
| 6 — diagnostic orchestrator + memory | 15 | turn cap, cost cap, JD trigger, memory mix |
| 7 — verdict + router + anti-syc | 28 | finalize flow, sycophancy, intent routing |
| 10 — north-star | 16 | click idempotency, per-intent criteria, rate math |
| (Courtesy fix — mock memory datetime) | re-pass | 19 |

**Total backend tests covering this work: 102 passing. Ruff and mypy
clean on all new code.** (One pre-existing mypy error in
`career_service.py:612` unrelated to this build, flagged separately —
see "Pre-existing issues observed during build" below.)

**Frontend lint + tsc clean across the entire project** — no new
errors anywhere.

---

## Pre-existing issues observed during build

These were caught during the test run for commit 5+ but are unrelated
to the diagnostic / JD decoder work and were not fixed as part of it.
Logged here so they don't get lost.

### `career_service.py:612` — mypy `Result.rowcount` access error
```
app/services/career_service.py:612: error: "Result[Any]" has no
attribute "rowcount"  [attr-defined]
```
Pre-existing. Trivial fix (cast or `# type: ignore[attr-defined]`).
Not in scope for this work.

### `test_billing_support_fallback_refund` — real LLM call in tests
Test makes a live call to `api.minimax.io` and asserts on the
response shape. Symptoms match the `feedback_llm_response_parsing.md`
memory: the LLM returned a list-of-dict content with a `thinking`
block instead of plain text. This kind of test burns money silently
and produces flaky CI. Worth a real ticket for someone to mock the
LLM call at the service boundary; not in scope for this work.

### `mock_memory_service._prune_stale` — SQLite naive-datetime bug
**Already fixed** as a courtesy commit (`fix(mock-interview): SQLite
naive-datetime in _prune_stale`). Same shape as the bug I hit in
`student_snapshot_service._resume_freshness`. The fix mirrors the
pattern from `readiness_north_star._ensure_aware`. Should be the
trigger for the shared-util refactor noted above.

---

## What's not yet measurable

Even with the north-star instrumentation in place, the following are
unmeasured at launch:

* **Does the diagnostic feel like a coach or a chatbot?** No
  quantitative signal. Plan: weekly sample review of 50 sessions
  scored 1–5 on (honesty calibration, evidence accuracy, tone fit).
  Manual; track median.
* **Does memory feel supportive or surveillance-like?** Same — manual
  review, watch for student opt-out signal.
* **Cost-cap fire rate per agent.** Once the resume-agent
  `cap_exceeded` asymmetry is resolved, a single SQL query will
  surface this; until then the resume agent's cap fires are mixed
  in with generic failures.

---

## Sign-off

Phase 1 MVP is feature-complete behind two backend flags
(`feature_readiness_diagnostic`, `feature_jd_decoder`) and two frontend
flags (`NEXT_PUBLIC_FEATURE_READINESS_DIAGNOSTIC`,
`NEXT_PUBLIC_FEATURE_JD_DECODER`). End-to-end flow verified via the
102 backend tests. Live-LLM verification + the watch list above are
the launch gates remaining.
