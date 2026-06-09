# Reliability — the Science (companion to Family D)

> **Status:** v1 reference (research-grounded, 2026-06). Companion to D1–D4. Reliability is the
> *least-understood, highest-impact* surface in agentic systems — there's now a paper literally
> titled **"Towards a Science of AI Agent Reliability" (arXiv:2602.16666)**. This is why the D
> patterns are shaped the way they are.

## 0. Why agent reliability is different
Deterministic services fail in ways you can enumerate; **agents fail probabilistically, partially,
and across many steps** — `pass · pass · FAIL · pass` even at high average. You cannot rely on
per-step model accuracy; the **harness must do what the model can't**: per-step verification,
safe retries, containment, recovery.

## 1. The compounding-failure law (memorize)
A 20-step workflow at 95% per-step reliability succeeds **0.95²⁰ = 36%** end-to-end. At 99% → 82%.
At 99.5% → 90%.
- **Implication:** raise per-step reliability *and* shorten/segment chains; add verification and
  dead-end detection between steps.
- **Worst-case, not average:** report **pass^k** ("all k attempts succeed" = pᵏ; 90% pass@1 → 57% @
  k=8) — see eval science. Average success hides the tail that pages you.
- Output-only evaluation hides 20–40% of trajectory corruptions ("corrupt success").

## 2. Durable execution semantics (the subtlety that bites)
- **Checkpoints ≠ durable execution.** Two models:
  - **Checkpoint** (LangGraph): save state *after each node*. Flexible code, no determinism rules —
    but **within-node progress is lost** on crash ("between nodes, not inside nodes"). A node looping
    200 items that crashes at 47 re-runs from 0. *Fix:* atomic node decomposition (one tool call per
    node) or a journal engine for the loop.
  - **Journal/replay** (Temporal/Restate): re-execute from start, replay cached results per journaled
    step. Strict determinism; built-in retries/timeouts/sagas.
- **Exactly-once vs idempotency:** engines give exactly-once *step* execution on a *registered*
  resource, but **not against arbitrary external APIs** — you still need **idempotency keys**.
  - **DBOS:** transactional exactly-once when the step writes the same Postgres as the workflow state.
  - **Restate:** `ctx.run()` journals before executing; re-invoke serves the journaled result, no
    idempotency key needed *for that call*.
  - **Temporal:** wrap non-deterministic/side-effecting work as activities (journaled once).
- **The 2026 enterprise pattern:** LangGraph for agent reasoning **+** Temporal for the orchestration
  around it (multi-day, sagas, activity retries). Compose, don't pick one.

## 3. Failure containment (why D2 exists)
- **Bulkhead** — shared resources = shared fate; isolate into per-lane/per-tenant pools.
- **Backpressure / load-shedding / admission control** — push back when over capacity.
- **DLQ + poison-message** — unprocessable work gets a home, not an infinite retry.
- **Circuit breakers + backoff** — stop hammering a failing dependency.
- **Saga / compensation** — on partial failure, preserve committed work; don't blind-rollback.
- Recommended **resilience stack:** resilience SDK + mesh timeouts/retries + workflow-engine
  compensation + queues with DLQ + admission control + OTel-first observability.

## 4. Reliability as parallel error budgets (why D3 exists)
One aggregate SLO lies. Run **a budget per SLI** (latency, completion, cost, loop, injection +
agent SLIs: ToolCallAccuracy, HallucinationRate, DelegationChainDepth, CalibrationDelta). Alert on
**burn rate** (page >14.4/1h), fire **exhaustion actions** (throttle / freeze-deploys / circuit-
break) — alert on *patterns*, not single events (a 20% success drop in 15 min is signal; one failed
run is noise).

## 5. Nondeterminism
Agents are non-deterministic by construction (sampling, tool/env variance, user variance). Recent
work (Thinking Machines Lab) targets *defeating nondeterminism in inference*; until then, treat
variance as a first-class metric (pass^k, trajectory/tool/judge variance) and design for it rather
than assuming it away.

## 6. The one-line test
> "Your deep-research agent has run 47 minutes and the worker dies — what happens?"

A staff answer walks: checkpoint durable at minute 47 → k8s restarts the pod → new worker pulls the
run → LangGraph resumes from the last node → any mid-flight tool call is retried (idempotency key
de-dupes a half-success) → ~30–60s observable downtime → *and* flags the within-node-loss subtlety
if a node was mid-iteration. That walk is the whole of Family D in one breath.

## 7. Sources
- Towards a Science of AI Agent Reliability (arXiv:2602.16666): https://arxiv.org/html/2602.16666v2
- Durable execution: Temporal / Restate / DBOS (2026): https://devstarsj.github.io/2026/04/03/durable-execution-temporal-restate-dbos-distributed-workflows-2026/
- DBOS vs Temporal (exactly-once / idempotency): https://www.tiarebalbi.com/en/blog/dbos-vs-temporal-postgres-durable-execution
- Durable execution for AI agents (Inngest): https://www.inngest.com/blog/durable-execution-key-to-harnessing-ai-agents
- Alerting on SLOs / burn rate (Google SRE): https://sre.google/workbook/alerting-on-slos/
