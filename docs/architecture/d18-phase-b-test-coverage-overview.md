# D18 Phase B — test coverage overview

**Status:** Phase B sealed at CP5 close (2026-05-09). Canonical
reference for the journey-test surface authored against Phase A
infrastructure. Future test-arc authors read this first.

Cross-reference: `d18-phase-a-test-infrastructure-overview.md` is
the infrastructure-side companion. Phase A built the substrate;
Phase B consumed it.

---

## Executive summary

Phase B authored **58 journey tests across 16 files** through
5 risk-tier checkpoints (CP1 critical-path → CP4 error states +
adversarial → CP5 closure). All run under the runner-overlay
topology established in Phase A retrofit-1.

**Final state:** 54 passing + 4 xfailed (1 product bug + 3 ops-deferred
stripe-env-gated). Cumulative cost ~₹39-43 of ~₹50 envelope. **Zero
security-relevant findings.** Four real bugs surfaced, classified,
either fixed in-flight (3) or registered as launch-readiness items (1).

Phase B's most important institutional finding: **bug-surfacing
value is front-loaded.** CP1 critical-path testing through real
infrastructure caught 3 infrastructure-layer bugs at integration
cost; CP2 edges + CP3 traceability ran clean against fixed
infrastructure; CP4 surfaced 1 distinct behavioral-layer bug none
of the prior CPs would have reached. Distribute test-authoring
investment along this bug-class distribution rather than
uniformly.

---

## Per-CP breakdown

### CP1 — Critical-path happy paths (commits 41ccf29 + aec3de6 + a04ccf3 + 6d2afef)

  * **Tests authored:** 24 across 9 journey files (a/b/c/d/e/f/g/h+j/i)
  * **Result:** 21 passing + 3 xfailed (stripe-env-gated)
  * **Cost:** ~₹6 authoring + ~₹8 remediation = ~₹14
  * **Bugs caught:**
    - **BUG-CP1D** — `interview_sessions.updated_at` schema/ORM drift.
      Live schema has `NOT NULL DEFAULT now()`; ORM declared
      `nullable=True` without `server_default`; SQLAlchemy INSERTed
      explicit NULL → Postgres rejected → 500 on every mock
      interview start. **Fixed** at commit `a04ccf3`. LAUNCH-BLOCKER
      candidate (production schema-dependent).
    - **BUG-CP1F** — 5 LLM call sites across 4 v2/agentic agents
      missed the `_track_llm_usage(ctx, response)` convention. Cost
      tracking silently zero on `/agentic/default/chat` path.
      **Fixed** at commit `6d2afef`. Pattern 27 (consumer convention
      drift), not infrastructure.
    - **BUG-CP1E** — empty response from `/agentic/default/chat`
      under batch. **Auto-resolved** by BUG-CP1F fix; was a
      downstream symptom of the same orchestration cost-tracking
      gap.
  * **Phase A infrastructure used:** PracticePage (retrofit-2);
    `seed_minimal_lesson_chain`/`seed_minimal_capstone_bundle` from
    retrofit-3 content_seeders; `register_via_http` /
    `seed_student_via_db` / `cleanup_student_via_db` from retrofit-3
    bridge.

### CP2 — High-value edge cases on critical paths (commit cd472e7)

  * **Tests authored:** 15 across 3 journey files
  * **Result:** 15/15 passing
  * **Cost:** ~₹9 authoring + ~₹3 batch re-runs = ~₹12
  * **Bugs caught:** ZERO new product bugs. One Pattern 22
    authoring-time correction (capstone empty-code: assumed accept,
    schema enforces 422; corrected before final assertion).
  * **Phase A infrastructure used:** 0 of 3 CP2-CP4 budget.
  * **Bug-taxonomy validation:** infrastructure-layer fixes from CP1
    don't shadow into edge cases — clean run validates the
    front-loaded discipline.

### CP3 — Traceability tests (commit 09274de)

  * **Tests authored:** 7 across 2 journey files
  * **Result:** 7/7 passing
  * **Cost:** ~₹6-8 authoring + ~₹3 batch re-runs = ~₹9-11
  * **Bugs caught:** ZERO new product bugs. Two Pattern 22
    authoring-time corrections (admin DM `triggered_by` taxonomy;
    mock interview audit pipeline writes to `mock_cost_log` +
    `agent_invocation_log`, not `agent_actions`).
  * **Phase A infrastructure used:** 0 of 3 budget.
  * **Operational finding:** batch-flakiness under real-LLM load
    (~1-3 transient-flake per full-suite run; isolation re-run
    deterministic). Documented; LOW severity.

