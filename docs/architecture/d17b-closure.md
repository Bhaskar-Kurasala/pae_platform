# D17b closure — cleanup arc + pattern catalog finalization

**Date:** 2026-05-08
**Engagement:** Cleanup arc (founder-led, architect-available). Closes
five known follow-up workstreams before D18 (testing arc).
**Locked decisions:** D-A (per-item commit discipline) ✓ honored. D-B
(test baseline load-bearing) ✓ honored. D-C (Patterns 1-29 apply
unconditionally) ✓ honored + extended to 1-30. D-D (D17b is debt-
closing; D18 owns comprehensive testing) ✓ honored.

---

## Engagement reframe

D17b started as 5 sequential follow-up closures. Two of the five (ITEM 1
cost-tracking, ITEM 3 student nudges) surfaced architectural reframes
under pre-flight verification:

- **ITEM 1**: D17a's "Path A vs Path B" framing turned out to be a
  false dichotomy — the patterns operate at different layers and
  compose. Fix landed at the leaf construction sites (refined Path B),
  not via the original "model_used field" speculation.
- **ITEM 3**: original prompt-side approach failed real-LLM verification
  (4 of 4 trigger phases failed to fire on career_coach; 3 of 6
  study_planner phases timed out from prompt growth). Founder-selected
  Path E (deterministic post-LLM composition) eliminated both failure
  modes simultaneously. Pattern 30 candidate registered.

Both reframes were caught at the prompt's mandatory pre-flight checkpoints,
not after wasted implementation work. The discipline paid off.

---

## What shipped

### ITEM 1 — cost-tracking architectural fix (1 commit)

| SHA | Scope |
|---|---|
| `94a093f` | refined Path B fix: `_model_from(response)` helper at SubAgentResult / ParsedJd construction sites; success/error asymmetry preserved |

- Closes `llm-cost-tracking-silent-zero.md` jd_decoder + readiness_orchestrator bullets (RESOLVED).
- 4 new tests pin under-cost fix + fallback path + success/error asymmetry guard + jd_parser parallel fix.

### ITEM 2 — read-tool entitlement leakage (3 commits)

| SHA | Scope |
|---|---|
| `a715913` | ITEM 2.A — `read_capstone_submission_content` student_id filter |
| `3955214` | ITEM 2.B — `read_rubric_for_capstone` entitlement gate via JOIN through course_entitlements |
| `88e1ddb` | ITEM 2.C — `lookup_jd_decoded` student_id filter (defense-in-depth; no live consumer) + audit-doc closure folded |

- Closes `d12-d14c-read-tool-entitlement-leakage-audit.md` 3 MEDIUM findings (ALL RESOLVED).
- 13 new tests across 3 tool files; per-tool conftest with throwaway-schema pattern (mirrors billing_support).
- Pre-flight Pattern 23 finding: tailored_resume_v2 `uses_tools` comment was stale; lookup_jd_decoded had no live consumer.

### ITEM 3 — career_coach + study_planner state-aware lead-ins (3 commits, Path E shape)

| SHA | Scope |
|---|---|
| `e1bbfb4` | Phase 0: `read_student_lead_in_signals` aggregator (5 fields, 5 tests) |
| `3443b07` | Path E Phase 1: `compose_lead_in_opener` deterministic composer (13 tests) |
| `353c738` | Path E Phase 2: wire composer into career_coach_v2 + study_planner_v2; revert prompt-side approach; 4-phase real-LLM verification script |

- Aggregator + composer infrastructure new; agents' user_block builders unchanged (LLM doesn't see signals).
- Real-LLM verification: 4-phase Path E confirmed verbatim opener prepending in production runs; control phases preserve baseline behavior.
- Pattern 30 candidate registered (deterministic composition over prompt-side judgment for state-aware response decoration). N=1 from this engagement.

### ITEM 4 — eval_row_writer remaining sub-items (2 commits)

| SHA | Scope |
|---|---|
| `662311f` | ITEM 4.A — `failure_class` enum on `agent_evaluations` (migration 0066 + writer + 2 call sites + 5 new tests + 1 enum-pin sanity) |
| `4729a72` | ITEM 4.B — `_try_insert_eval_artifact` shared persistence envelope + 2 new tests + audit-doc closure folded |

