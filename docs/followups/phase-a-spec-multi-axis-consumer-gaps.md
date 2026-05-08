# Phase A spec ↔ multi-axis consumer gaps — retrospective

**Status:** Open. Institutional learning. Severity: MEDIUM.
**Origin:** D18 Phase B pre-CP1 verification (Path A) +
post-shakedown CP1.2 surfaces, 2026-05-08.
**Created:** 2026-05-08 alongside the retrofit-3 commit.

## What this is

D18 Phase A shipped a 6-checkpoint test infrastructure (CP1-CP6;
commits 84c9835 → 607085c). Each CP had its own smoke tests
exercising the specific component it added. All 50 CP-internal
smokes passed by Phase A close.

Then Phase B started authoring journey tests against the
infrastructure. Within ~2 hours of Phase B kickoff, three retrofit
commits had landed:

  * **retrofit-1** (commit pair `d6b2374` + `f84803d`) — runner
    overlay end-to-end execution. Three layered gaps: missing
    pytest in upstream image, frontend bundle's baked
    `localhost:8080`, bind mount shadowing the runner's `.venv`,
    plus CORS via same-origin policy. Plus a fourth (pnpm 11
    rebuild break) that was orthogonal but blocked the fix.
  * **retrofit-2** (commit `528a7ac`) — `PracticePage` page object.
    The eight Phase A page objects didn't include the
    `/practice?mode=capstone` work surface; CP1 journey (c)
    couldn't be authored without it. Plus a Pattern 22 finding
    inside the new page object: `assert_capstone_rail_visible`
    over-asserted on a state that requires fixture-seeded entitlement.
  * **retrofit-3** (this commit) — `content_seeders.py` +
    `sync_async_bridge.py`. Phase A's `playwright_test` template
    has 1 lesson (the synthetic CP4 capstone harness); CP1 journey
    (b) needed real lesson content. Phase A's role-state fixtures
    seed via async DB sessions; CP1 browser tests needed a way
    to bridge async-DB seeding into sync Playwright sessions.

Each retrofit is small (≤2 hours of work, ~₹0). Each closed cleanly.
The pattern is clear: **Phase A's per-component smoke tests verified
each component in isolation, but missed multi-axis consumer scenarios
that combine components.**

## The canonical gap

A test infrastructure has multiple consumer axes:

  * **Topology axis** — host-run vs in-container vs runner-overlay
    execution.
  * **Content axis** — what data is seeded in the DB the consumer
    reads from.
  * **Session axis** — sync (Playwright sync API) vs async
    (pytest-asyncio fixtures) test code.
  * **Fixture-state axis** — placeholder-password-fast vs
    login-capable-bcrypt vs entitled-with-content vs role-state-seeded.

Phase A's CP-internal smokes each exercised one axis at a time:

  * CP3 page-object smokes: ran in non-overlay topology; used
    pre-existing fresh-registered student; never checked
    populated-state branches.
  * CP4 fixture smokes: ran async-only; never bridged into a
    browser session.
  * CP6 full-loop smoke: auto-skipped its own multi-axis case
    (PLAYWRIGHT_FULL_LOOP_OK gate); the actual end-to-end
    execution came at Phase B pre-CP1.

Phase B's first journey tests are by definition multi-axis: a
journey wires login + DOM rendering + DB state + assertions. Each
axis intersection that Phase A didn't smoke surfaces as a gap when
the journey test runs.

## Three concrete instances

**Instance 1 — Runner overlay (retrofit-1).** Topology axis crossed
session axis. The CP6 runner image was pulled and "verified"; never
actually executed. First execution surfaced four serialized gaps
(deps + frontend URL + bind mount + CORS) that all needed to land
together for the smoke to pass.

**Instance 2 — Capstone rail testid (retrofit-2 + during retrofit-2
authoring).** Page-object axis crossed fixture-state axis. Phase A
authored `PracticePage` selectors against the populated-bundle
DOM; tests using a fresh-registered student hit the empty-state
DOM which doesn't carry the same testids.

**Instance 3 — Lesson content + bridge (retrofit-3).** Content
axis + session axis + fixture-state axis. The `playwright_test`
template was deliberately empty (per-test seed); CP1 journey (b)
needs lessons; the bridge from async DB seeders into sync browser
sessions wasn't extracted. Each individual axis was authored;
combining them required a new helper.

## Discipline going forward

For future architect-led testing arcs, Phase A specs should include
a mandatory **multi-axis consumer pre-flight**:

  1. List the axes the test infrastructure presents to consumers.
  2. For each pair of axes, specify at least one smoke test that
     exercises the intersection.
  3. Auto-skip-with-PLAYWRIGHT_FULL_LOOP_OK style gates are useful
     local-dev affordances but **must be exercised at least once**
     end-to-end before the infrastructure is declared shipped.
     A pulled image is not an executed image.

The N=4 Pattern 29 evidence base now reads:

  * **N=1 admin_console_*** (D14b) — scaffolded UI flow that
    didn't fire end-to-end.
  * **N=2 runner overlay** (CP6 → retrofit-1) — pulled but never
    executed.
  * **N=3 PracticePage assert_capstone_rail_visible** (retrofit-2)
    — page-object selector that worked for the case it was
    authored against, broke for the cross-axis case.
  * **N=4 playwright_test content + sync/async bridge**
    (retrofit-3) — single-axis fixtures didn't compose for
    multi-axis consumption.

**Canonical statement (refined at retrofit-3 close):**

> Test infrastructure is "ready" only when its happy-path smoke
> AND each cross-axis consumer scenario have been executed
> end-to-end at least once. A component that passes its own
> internal smoke but has never been used by a real consumer is
> scaffolded-but-unconsumed; expect surfaces when the first
> consumer arrives.

## Cross-references

- `docs/followups/pytest-asyncio-pytest-playwright-split-runs.md`
  — the canonical sync/async tension this bridge module addresses.
- `docs/architecture/d18-phase-a-test-infrastructure-overview.md`
  — Phase A overview (updated at retrofit-3 close with the N=4
  evidence + multi-axis framing).
- Retrofit commit chain: `d6b2374` → `f84803d` → `528a7ac` →
  retrofit-3 (this commit).

## Severity rationale

**MEDIUM, not HIGH:**
  * Each retrofit was small and caught at the right cost.
  * No production code was affected.
  * Phase B authoring picked up cleanly after each fix.
  * Cumulative D18 Phase B cost still ~₹0 at retrofit-3 close.

**Not LOW** because the pattern is general; if D19+ ships another
testing arc without applying the multi-axis pre-flight discipline,
the same retrofit cost will recur.