### CP4 — Error states + adversarial input (commit cbcddde)

  * **Tests authored:** 12 across 2 journey files
  * **Result:** 11 passing + 1 xfail (BUG-CP4-LESSON-FK-500)
  * **Cost:** ~₹4-6 authoring (Cat B prompt-injection ~₹3-4 + Cat C
    long-input ~₹1-2)
  * **Bugs caught:**
    - **BUG-CP4-LESSON-FK-500** — `POST /me/lessons/{nonexistent}/complete`
      raises FK violation → unhandled `IntegrityError` → 500.
      Expected 404. MEDIUM severity (user-visible 5xx on stale URLs;
      not data-corrupting, not security). xfail-strict; fix scope
      preliminary in `docs/followups/bug-cp4-lesson-fk-500.md`.
    - **Side observation:** pre-existing `auth.signup_grace_failed`
      visible in backend logs (`:meta::jsonb` SQL syntax error;
      every signup since regression landed silently fails the
      free-tier-grant write). Registered separately at
      `docs/followups/auth-signup-grace-jsonb-cast-syntax.md`.
  * **Security findings:** ZERO. Direct + indirect prompt injection
    both handled gracefully; authorization contracts (student→admin,
    invalid JWT) all hold.
  * **Phase A infrastructure used:** 0 of 3 budget.
  * **Bug-taxonomy validation:** CP4 surfaced exactly the predicted
    behavioral-layer bug none of CP1-CP3 would have reached.

### CP5 — Closure (this commit)

  * Documentation + decision; ~₹0 cost.
  * Deliverables: this overview, pattern catalog hardening, CI cost
    shape resolution, Phase C readiness assessment.

---

## Bug log (final, classified)

| ID | Severity | Status | Resolution |
|---|---|---|---|
| BUG-CP1D | LAUNCH-BLOCKER candidate | ✅ CLOSED | `server_default=sa.func.now()` on ORM column (commit a04ccf3) |
| BUG-CP1F | MEDIUM (cost-tracking gap) | ✅ CLOSED | `_track_llm_usage` added to 4 agents (commit 6d2afef) |
| BUG-CP1E | LOW-MEDIUM (downstream symptom) | ✅ CLOSED | Auto-resolved by BUG-CP1F fix |
| BUG-CP4-LESSON-FK-500 | MEDIUM (5xx on stale URL) | ⏸ DEFERRED | xfail-strict; fix scope in follow-up doc |
| auth-signup-grace-jsonb | PENDING (investigation) | ⏸ DEFERRED | Side-finding; backend team owns; before launch |
| 3× Stripe webhook xfails | PENDING (env config) | ⏸ DEFERRED | Ops-side; if `STRIPE_WEBHOOK_SECRET` lands in runner overlay, un-xfail |

**Triage horizon for launch:**
  * Must fix before launch: BUG-CP4-LESSON-FK-500 (small fix; 1 hour),
    auth-signup-grace-jsonb (investigation + fix; 2-4 hours).
  * Nice to fix before launch: 3× stripe-env-gated tests (ops-side
    work + un-xfail; ~30 min once env is configured).
  * No further pre-launch work needed: BUG-CP1D, BUG-CP1F, BUG-CP1E
    (all closed).

---

## Test catalog (by journey + category)

### By journey letter (per saved Phase B prompt)

| Journey | CP1 | CP2 | CP3 | CP4 | Total |
|---|---:|---:|---:|---:|---:|
| (a) signup | 3 | 2 | 1 | — | 6 |
| (b) lesson nav + completion | 3 | 2 | 1 | — | 6 |
| (c) capstone submission | 1 | 2 | 1 | — | 4 |
| (d) mock interview | 1 | 1 | 1 | — | 3 |
| (e) career coach | 1 | 2 | 1 | — | 4 |
| (f) resume_reviewer | 2 | — | — | — | 2 |
| (g) gate evaluation | 3 | 2 | — | — | 5 |
| (h+j) admin | 6 | 3 | 2 | — | 11 |
| (i) payment (Stripe) | 4 | — | — | — | 4 |
| Adversarial input | — | — | — | 6 | 6 |
| Error modes | — | — | — | 6 | 6 |
| **CP totals** | **24** | **15** | **7** | **12** | **58** |