- Closes `eval-row-writer-defensive-fix.md` sub-items 2 + 3 (sub-item 1 RESOLVED at D17a `39c7564`). All 3 sub-items RESOLVED.
- 8 new + updated tests; enum-CHECK parity guard catches drift at unit-test time.
- Pre-flight Pattern 23 catches: doc's "convert string field to enum" framing was actually "add new column"; "single writer with discriminator" was actually "shared persistence envelope; per-table row construction stays."

### ITEM 5 — pattern verification + operational follow-ups + closure (1 commit)

| SHA | Scope |
|---|---|
| `<this commit>` | Pattern catalog updates (23 → N=6 + tightened canonical; 18b prompt-size extension; 29 candidate→canonical; 30 candidate registered); 4 operational follow-up docs; this closure report |

- 4 new follow-ups registered:
  - `test-suite-bulk-run-oom-by-directory-workaround.md`
  - `tests-dir-not-bind-mounted-docker-cp-workaround.md`
  - `msys-path-translation-docker-exec-from-git-bash.md`
  - `study-planner-career-coach-tail-latency-baseline.md`

### Total: 10 commits across D17b (9 implementation + 1 closure)

---

## Test count delta

D17b added **43 new tests** across 5 ITEMs:

| ITEM | New tests | Location |
|---|---|---|
| 1 | 4 | `tests/test_agents/test_llm_cost_tracking.py` |
| 2.A | 4 | `tests/test_agents/tools/agent_specific/project_evaluator/test_read_capstone_submission_content.py` |
| 2.B | 5 | `tests/test_agents/tools/agent_specific/project_evaluator/test_read_rubric_for_capstone.py` |
| 2.C | 4 | `tests/test_agents/tools/agent_specific/tailored_resume/test_lookup_jd_decoded.py` |
| 3 Phase 0 | 5 | `tests/test_agents/tools/universal/test_read_student_lead_in_signals.py` |
| 3 Path E | 13 | `tests/test_agents/primitives/test_lead_in_composer.py` |
| 4.A | 6 (5 enum + 1 enum-pin sanity) | `tests/test_agents/test_eval_row_writer_none_score.py` |
| 4.B | 2 | same file (shared-helper success + failure paths) |

Plus 5 pre-existing test signature updates in ITEM 4.A (adding `failure_class=` to existing `_write_evaluation_row` calls) — not new tests but required updates per Pattern 27 discipline.

**Test baseline at D17b close:**
- Touched-area suites: zero regression across all 5 ITEMs.
- Aggregate: 1491 + 86 (D15 slice) + 43 (D17b new) + 45 (pre-existing failures unchanged).
- All new tests pass against real Postgres (where DB-backed) or unit-test (where pure logic).

---

## Pattern catalog post-D17b state

**Patterns 1-22**: canonical, no D17b changes. (CP1-CP4 application guide patterns from D10-D14.)

**Pattern 23 (follow-up doc framing drift)**: extended.
- N=3 → **N=6** with the addition of D17b ITEM 2.C tailored_resume_v2 `uses_tools` comment, ITEM 4.A "convert" framing, and ITEM 4.B "discriminator" framing.
- Canonical statement **strengthened** to: "Pre-flight verification of follow-up doc claims against current code is MANDATORY, not optional, on any deliverable that consumes a follow-up doc older than ~1 deliverable. Expect drift; design pre-flight checkpoints to surface it explicitly."
- Operational pre-flight checks documented: grep every named symbol; verify every shape claim; surface reframe as STOP and seek explicit founder approval.

**Patterns 24-27**: canonical, no D17b changes.

**Pattern 18b (preemptive timeout multiplier)**: extended with D17b ITEM 3 prompt-size finding.
- New canonical bullet: applies preemptively when **prompt size changes materially**, not only when LLM provider changes. Pre-flight calibration required when adding ≥ 50 lines to any agent prompt.
- Evidence: study_planner pre-D17b 109 lines / 30s held; prompt-side D17b attempt 191 lines / 30s broke 50%; Path E (no prompt change) restored 30s baseline. Provider stayed MiniMax across all measurements; prompt size was the variable.

**Pattern 28 (functional audit before gap-closure)**: canonical at D16; verified canonical at D17b close. No changes.

