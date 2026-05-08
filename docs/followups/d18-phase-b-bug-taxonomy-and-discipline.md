# D18 Phase B — bug taxonomy + edge-case shadowing + Pattern 22 bidirectionality

**Status:** Open. Institutional finding. To be folded into the
canonical pattern catalog at CP5 closure.
**Origin:** D18 Phase B pre-CP3 architect-bundled registration,
2026-05-09 (post CP2 zero-bug close).

## Bug taxonomy (CP1 → CP2 evidence)

CP1 (critical-path happy paths) caught 3 real bugs:
  * BUG-CP1D — schema/ORM drift on `interview_sessions.updated_at`
  * BUG-CP1F — missing `_track_llm_usage` calls in 4 v2/agentic
    agents (cost-tracking convention drift)
  * BUG-CP1E — empty response from `/agentic/default/chat` under
    batch (downstream symptom of BUG-CP1F; auto-resolved)

All three were **infrastructure-layer bugs**: schema/ORM mismatch,
missing instrumentation calls, instrumentation-gap-cascading symptom.

CP2 (high-value edge cases on critical paths) caught **zero** new
product bugs.

The pattern: **infrastructure-layer bugs, once fixed correctly, do
not typically shadow into edge cases.** Fixing
`server_default=sa.func.now()` on a column fixes every code path
that ever inserts that row, not just the path the original test
exercised. Fixing the missing `_track_llm_usage` call in an agent
fixes cost tracking for every input that agent ever receives.

By contrast, **behavioral bugs** (logic errors, state-machine gaps,
error-handling omissions) DO shadow into edge cases. A logic error
that's correct on the happy path but wrong at a boundary condition
won't be caught by happy-path tests; correlated edge tests are
required.

CP1 caught only infrastructure-layer bugs because critical-path
happy paths are where infrastructure either works end-to-end or
breaks end-to-end. CP2's clean result is consistent with this
taxonomy: edge tests on already-fixed infrastructure produce no new
findings.

**Prediction:** CP4 (error states + deliberately-skipped harder edges)
will surface more bugs than CP2 did, because CP4 exercises behavioral
paths CP1+CP2 didn't reach. If CP4 also produces zero bugs, that's
either a strong correctness signal OR an under-scoping signal worth
examining at CP5.

## CP2 scoping caveat (honest record)

CP2's "zero new bugs" result is conditional on the scoping decision
to skip:
  * Concurrency / race edges (duplicate-email simultaneous registration,
    concurrent lesson-completion writes, etc.)
  * Token-budget overflow (very long inputs, deep conversation history)
  * Failure injection (network drops mid-action, DB failover during
    write)
  * Adversarial input (prompt injection on agent inputs, malformed
    JSON, oversized payloads)

That scoping was correct per the saved Phase B prompt's framing
("prioritize bug-finding signal over comprehensive coverage"). CP2
covered the high-value edge cases that real production systems hit;
the deliberately-skipped categories are CP4's territory or
post-launch.

**Read CP2's clean result as:**
  ✅ "All infrastructure-layer drift caught at CP1; remediation
     was robust enough to cover edge cases too"
  ⚠ NOT "critical paths are bug-free" (CP4 still pending)

## Pattern 22 bidirectionality (CP2 self-correction finding)

Phase A + Phase B have produced ~12 Pattern 22 instances. Reading
the corpus, the pattern's value is bidirectional:

  * **Drift-caught direction:** an existing artifact's claim about
    schema/route/payload shape is verified against the live system
    and found wrong. Fix the artifact. Examples: BUG-CP1D (ORM
    nullable=True vs schema NOT NULL), CP1F architecture seam (test
    expected /agents/chat to route to v2 agents — wrong endpoint),
    CP4 retrofit (`agent_actions.triggered_by_user_id` claimed by
    docs, doesn't exist on schema).
  * **Drift-prevented direction:** during authoring of a new
    artifact, the author *would have* assumed an incorrect contract,
    but live-system verification before assertion produced the
    correct test directly. Examples: CP2 capstone empty-code
    assertion (assumed accept=201; verified schema before final
    assertion → flipped to reject=422), CP1F orchestrator hypothesis
    (initial fix-direction was wrong; diagnose-first surfaced the
    actual root cause).

Both directions exist; both are valuable; the canonical statement
should reflect both at CP5.

**Proposed canonical refinement (CP5 work):**
> Pattern 22: any artifact making schema, route, or payload-shape
> claims must be verified against live-system introspection
> (`pg_constraint` / `pg_attribute` / live HTTP responses /
> `grep` across consumer sites). Apply at two moments: (1) when
> consuming an existing claim — does the claim still hold? (2)
> when authoring a new claim — does the live system match what
> I'm about to assert? Both moments are equally important; the
> drift-prevented direction is invisible-by-default and worth
> deliberate practice.

## Cross-references

  * `docs/followups/bug-cp1d-interview-sessions-updated-at-not-null.md`
    — closed; infrastructure-layer instance.
  * `docs/followups/bug-cp1f-cost-tracking-zero-on-agentic-path.md`
    — closed; infrastructure-layer instance (consumer convention drift).
  * `docs/followups/bug-cp1e-empty-response-under-batch.md`
    — closed; downstream symptom auto-resolved.
  * `docs/architecture/d18-phase-a-test-infrastructure-overview.md`
    — Pattern 27 vs 29 disambiguation rule (related discipline).
  * `docs/followups/llm-cost-tracking-convention-enforcement.md`
    — long-term enforcement to prevent BUG-CP1F-class recurrence.