### By marker (CI execution tier)

  * `@pytest.mark.critical_path`: 24 tests (CP1) — runs every PR
    under the proposed CI shape β.
  * `@pytest.mark.edge_case`: 15 tests (CP2) — runs on labeled PRs
    or main per shape β.
  * `@pytest.mark.traceability`: 7 tests (CP3) — runs on main +
    nightly per shape β.
  * `@pytest.mark.error_state`: 12 tests (CP4) — runs on main +
    nightly per shape β.
  * `@pytest.mark.real_llm`: subset across all CPs (~10-12 tests)
    that incur real LLM cost.
  * `@pytest.mark.cost("low" | "medium" | "high")`: cost-budget
    tracker reads.

### Files

```
backend/tests/playwright/journeys/
├── _journey_helpers.py              # shared HTTP helpers
├── test_cp1_journey_a_signup.py
├── test_cp1_journey_b_lesson.py
├── test_cp1_journey_c_capstone.py
├── test_cp1_journey_d_mock_interview.py
├── test_cp1_journey_e_career_coach.py
├── test_cp1_journey_f_resume_reviewer.py
├── test_cp1_journey_g_gate.py
├── test_cp1_journey_i_payment.py
├── test_cp1_journey_jh_admin.py
├── test_cp2_edges_signup_admin.py
├── test_cp2_edges_lesson_capstone_gate.py
├── test_cp2_edges_agentic.py
├── test_cp3_traceability_backend.py
├── test_cp3_traceability_agentic.py
├── test_cp4_adversarial_input.py
└── test_cp4_error_modes.py
```

---

## Phase A infrastructure consumption (final)

Phase B used Phase A infrastructure as designed; **0 of 3 CP2-CP4
extension budget consumed.** Two retrofits authored *before* CP1
proved sufficient for all 58 journey tests:

  * **Retrofit-2 (PracticePage)** — required for journey (c)
    capstone path; used in CP1 + CP2.
  * **Retrofit-3A (content_seeders)** — `seed_minimal_lesson_chain`
    + `seed_minimal_capstone_bundle` consumed across CP1 + CP2 + CP3
    in 7 tests. Per-test inline seeding pattern preserved the
    template's "empty by default" property.
  * **Retrofit-3B (sync_async_bridge)** — `register_via_http`,
    `fetch_token_via_http`, `seed_student_via_db`,
    `mutate_student_state_via_db`, `cleanup_student_via_db`
    consumed in EVERY journey file. Without this module, each
    journey file would have inlined ~50-80 lines of bridging
    code; with it, each file is ~100-200 LoC focused on the
    journey's actual assertions.

**Validates Pattern 34** (pre-flight infrastructure investment
compounds non-linearly with consumption). One-time ~150 LoC retrofit
investment vs ~300-900 LoC of inlined bridging across 58 tests.

---

## CI execution model (post-CP5)

See `.github/workflows/playwright-tests.yml` for the wired CI
configuration. Phase B markers gate which jobs run which tests:

  * **playwright-db-only job** (every PR): CP2/CP4/CP5 smoke +
    BUG-CP1D regression + content_seeders smoke + bridge smoke.
    No browser; no LLM; ~5s wall.
  * **playwright-browser-critical job** (every PR per shape β):
    `@pytest.mark.critical_path` only. ~3-5 minutes wall;
    ~₹15-20 cost (real LLM tests on (e)/(d)/(f)/(c)).
  * **playwright-browser-full job** (main + nightly):
    full Phase B journey suite. ~20-30 minutes wall; ~₹40-50 cost.
  * **Cost cap (refinement 1):** if PR critical-path run exceeds
    ~₹25, alert in PR comment + downgrade to low-tier-only for the
    rest of the run.
  * **Manual full-suite trigger (refinement 2):**
    `/run-full-suite` PR comment runs the full suite for risky
    PRs; useful for agent code changes without forcing it on all
    PRs.

