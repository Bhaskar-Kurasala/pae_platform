# Sandbox Path A → Path B migration (E2B or container-per-execution)

**Status:** Open. D11.5 ships Path A (process-based isolation in the same Linux container as the application). Path B (container-per-execution OR E2B managed sandbox) is the production-grade answer documented in pass-3d-tool-implementations.md.
**Created:** 2026-05-07 (D11.5 closure).
**Triage:** Production-readiness gate. Pre-launch if AICareerOS opens to paying users; otherwise D17 cleanup or earlier if production traffic shows escape attempts in `sandbox_escaped=True` audit rows.
**Cross-references:** Pass 3d §G.5 (sandbox infrastructure spec); `app/sandbox/security.py` threat model docstring; D11.5 closure.

## What

D11.5's Path A executes student code as an `appuser` subprocess inside the application container with five `RLIMIT_*` constraints and environment scrubbing. The threat model in `security.py` documents what's mitigated (CPU/memory runaway, fork bombs, env secret leakage, FD exhaustion) versus what's NOT mitigated (host filesystem reads, network egress, kernel exploits, side-channels, persistent storage).

Path B replaces process-based isolation with container-per-execution. Two main variants:

1. **E2B (managed cloud sandbox)** — pass3d's spec recommendation. Each execution spins a tiny VM-isolated container at E2B; we just submit code and read back results. Network egress and filesystem isolation are E2B's responsibility. Cost: ~$0.0002/execution at E2B pricing as of late 2025.
2. **Self-hosted container-per-execution** — Docker-in-Docker or k8s job-per-execution. We own orchestration. Cost: AICareerOS infra + ~50ms-500ms cold start per execution. Full control, more complexity.

## Why D11.5 shipped Path A despite spec recommending E2B

D11.5's deliverable was *the deferred D11 sandbox infrastructure*. Engineering cost of building Path A was already committed; switching to E2B mid-deliverable would have required:
- E2B account + API key provisioning + cost ceiling
- Schema layer rewrite (E2B has its own request/response shape)
- Integration testing against an external service (introduces flakiness)
- Cost ceiling + runaway protection at the integration layer

The Path A surface (asyncio subprocess + 5 rlimits + env scrub + escape detection) gives consumers (`run_in_sandbox`, `run_tests`) a stable contract. The contract is provider-agnostic — switching to E2B means swapping the executor implementation; consumers don't change.

## What Path B fixes that Path A doesn't

| Threat class | Path A | Path B (E2B or container) |
|---|---|---|
| Host filesystem reads (`/etc/passwd`, etc.) | Best-effort detection only | Container fs is empty except for the supplied code |
| Network egress | Best-effort detection only (subprocess can call out) | Container network policy denies egress |
| Persistent storage attacks | RLIMIT_FSIZE caps writes; no isolation across executions | Container is destroyed after execution |
| Kernel exploits | Host kernel is shared | Cloud provider's hypervisor isolates kernels (E2B); container shares kernel but with seccomp profile (self-hosted) |
| Side-channel attacks | Visible to subprocess | Container-isolated (E2B uses VMs; self-hosted with appropriate cgroups) |

## Migration discipline

When Path B lands, the swap should preserve:

1. **`SandboxRequest` + `SandboxResult` schemas** — these are the spec contract per Pass 3d §E.3.2; consumers don't change.
2. **`run_in_sandbox` + `run_tests` tool surface** — agents continue to invoke through capability-gated tools.
3. **`agent_tool_calls` audit row shape** — args/result jsonb columns capture sandbox-specific fields without schema migration.
4. **Threat model documentation** — `security.py` module docstring updates to reflect what Path B actually mitigates (the "NOT mitigated" list shrinks).

Path B's executor body replaces `app/sandbox/executor.py::execute`. The `app/sandbox/security.py` resource-limit primitives become unused (or migrate to seccomp profile generation for self-hosted variant).

## Triage signals

Promote Path B from "open follow-up" to "blocking" when ANY of:
- AICareerOS opens to paying users (production-readiness gate).
- Production audit rows show >1% `sandbox_escaped=True` rate.
- A specific compliance requirement (SOC 2, GDPR processor agreement) requires verifiable execution isolation.
- A D14+ agent needs network access during execution (e.g., scraping student-supplied URLs); Path A's "always-deny network" can't honor that.

## Decision frame for E2B vs self-hosted

E2B wins on:
- Time-to-implement (days vs weeks)
- Operational simplicity (no DinD or k8s-job complexity)
- Per-execution cost transparency

Self-hosted wins on:
- No external dependency
- Full control over execution environment (specific Python versions, custom packages)
- No per-execution variable cost — fixed infra spend

For AICareerOS at current scale: E2B is the right answer if cost ceiling fits. Switch to self-hosted only when execution volume makes E2B's per-execution pricing painful AND we have ops bandwidth to run k8s-job orchestration.

## Cross-references

- [backend/app/sandbox/executor.py](../../backend/app/sandbox/executor.py) — Path A implementation; replace this file's body for Path B
- [backend/app/sandbox/security.py](../../backend/app/sandbox/security.py) — threat model docstring; update on Path B landing
- [backend/app/schemas/sandbox.py](../../backend/app/schemas/sandbox.py) — Path-agnostic schemas; preserved across migrations
- pass-3d-tool-implementations.md §G.5 — original spec recommending E2B