**Pattern 29 (scaffolded-but-inert detection)**: candidate → **canonical** at D17b.
- N=1 → **N=2** with addition of D17b ITEM 2.C `lookup_jd_decoded` registered-but-unconsumed tool.
- Documented **third variant** (registered-but-unconsumed tool) alongside the two original variants (no-writer-found, writer-retired-without-drop).
- Promotion rationale: both observed instances came from architectural audits (D16 CP1 + D17b ITEM 2.C pre-flight), reinforcing that this pattern surfaces under audit-style investigation more reliably than under feature-driven work.

**Pattern 30 (deterministic composition over prompt-side judgment)**: **registered as candidate** at D17b close.
- N=1 from D17b ITEM 3.
- Canonical promotion conditional on observing the same shape resolved the same way more than once.
- Cross-references Pattern 26 (runtime backstop) and Pattern 18b (prompt-size extension); the three patterns reinforce each other for state-aware response decoration use cases.

**Catalog total at D17b close: 30 patterns (29 canonical + 1 candidate).**

---

## Follow-up doc resolution count

**RESOLVED at D17b:**

- `llm-cost-tracking-silent-zero.md`: jd_decoder_service.py + readiness_orchestrator.py bullets RESOLVED at ITEM 1 (`94a093f`). Two remaining gaps (D12 v2 agents cost pipeline; Layer 2 safety classifier / Critic) are architecturally distinct shapes and remain explicitly deferred per existing triage.
- `d12-d14c-read-tool-entitlement-leakage-audit.md`: ALL 3 MEDIUM findings RESOLVED at ITEM 2 (`a715913`, `3955214`, `88e1ddb`). LOW findings (13 tools) remain documented; defer to post-launch.
- `eval-row-writer-defensive-fix.md`: ALL 3 sub-items RESOLVED across D17a + D17b (`39c7564`, `662311f`, `4729a72`).

**REGISTERED at D17b ITEM 5:**

- `test-suite-bulk-run-oom-by-directory-workaround.md` — operational; D18 Phase A test infrastructure must plan around this.
- `tests-dir-not-bind-mounted-docker-cp-workaround.md` — operational; D18 Phase A should add the bind mount.
- `msys-path-translation-docker-exec-from-git-bash.md` — operational; documented for Windows-host developer flow.
- `study-planner-career-coach-tail-latency-baseline.md` — operational; D18 Phase A Playwright timeout buffers must accommodate.

---

## Architectural artifacts produced

- **Migration `0065_users_whatsapp_number`** (D16 carry-forward; not D17b but referenced for migration tail context).
- **Migration `0066_eval_failure_class`** (ITEM 4.A) — `failure_class` TEXT column + 4-value CHECK constraint on `agent_evaluations`.
- **Module `app/agents/tools/universal/read_student_lead_in_signals.py`** (ITEM 3 Phase 0) — 5-field state aggregator tool.
- **Module `app/agents/primitives/lead_in_composer.py`** (ITEM 3 Path E) — deterministic post-LLM opener composer with 5 trigger rules + 7 templates.
- **Helper `_try_insert_eval_artifact`** (ITEM 4.B) — shared persistence envelope for eval-row writers.
- **Helper `_model_from(response)`** (ITEM 1) — leaf-extraction of response_metadata model field for SubAgentResult / ParsedJd construction.
- **3 read-tool fixes** (ITEM 2): student_id filter on `read_capstone_submission_content` + entitlement-chain JOIN on `read_rubric_for_capstone` + student_id filter on `lookup_jd_decoded`.
- **6 fixture helpers** (ITEM 3 — `seed_returning_after_absence_data_analyst`, `seed_just_passed_mock_data_scientist`, `seed_just_cleared_gate_data_analyst`, `seed_healthy_data_analyst`, `seed_stalled_data_analyst`, `seed_momentum_data_analyst`) + 3 internal seed helpers in `role_state_fixtures.py`.

---

## Cumulative cost