Steady-state cost projection: ~₹650/week (~20 PRs × ~₹15-20 + 7
nights × ~₹50). Manageable for a launch-stage project.

---

## How to extend Phase B coverage

When to **add a new journey** (new test file):
  * The product surface added a UI flow or backend endpoint that
    exercises a code path none of the existing 9 journeys reach.
  * Example trigger: launch a new agent surface (Phase C+).
  * Cost: 1 test file, 2-5 tests, ~₹1-5 if real-LLM.

When to **extend an existing journey** (add tests to existing file):
  * Edge case or contract-pin test for an already-covered
    journey's surface.
  * Example trigger: a new field added to an existing schema; the
    test file already covers the journey, just needs a contract pin.
  * Cost: 1-3 tests added; ~₹0-3 if real-LLM.

When **infrastructure extension is warranted**:
  * The new tests need a fixture or helper that doesn't exist AND
    will be reused across ≥3 future tests.
  * The Phase A 3-extension budget across CP2-CP4 was unused; if
    Phase C consumes it, that's appropriate.
  * If a single-test extension is sufficient, inline it instead.

When to **mark a test xfail-strict**:
  * The test exposes a real product bug AND the bug isn't a
    launch-blocker AND fix-now would be out of scope. Convention A
    from CP1 applies: xfail-strict + follow-up doc with fix scope.
  * Drop the xfail when the fix lands (mechanical).

---

## Pattern catalog state at Phase B close

See per-pattern docs for canonical statements. Phase B-era updates:

  * **Pattern 22** elevated to "verify always; treat any unverified
    claim as suspect by default." Bidirectional value (drift-detect
    + drift-prevent) explicit. ~14 D18 instances.
  * **Pattern 27 vs 29** disambiguation rule registered in Phase A
    overview. Diagnostic primitive: call-site grep across consumers.
  * **Pattern 33 (new)** — bug-surfacing front-loading principle.
    Order checkpoints by diagnostic-clarity, not mechanical
    test-type. D18 Phase B distribution is the canonical evidence.
  * **Pattern 34 (new)** — pre-flight infrastructure investment
    compounds non-linearly with consumption. Break-even ~10-15
    consumers. D18 retrofit-3 is the canonical evidence.

---

## Phase C readiness

GREEN with two TODOs before launch:

  1. Fix BUG-CP4-LESSON-FK-500 (1-hour scope; pre-validate lesson
     in `complete_lesson` service OR catch IntegrityError → 404).
  2. Investigate `auth-signup-grace-jsonb-cast-syntax`; fix +
     backfill if needed (2-4 hour scope).

All Phase C-relevant infrastructure (cost tracking via D17b ITEM 1
+ BUG-CP1F fix; agent_invocation_log populating unconditionally
across all paths; runner overlay verified) is ready for production
load monitoring and operational consumers.

The batch-flakiness operational note
(`docs/followups/d18-phase-b-batch-flakiness-under-real-llm-load.md`)
is documented but doesn't block launch — it's a CI signal-quality
concern, not a product bug.

---

## Cross-references

  * `docs/architecture/d18-phase-a-test-infrastructure-overview.md`
    — infrastructure substrate that Phase B consumed.
  * `docs/followups/d18-phase-b-bug-taxonomy-and-discipline.md` —
    bug taxonomy + CP2 zero-bug caveat + Pattern 22 bidirectionality.
  * `docs/followups/d18-phase-b-bug-surfacing-front-loaded.md` —
    front-loading principle (now Pattern 33).
  * `docs/followups/d18-phase-b-batch-flakiness-under-real-llm-load.md`
    — operational noise distinction.
  * `docs/followups/llm-cost-tracking-convention-enforcement.md` —
    long-term enforcement to prevent BUG-CP1F-class recurrence
    (Pattern 27).
  * `docs/followups/bug-cp1d-*.md`, `bug-cp1e-*.md`, `bug-cp1f-*.md`,
    `bug-cp4-lesson-fk-500.md`, `auth-signup-grace-jsonb-cast-syntax.md`
    — per-bug records.
  * `.github/workflows/playwright-tests.yml` — CI configuration
    (Phase A authored; Phase B CP5 documented the shape β decision).
