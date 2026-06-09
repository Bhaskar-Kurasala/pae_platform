# Cost Engineering — the Science (companion to E1)

> **Status:** v1 reference (research-grounded, 2026-06). Companion to
> [E1-hierarchical-budget-admission.md](./E1-…). E1 is the *enforcement*; this is *attribution,
> the optimization playbook, and unit economics* — the difference between an AI product with a
> business model and one with a runway.

## 0. The law
**Cost attribution before cost control.** You can't govern what you can't attribute. Orgs routinely
cut **40–70% off the LLM bill within a quarter** once they stop guessing and start measuring. Every
agent span carries a **`tenant_id` — no exceptions** (tenant-less spans are the root cause of
month-end reconciliation pain), and a **`feature_id`** tag is *the* architectural decision that
determines whether per-feature accounting is possible at all. [Braintrust; digitalapplied; zop.dev]

## 1. Attribution at three levels (each answers a different stakeholder)
- **Per-agent-run** → engineering: is this run too expensive? did it hit the cap?
- **Per-feature** → product: what does "Q3 forecast" cost per user-month? (feature P&L)
- **Per-tenant** → finance/GTM: what does Acme cost vs its contract price? (margin)

The cost record on every LLM/tool call:
```
{ tenant_id, user_id_hash, agent_id, agent_version, run_id, step_kind, feature_id,
  model, provider, input_tokens, output_tokens,
  cache_read_tokens, cache_write_tokens,   # separate! see §2
  cost_micros, timestamp, region }
```

## 2. Cache economics (the cheapest 30–40% win)
Prompt cache: **~90% cheaper on reads**, slightly more on writes. Track **separate fields**
(`cache_read_tokens` vs `cache_write_tokens`) — without them, dashboards treat cached input as
regular input and cache-heavy workloads look *more* expensive than they are. A **read rate < 30%**
means TTL too short or requests too diverse. Cache-friendly ordering (stable prefix first — context
engineering) often delivers 30–40% reduction with no code change.

## 3. The optimization playbook (order matters — most teams skip to step 5)
1. **Measure where spend is** — rollups by (agent, step_kind, model). Usual surprise: 60–80% in one
   step.
2. **Verify cache hit rate** — fix prefix ordering before anything else (30–40% for free).
3. **Right-size per step** — frontier for plan/final; cheap for classify/critique (routing).
4. **Reduce token volume** — compress history past ~30% fill; drop unused tool schemas; large tool
   outputs → virtual filesystem handle.
5. **Distill high-volume narrow steps** — per-tenant/domain LoRA (only if volume math clears, ~100k+
   calls/day) — G5/D4.
6. **Cache tool results** — idempotent reads, short TTL.
7. **Memory-summary cache** — per (tenant,user), invalidate on write.
8. **Circuit breakers** — the safety net (E1), not an optimization.

## 4. Unit economics / FinOps-for-AI
- **Per-feature unit economics:** "Q3 forecast = $0.42/user-month"; the PM owns the number; moves
  require signoff.
- **Per-tenant margin:** contract $4,500/mo, agent cost $1,200 → 73% margin; flag if cost > 30% of
  contract.
- **Cost-to-value alignment:** free tier → cheap models + low caps; paid → frontier + higher caps.
- **Cost as an SLO:** "p95 cost per support-triage run < $0.05" tracked like p95 latency.
- **Anomaly detection:** 3σ spike per (tenant, agent) → alert (catches loops *and* abuse).
- **Healthy ratio:** AI-native products run **5–15% of revenue** as AI cost; 20–30% stretched; 40%+
  the model doesn't work yet.

## 5. The three dashboards (different stakeholders, different views)
| Dashboard | Shows |
|---|---|
| **CFO** | monthly spend + 90-day trend · per-tenant cost-vs-revenue margin · top-10 tenants · cost as % revenue · next-quarter forecast |
| **Eng lead** | per-agent cost trend · cost/run distribution (median/p95/**p99** — the tail dominates) · per-step breakdown · cache hit rate · runs that hit the cap (with trace links) |
| **PM** | per-feature cost/user-month · feature usage × cost = P&L · A/B variant cost delta |

## 6. The discipline that prevents quality regressions
Every optimization is measured on **cost AND quality** side-by-side; promote only on a Pareto
improvement. Reject pure cost wins that hurt quality and pure quality wins that balloon cost (the
"+1% quality / +300% cost" trap — ties the shadow multi-gate in eval-science).

## 7. Sources
- How to track LLM costs 2026 (per-user/feature/agent-run): https://www.braintrust.dev/articles/how-to-track-llm-costs-2026
- LLM agent cost attribution production 2026: https://www.digitalapplied.com/blog/llm-agent-cost-attribution-guide-production-2026
- LLM FinOps per-feature cost + token budgets: https://zop.dev/resources/blogs/llm-finops-per-feature-token-budget/
- AI cost optimization practical guide 2026: https://www.truefoundry.com/blog/what-is-ai-cost-optimization