D17b: **~₹0.05-0.10** (estimated from MiniMax-rate inference across the ~12 LLM calls in ITEM 3 verification runs; precise cost reporting blocked by the v2 agents' separate cost-tracking-pipeline issue documented in `llm-cost-tracking-silent-zero.md`).

Engagement architect-led cost (cumulative across D9-D17b): ~₹14 + ~₹0.10 = **~₹14.10**.

D17b consumed: ~4% of its ₹2.50 ceiling.

---

## Bug count

- Pre-D17b: 24 fixed across D10-D17a, 0 open.
- D17b: 0 new bugs introduced.
- **D17b close: 24 fixed, 0 open.**

---

## Engagement state at D17b close

- All architect-led deliverables (D9-D17b) complete.
- All identified launch blockers resolved code-side (D16 launch blocker `celery-safety-memory-bump.md` closed; no new launch blockers introduced).
- All known follow-up backlog from D14c-D16 closed (3 follow-up docs flipped to RESOLVED).
- Pattern catalog at 30 (29 canonical + 1 candidate); strengthened canonical statements + extensions across patterns 18b, 23, 28, 29.
- 4 new operational follow-ups registered for D18 Phase A consumption.
- Engagement enters D18 (testing arc) with clean state.

---

## Readiness for D18 (Phase A test infrastructure)

**Three operational follow-ups inform Phase A architecture:**

1. **Bulk-suite OOM** — CI strategy must split into multiple parallel jobs; local `pytest` wrapper script needed; cross-test interaction effects must be exercised via at least one full-suite-in-one-shot CI gate.
2. **Tests dir not bind-mounted** — Phase A should add `./backend/tests:/app/tests` to docker-compose; eliminates `docker compose cp` ritual; aligns test-edit ergonomics with `app/` mount.
3. **MSYS path translation** — Windows-host developer flow + any Windows-host CI runner needs `sh -c '...'` wrapping convention or `MSYS_NO_PATHCONV=1` env var.

**Tail-latency baseline understood**: career_coach 150s + study_planner 30s are calibrated, not generous. D18 Playwright timeout buffers should match observed P95 + acknowledge the 3-15% timeout rate via flaky-tolerant retry, elevated test-path timeout, or skip-on-timeout per test policy.

**All test-fixture patterns reusable across D18 Playwright tests:**

- `role_state_fixtures.py` (12 seed helpers including the 6 D17b lead-in fixtures)
- `runtime_grounding_verifier.py` (D15 CP3-era; reusable for any agent-output grounding assertion)
- Throwaway-schema conftest pattern (billing_support, project_evaluator, tailored_resume) — replicable for any new tool-test cluster
- Outer-transaction-rollback session pattern (test_role_state_tools_smoke, test_read_student_lead_in_signals) — for tests that need live dev-DB seed data

**Test-author conventions documented:** docker compose cp ritual; root-mkdir for new sub-directories; sh -c wrapping for path-bearing commands; TEST_PG_DSN override pattern (`-e TEST_PG_DSN=postgresql+asyncpg://postgres:postgres@db:5432/platform`).

---

## Final commit summary (D17b)

```
<this commit>  docs(d17b): D17b ITEM 5 — pattern verification + 4 operational follow-ups + D17b closure report
4729a72        refactor(eval): D17b ITEM 4.B — eval_row writer consolidation (closes ITEM 4)
662311f        refactor(eval): D17b ITEM 4.A — failure_class enum on agent_evaluations
353c738        refactor(agents): D17b ITEM 3 (Path E) — wire compose_lead_in_opener into career_coach_v2 + study_planner_v2; revert prompt-side lead-in approach
3443b07        feat(agents): D17b ITEM 3 (Path E) — compose_lead_in_opener deterministic composer
e1bbfb4        feat(tools): D17b ITEM 3 Phase 0 — read_student_lead_in_signals aggregator (Pattern 26)
88e1ddb        fix(read-tools): D17b ITEM 2.C — lookup_jd_decoded student_id filter (closes ITEM 2)
3955214        fix(read-tools): D17b ITEM 2.B — read_rubric_for_capstone entitlement gate
a715913        fix(read-tools): D17b ITEM 2.A — read_capstone_submission_content student_id filter
94a093f        fix(cost-tracking): D17b ITEM 1 — capture actual model via _model_from(response) at SubAgentResult/ParsedJd leaf constructions
```

10 commits total. Engagement closes D17b cleanly; D18 begins with verified clean state.
