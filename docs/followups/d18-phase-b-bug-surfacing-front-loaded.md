# D18 Phase B — bug-surfacing value is front-loaded (CP1-leveraged
# downstream cleanliness)

**Status:** Open. Institutional finding. Folds into the canonical
migration-verification-discipline argument at CP5 closure.
**Origin:** D18 Phase B pre-CP4 architect-bundled registration,
2026-05-09.

## What this is

Phase B's bug-discovery distribution across CPs:

  * **CP1 (critical-path happy paths)**: 3 real bugs caught
    (BUG-CP1D schema/ORM drift; BUG-CP1F missing _track_llm_usage
    convention drift; BUG-CP1E downstream symptom of F).
  * **CP2 (high-value edge cases on critical paths)**: 0 new
    product bugs. Test-authoring Pattern 22 surfaces (1) without
    finding new product issues.
  * **CP3 (UI-action → DB-row traceability contracts)**: 0 new
    contract bugs. Test-authoring Pattern 22 surfaces (2) without
    finding new product issues.

The infrastructure-layer bugs caught at CP1 — once fixed
correctly — do NOT shadow into the edge cases or traceability
assertions exercised by CP2+CP3. The integration cost paid at
CP1 ($\sim$₹6 of authoring + ~₹8 of remediation) bought clean
contract-assertion runs at CP2+CP3.

The pattern: **bug-surfacing value is front-loaded**. Critical-path
happy paths through real infrastructure are the highest-density
bug-finding surface, not because happy paths exercise the most
code, but because infrastructure failures break the happy paths
deterministically.

## Why this matters for migration-verification discipline

Future architect-led testing arcs (D19+ shape) face a scoping
question: how many tests? Where to invest first? The Phase B
distribution suggests:

  * **Front-load critical-path happy-path investment.** Three
    real bugs at integration cost is the high-yield target;
    cheaper than expensive-comprehensive coverage that doesn't
    increase signal density.
  * **Edge cases + traceability follow as cleanup verification.**
    Their value is "did the CP1 fixes hold under a stronger
    assertion?" not "find new bugs."
  * **CP4 is where new bugs are most likely to surface again** —
    because CP4 exercises behavioral paths (errors, adversarial
    input, concurrency) that the happy-path-+-edges progression
    didn't reach.

The canonical statement (proposed for CP5):

> Front-load testing investment on critical-path happy paths
> through real infrastructure. Infrastructure-layer bugs caught
> there propagate into clean downstream assertions; behavioral-
> layer bugs surface separately under error-state and adversarial
> testing. Distribute test-authoring effort along the bug-class
> distribution, not uniformly.

## Pattern 22 bidirectional canonical statement

Phase A + Phase B produced N=14+ Pattern 22 instances. CP3 made
the bidirectional value explicit:

  * **Drift-caught direction** (CP1 era): existing claim about
    schema/route/payload is verified against live system; found
    wrong; fix the artifact. BUG-CP1D ORM drift; BUG-CP1F missing
    convention; CP4 retrofit's nonexistent column claims.
  * **Drift-prevented direction** (CP2-CP3 era): during authoring
    of a new artifact, the author would-have asserted incorrectly;
    live-system check before final assertion produced the correct
    test directly. CP2 capstone empty-code (would have asserted
    accept; verified schema → flipped to reject); CP3 admin DM
    (would have asserted triggered_by='admin'; verified → pinned
    'admin_manual'); CP3 mock interview (would have queried
    agent_actions; verified service docstring → queried
    mock_cost_log + agent_invocation_log).

**Both directions are equally valuable; verify always; treat any
unverified claim as suspect by default.** The drift-prevented
direction is invisible by default (tests pass; nobody knows the
author *would have* failed); deliberate practice surfaces it as
caught-at-authoring corrections.

## Cross-references

  * `docs/followups/d18-phase-b-bug-taxonomy-and-discipline.md` —
    bug taxonomy (infrastructure-layer vs behavioral); CP2 zero-
    bug caveat; this finding's evidence base.
  * `docs/followups/d18-phase-b-batch-flakiness-under-real-llm-load.md`
    — operational-noise distinction (not a bug class).
  * `docs/architecture/d18-phase-a-test-infrastructure-overview.md`
    — Pattern 27 vs 29 disambiguation rule (related discipline).
