---
title: Pass 3i — Scale + Observability + Cost Model
status: Final — operational backbone for AICareerOS at 1,000+ students
date: After Pass 3h sign-off
authored_by: Architect Claude (Opus 4.7)
purpose: Answer "will this actually run reliably at 1,000 students, and how would we know if it didn't?" Three concerns interleave — scale (connection pools, Redis, worker topology, LLM rate limits, capacity at scale checkpoints), observability (trace endpoint, dashboards, alerts), cost (line-item per-student projection at 100 / 1k / 5k / 10k tiers). Plans for 1,000 users today with explicit upgrade checkpoints at 5,000 and 10,000.
supersedes: nothing
superseded_by: nothing — this is the canonical operational design
informs: D9 (initial sizing applied), D17 (operational dashboards built), every implementation deliverable (cost and observability guidelines apply)
implemented_by: D9 (initial sizing + trace endpoint), D17 (full operational dashboards), with continuous tuning post-launch
depends_on: every prior pass — this layer wraps them all operationally. Specific dependencies: Pass 3b §9 (trace endpoint sketch), Pass 3f (cost ceilings; cost dashboards consume that data), Pass 3g (safety incidents need monitoring), Pass 3h (closed-loop measurement data feeds dashboards)
---

# Pass 3i — Scale + Observability + Cost Model

> Earlier passes built the architecture. This one makes it run. Three intertwined concerns: will the system actually carry the load, can we see what it's doing, and can we afford to operate it. Answers each at three scale tiers — 100 / 1,000 / 5,000-10,000 — with the implementation built for 1,000 and the upgrade paths documented.

> Read alongside: Pass 3b §9 (the trace endpoint and dashboards this pass concretizes), Pass 3f §H (calibration metrics this pass turns into dashboards), Pass 3h §D (closed-loop measurement this pass surfaces operationally).

---

## Section A — The Scale Tiers

Three explicit tiers. Each has different infrastructure shape. Designing with all three in mind from day one prevents engineering cul-de-sacs.

### A.1 Tier 1 — Up to 1,000 students (the v1 build target)

Topology: single application server, single database, single Redis, single Celery worker host. Vertical-scaling-first.

Properties:
- One Postgres instance (managed: Neon, Supabase, or RDS)
- One Redis instance (managed: Upstash, AWS ElastiCache, or self-hosted)
- One application host (FastAPI uvicorn workers + Celery workers can share the host)
- One MCP server set (YouTube, Email, optional Sandbox); colocated with app
- Single region

Daily traffic: ~5,000 student-initiated agent calls + ~2,000 proactive/scheduled calls + ~50 webhook calls = ~7,000 agent invocations/day.

### A.2 Tier 2 — 5,000 students (first scale checkpoint)

Topology: separate application and Celery hosts, vertically larger DB, Postgres read replica for analytics, Redis sized larger.

Changes from Tier 1:
- Application host and Celery worker host become separate machines
- Postgres gets a read replica for analytics queries (the trace endpoint reads from replica)
- Redis size grows to 8 GB
- MCP servers move to dedicated host(s)
- Still single region

Daily traffic: ~30,000 agent calls/day.

### A.3 Tier 3 — 10,000 students (second scale checkpoint)

Topology: horizontal application scaling, multiple Celery worker hosts segmented by queue, Postgres with connection pooler (PgBouncer), Redis cluster.

Changes from Tier 2:
- Multiple FastAPI hosts behind a load balancer
- Celery workers split across hosts by queue type (safety / proactive / content / default)
- PgBouncer in front of Postgres for connection pooling at scale
- Redis cluster (or larger managed instance with replication)
- Consideration of multi-region if user geography warrants

Daily traffic: ~70,000 agent calls/day.

### A.4 Where AICareerOS lives today

Pre-launch, no paying users. Tier 1 build is right-sized — anything more is premature. Pass 3i specifies Tier 1 implementation with **named, deferred** upgrades for Tiers 2 and 3.

---

## Section B — Database Sizing And Connection Pools

### B.1 Postgres at Tier 1

**Instance size:** managed Postgres at ~2 vCPU / 8 GB RAM / 50 GB storage. Sufficient headroom for the seeded curriculum graph (<1 GB), `agent_actions` growth (~5 GB/year at 1k users), and audit tables.

**Connection budget:**
- Postgres at this size offers ~100 connection slots
- Reserve 20 for ad-hoc admin / migration / replication
- Application gets 80 connection slots

**Connection pool sizing per worker process:**
```
Total app slots:        80
FastAPI workers:        4 processes
Celery workers:         4 processes (split across queues; see §D)
Total worker procs:     8

Pool size per process:  10  (8 procs × 10 = 80, exactly the budget)
Max overflow:           5
Pool recycle (sec):     1800
```

The 10-slot pool per process is generous for a single process's concurrency. With max_overflow=5, transient bursts get 15 effective connections per process.

**Why these numbers:** the standard Postgres connection-pool formula is `(2 × CPU_cores) + effective_spindle_count`. Managed Postgres at this tier has ~4 effective cores from our perspective; that suggests ~10 connections per process. Confirmed by the 8 × 10 = 80 budget allocation.

### B.2 Postgres at Tier 2 (5k students)

**Changes:**
- Bump instance to 4 vCPU / 16 GB RAM
- Connection budget increases to ~200 slots
- Pool size per process stays 10, but worker count grows to 12 procs total
- **Add read replica** specifically for analytics, trace endpoint, and dashboard queries
- Application code uses a `read_only_session()` helper that routes to the replica

**Why a read replica at 5k:** the trace endpoint queries (joining `agent_actions`, `agent_call_chain`, `agent_tool_calls`, `agent_memory`) become heavy enough to compete with transactional writes. Routing reads off the primary keeps writes responsive.

### B.3 Postgres at Tier 3 (10k students)

**Changes:**
- Introduce **PgBouncer** in front of primary in transaction-pooling mode
- Application connects to PgBouncer; PgBouncer maintains a smaller pool to Postgres
- Removes the worker-process-count bottleneck (each app process can have higher pool sizes against PgBouncer)
- Read replica stays; consider second replica for redundancy

PgBouncer adds operational complexity (one more service to monitor, occasional connection-state surprises with prepared statements) but unlocks horizontal app scaling.

### B.4 Critical Postgres tuning

Settings that matter at every tier (set in the managed DB config or via migration `0060_postgres_tuning.py` for self-hosted):

```
shared_buffers              = 25% of RAM
effective_cache_size        = 75% of RAM
work_mem                    = 16MB           # per-operation; tune up if complex queries spill
maintenance_work_mem        = 256MB          # for index builds, vacuum
checkpoint_completion_target = 0.9
random_page_cost            = 1.1            # SSD storage
default_statistics_target   = 100            # default; bump to 500 for skewed tables (agent_actions)
log_min_duration_statement  = 500            # log slow queries; key for ongoing optimization
```

`agent_actions` should have `default_statistics_target = 500` set per-table because its query patterns are skewed (some students have orders of magnitude more rows than others).

### B.5 Indexes that matter

The schema has been adding indexes per pass. Consolidated checklist for Tier 1:

```sql
-- Already exist from D1 / prior passes:
-- agent_actions (student_id, created_at)
-- agent_actions (request_id)
-- agent_call_chain (request_id, parent_action_id)
-- agent_memory HNSW on embedding
-- course_entitlements (user_id, revoked_at)
-- mv_student_daily_cost (user_id, day_utc)

-- Additional indexes Pass 3i requires:
CREATE INDEX idx_agent_actions_supervisor_decline
    ON agent_actions (created_at)
    WHERE agent_name = 'supervisor' AND output_data->>'decline_reason' IS NOT NULL;
-- Used for the decline-rate dashboard

CREATE INDEX idx_agent_actions_critic_score
    ON agent_actions (agent_name, created_at)
    WHERE output_data->>'critic_score' IS NOT NULL;
-- Used for routing-quality regression detection

CREATE INDEX idx_safety_incidents_severity_recent
    ON safety_incidents (severity, occurred_at DESC)
    WHERE severity IN ('high', 'critical');
-- Used for safety incident dashboards

CREATE INDEX idx_nudge_records_recent
    ON nudge_records (sent_at DESC, channel, severity_basis);
-- Used for nudge effectiveness dashboards
```

Index review is part of every implementation deliverable's review checklist. New tables ship with indexes; existing tables get index additions when query patterns change.

---

## Section C — Redis Sizing And Topology

### C.1 Redis at Tier 1

**Instance size:** 2 GB managed Redis with persistence (AOF or RDB).

**Memory budget breakdown:**
- Conversation thread cache: ~200 MB at 1k students × 5 KB per conversation × ~10 conversations/student
- `student_snapshot_service` cache (5-min TTL): ~50 MB at 1k students × ~50 KB snapshot
- EscalationLimiter state (Track 2): ~20 MB
- `mv_student_daily_cost` derived caches: ~10 MB
- General application cache (rate limits, idempotency keys, session): ~100 MB
- Celery broker queue depth: ~50 MB headroom
- **Total budget:** ~430 MB used, 1.5 GB headroom

The headroom matters because Redis usage spikes during incidents (e.g., a Postgres slowdown causes more cache writes as agents work around it).

**Eviction policy:** `allkeys-lru` for the application Redis. Caches that absolutely must not evict (EscalationLimiter state) use a separate logical DB or explicit TTLs that survive eviction.

**Persistence:** AOF with `everysec` fsync. Redis as cache can survive data loss; Redis as authoritative store (EscalationLimiter, idempotency) cannot. The hybrid usage means we err toward durability.

### C.2 Redis at Tier 2 (5k students)

**Changes:**
- Bump to 8 GB
- Consider splitting into two Redis instances:
  - `redis-cache`: pure cache, can lose data on restart, larger memory
  - `redis-state`: durable state (limiter, idempotency, distributed locks), smaller memory but durable

The split reduces blast radius — a cache stampede doesn't compete with state operations.

### C.3 Redis at Tier 3 (10k students)

**Changes:**
- Move to Redis cluster (managed) or larger replicated instance
- Sentinel-based HA for the state instance
- Cache instance can stay single-node since cache loss is recoverable

### C.4 Redis usage discipline

Rules enforced in code review:

- **TTLs are mandatory.** Every Redis write specifies a TTL. Default 1 hour; explicit override only when justified.
- **Keys are namespaced.** `aco:cache:snapshot:{user_id}`, `aco:state:limiter:{agent_name}`, etc. Makes tuning and debugging tractable.
- **No large blobs.** Anything over 100 KB goes to Postgres or object storage; Redis is for fast, small data.
- **No SCAN in hot paths.** Use known keys directly; SCAN is for ops/debugging only.

A small `RedisHelper` class (deferred to D17 as a cleanup item) wraps the client and enforces these rules.

---

## Section D — Worker Topology

### D.1 FastAPI workers at Tier 1

**Configuration:** 4 uvicorn workers per host, single host.

```python
# launch (pseudo)
uvicorn app.main:app --workers 4 --host 0.0.0.0 --port 8000 \
    --backlog 2048 --timeout-keep-alive 75
```

**Why 4 workers:** at typical 2-4 CPU app hosts, 4 uvicorn workers saturate the CPU without excessive context switching. Each worker handles ~25 concurrent requests via async, so total concurrency is ~100 in-flight requests. At 7k requests/day average, in-flight is far below 100.

**Memory per worker:** ~750 MB Presidio + 100 MB application + 50 MB caches = ~900 MB per worker. Total app memory: ~3.6 GB. Comfortable on 8 GB host.

### D.2 Celery workers at Tier 1

**Queues:**
- `celery_safety`: latency-sensitive safety scans, concurrency 4
- `celery_default`: default for most tasks, concurrency 8
- `celery_proactive`: low-priority proactive runs, concurrency 4
- `celery_content`: very-low-priority content ingestion, concurrency 2
- `celery_critical`: high-priority short tasks (notifications, status updates), concurrency 4

**Total Celery worker concurrency:** 22 across queues. Implemented as a single Celery worker process with prefetch_multiplier=1 routing to queues, OR multiple worker processes each pinned to a queue (cleaner separation, slightly more resource overhead).

For Tier 1: **one Celery worker process per queue type** (5 processes total) for clarity. Each process handles its declared queue with appropriate concurrency.

```python
# Suggested launch commands
celery -A app.celery worker -Q celery_safety -n safety@%h -c 4
celery -A app.celery worker -Q celery_default -n default@%h -c 8
celery -A app.celery worker -Q celery_proactive -n proactive@%h -c 4
celery -A app.celery worker -Q celery_content -n content@%h -c 2
celery -A app.celery worker -Q celery_critical -n critical@%h -c 4
```

**Beat scheduler:** one celery-beat process for cron-driven tasks (daily interrupt_agent run, mv_student_daily_cost refresh, weekly progress_report dispatch, etc.).

### D.3 Why the queue split matters

A single queue means a long-running content_ingestion task can block latency-sensitive safety scans. Separation prevents this.

The proactive queue's low priority means daily nudge dispatch doesn't compete with student-facing requests. If the system is under load, proactive runs can wait; student requests cannot.

### D.4 Worker counts at scale

| Tier | FastAPI workers | Celery total concurrency | Hosts |
|---|---|---|---|
| 1 (1k users) | 4 | 22 | 1 |
| 2 (5k users) | 8 | 40 | 2 (app + workers separate) |
| 3 (10k users) | 16 (across hosts) | 80 (across hosts) | 3+ (load-balanced app, multi-host workers) |

The Tier 3 transition is where the architecture genuinely changes — you can't keep growing one machine. PgBouncer (B.3) and load balancer (in front of FastAPI) become required.

---

## Section E — LLM Rate Limits And Queueing

### E.1 Anthropic API rate limits

Anthropic's published rate limits scale with usage tier; for an active production account:

- **Sonnet 4.6:** ~50 requests/minute, ~80,000 input tokens/minute (typical sustained limits; check current docs at https://docs.claude.com)
- **Haiku 4.5:** ~50 requests/minute, ~100,000 input tokens/minute

These limits apply across **all** AICareerOS-issued requests. At 1k users, peak hour traffic is ~5,000 calls/24 hr / 6 active hours ≈ 14 calls/minute, well within limits.

At Tier 2 (5k users): peak ~70 calls/minute. Approaches Sonnet's per-minute limit during peaks. Mitigation: Haiku for the Supervisor's classifier path, batching where possible.

At Tier 3 (10k users): peak ~140 calls/minute. Exceeds default per-minute. Either request limit increase from Anthropic or distribute load via the Anthropic Batch API (60% discount; latency-tolerant flows like proactive nudges).

### E.2 Rate-limit handling

When the Anthropic API returns 429 (rate limited):

1. **Retry with exponential backoff.** Existing pattern from D5; respect the `retry-after` header.
2. **Failover to Haiku for non-critical Sonnet calls.** Specifically, Critic samples and the Layer 2 prompt-injection classifier are already Haiku; the Supervisor and specialists fall back to Haiku only as a last resort with degraded-quality flag.
3. **Queue with backpressure.** If the rate-limit retry budget is exhausted, requests queue in Celery with a `rate_limited_at` timestamp; the orchestrator returns a graceful 503 with retry-after to the client.

### E.3 Cost-aware routing

The Supervisor's prompt is already aware of `typical_cost_inr` per agent capability. At budget-tight moments (student approaching daily ceiling, platform approaching projected monthly budget), the Supervisor can be configured to prefer cheaper agents.

In v1, this preference is **off** (no dynamic cost-aware routing). The infrastructure exists (capability has `typical_cost_inr`); turning it on is a config flip when post-launch data shows it's needed.

---

## Section F — The Trace Endpoint

The keystone observability surface. Promised by Pass 3b §9.2.

### F.1 Endpoint specification

```
GET /api/v1/admin/students/{student_id}/journey
  ?from=<ISO-8601 timestamp>
  &to=<ISO-8601 timestamp>
  &include=actions,chains,memory,escalations,safety,nudges  (default: all)
  &limit=<int>  (default: 200, max: 1000)
```

Returns a structured JSON timeline reconstructable into a UI view:

```python
class StudentJourney(BaseModel):
    student_id: UUID
    window_from: datetime
    window_to: datetime
    actions: list[ActionEntry]            # agent invocations
    chains: list[ChainEntry]              # call chains (Supervisor → specialist sequences)
    memory_writes: list[MemoryEntry]      # significant memory writes in window
    escalations: list[EscalationEntry]
    safety_incidents: list[SafetyEntry]
    nudges: list[NudgeEntry]
    summary: JourneySummary               # rolled-up stats: total cost, agents touched, etc.
```

The frontend (when ready) renders this as a vertical timeline. For now, the backend produces it; admin-facing rendering is a small later addition.

### F.2 Implementation strategy

**Tier 1 (1k users):** the endpoint queries `agent_actions`, `agent_call_chain`, `agent_memory`, `agent_escalations`, `safety_incidents`, `nudge_records` directly with appropriate joins.

For typical 7-day windows, ~10-50 actions per student, query latency is <500ms.

**Tier 2 (5k users):** queries route to the read replica. Trace queries on hot students might join across millions of rows; the replica isolates this from primary write performance.

**Tier 3 (10k users):** consider denormalized journey table refreshed periodically, OR adopt an OLAP database (Clickhouse, DuckDB) for analytics. The trace endpoint is a read-mostly analytics workload; OLAP fits naturally. Deferred until needed.

### F.3 Per-agent recent decisions

Companion endpoint from Pass 3b §9.2:

```
GET /api/v1/admin/agents/{agent_name}/recent-decisions
  ?limit=<int>  (default: 50, max: 200)
  &since=<ISO-8601 timestamp>  (default: 24h ago)
```

Returns recent decisions/invocations of a specific agent. Used by ops to investigate "why is X agent getting hit so much?" or "what's the routing-quality trend for the Supervisor."

---

## Section G — Operational Dashboards

The SQL queries from Pass 3b §9.3 turned into actual dashboard specs.

### G.1 The dashboard stack

**PostHog** for product/event metrics (already in use):
- Event funnel: signup → placement_quiz → first_paid_session → first_capstone_submission
- Per-event properties: agent_name, decline_reason, channel, severity_basis
- A/B test analysis (the 5% nudge hold-out from Pass 3h)
- Free-tier conversion rate

**Grafana + Prometheus** for infrastructure metrics:
- CPU/memory/disk per host
- Postgres query latency (p50, p95, p99)
- Redis memory usage and hit rate
- Celery queue depth per queue
- HTTP request latency by endpoint
- LLM API call volume and latency

**Sentry** for errors and exceptions:
- Stack traces with context
- Error rate trends
- Release tracking (errors per deployment)

### G.2 The "single pane of glass" dashboard

The dashboard you check first thing in the morning. Single Grafana panel showing:

| Metric | Threshold for alarm |
|---|---|
| Total agent calls in last hour | < 50% of expected baseline (drop) or > 200% (spike) |
| Supervisor decline rate | > 5% |
| Critic mean score across agents | < 0.7 |
| Safety incidents in last hour | > 5 of severity high+ |
| Cost-ceiling-hit count in last hour | > 20 |
| LLM API error rate | > 1% |
| Postgres p95 query latency | > 500ms |
| Redis memory used | > 80% |
| Celery queue depths | safety>10, default>50, content>200 |
| Webhook delivery failure rate | > 2% |

Each metric has an explicit threshold. Crossing it lights a red square on the dashboard. Multiple red squares is escalation territory.

### G.3 Per-domain dashboards

**Supervisor health:**
- Decisions per hour (single, chain, decline, escalate, ask_clarification)
- Routing distribution: which agents are being dispatched, in what proportions
- Average chain length and trends
- Decision latency p50/p95/p99
- Critic score distribution per primary_intent
- Failure-class distribution (the five classes from Pass 3b §7.1)

**Safety health (from Pass 3g):**
- Incidents per category per day
- False-positive rate (admin-reviewed `false_positive` outcomes / total reviewed)
- Pattern bank coverage (which patterns fire, which don't)
- Layer 2 LLM classifier rate (how often is Layer 1 inconclusive)
- Per-detector latency

**Cost health (from Pass 3f):**
- Cost per student per day (P50, P95, P99)
- Cost ceiling hits per day, broken down by agent
- Free-tier vs. standard cost distribution
- Total platform spend trend

**Engagement health (from Pass 3h):**
- Nudges sent per day, by channel, by severity_basis
- Response rates per channel/tone/severity combination
- Hold-out group cohort comparison
- Pause-link click rate
- Plan adherence trend

**Curriculum graph health (from Pass 3e):**
- Concept coverage (concepts with canonical resources / total concepts)
- Candidate review queue depth
- Query latency per pattern
- Most-queried concepts (signal of student interests)

### G.4 Dashboard build sequencing

Dashboards aren't all built at once. Sequence:

- **D9** ships the trace endpoint and the basic Supervisor and cost dashboards (the operational essentials)
- **D17** ships the full dashboard set including engagement, safety, and curriculum graph dashboards
- Post-launch, dashboards evolve based on which questions ops actually ask

Most dashboards are SQL queries against the schema we've designed. Building them is mechanical once the data exists.

---

## Section H — Alerting And Runbooks

### H.1 Alert philosophy

Three rules:

1. **Every alert is actionable.** No "FYI" alerts. If there's nothing the on-call should do, it goes in the dashboard, not as an alert.
2. **Alerts have runbooks.** Every alert has a linked runbook explaining what to investigate, what to fix, and when to escalate further.
3. **Alert fatigue is treated as a bug.** A noisy alert is fixed at the source (better threshold, better signal, or removed).

### H.2 Alert channels

Tier 1 (pre-multi-operator): single Slack/Discord webhook. All alerts arrive in one channel.

Tier 2+: on-call rotation with PagerDuty or similar. Severity-based routing.

### H.3 Critical alerts (page on-call)

- LLM API error rate > 5% sustained 5 minutes
- Postgres unavailable (any 503 from primary)
- Safety: more than 10 `critical` severity incidents in 5 minutes (signals coordinated attack)
- Cost: platform daily spend exceeds 150% of expected by midday
- Webhook delivery failure rate > 20% sustained 10 minutes

### H.4 Warning alerts (notify, don't page)

- Supervisor decline rate > 10% sustained 30 minutes
- Critic mean score drop > 0.1 absolute over 24h
- Redis memory > 85%
- Celery `safety` queue depth > 20 sustained 5 minutes
- Pattern bank stale (no updates in 90 days)

### H.5 Information alerts (dashboard only, no notification)

- Daily cost-ceiling hit count
- Free-tier expiry events
- Capability registration changes

### H.6 Runbook structure

Every runbook follows this template at `docs/runbooks/{alert_name}.md`:

```
# Alert: <name>

## Symptom
<what the alert looks like; sample message>

## Likely causes
1. <most common cause>
2. <next most common>
3. <rarer but important>

## Investigation
1. Check dashboard X for Y
2. Query Z to see W
3. Inspect logs for pattern P

## Mitigation
- For cause 1: <action>
- For cause 2: <action>
- For cause 3: <escalate to <person/team>>

## Prevention follow-ups
<long-term work that would prevent recurrence>
```

D17 ships starter runbooks for the five most likely incidents:
- Supervisor LLM degradation
- Curriculum graph query saturation
- Safety incident spike
- Cost-ceiling-hit surge
- Webhook subscriber gap (the PG-1 class of failure)

---

## Section I — The Cost Model

Honest line-item accounting at three scale tiers.

### I.1 Cost categories

1. **LLM API calls** — Anthropic-billed per token for Sonnet/Haiku
2. **Embedding calls** — Voyage-3 per token (used by D2 + curriculum graph + memory)
3. **Sandbox execution** — E2B per-execution (until/if we self-host)
4. **MCP server hosting** — fixed cost for our YouTube/Email/Sandbox-wrapper MCP infra
5. **Database** — managed Postgres tier
6. **Redis** — managed Redis tier
7. **Application hosting** — app servers + Celery workers
8. **Email sending** — transactional email service (Postmark, Resend, etc.)
9. **Object storage** — for any uploaded files (resumes, capstone artifacts)
10. **Monitoring and observability** — PostHog, Sentry, Grafana Cloud

### I.2 Per-student-per-day expected usage (Tier 1)

Modeling a typical paid student at moderate engagement:

- **2 student-initiated agent calls/day** (chat sessions, code review requests)
- **1 proactive interaction/day** (interrupt_agent decision; most days no nudge sent)
- **Agent calls average 1.5 LLM calls each** (Supervisor + 1 specialist average)

Daily LLM volume per student: ~3-4 LLM calls.

Per call mix:
- ~70% Sonnet (specialists, Supervisor proper)
- ~30% Haiku (classifier paths, Critic samples, prompt-injection Layer 2)

### I.3 Tier 1 monthly cost projection (1,000 paying students)

```
LLM API (Sonnet):
  3 calls/day × 1k students × 70% × 3 INR avg/call × 30 days
  = 189,000 INR/month

LLM API (Haiku):
  3 calls/day × 1k students × 30% × 0.5 INR avg/call × 30 days
  = 13,500 INR/month

Embeddings (Voyage-3):
  ~5 embeddings/student/day × 1k × 0.05 INR each × 30 days
  = 7,500 INR/month

Sandbox (E2B):
  ~0.3 sandbox runs/student/day × 1k × 5 INR/run × 30 days
  = 45,000 INR/month

MCP server hosting:
  ~$50 USD/month (small managed instance) ≈ 4,200 INR/month

Postgres (managed, 2 vCPU/8 GB):
  ~$80 USD/month ≈ 6,700 INR/month

Redis (managed, 2 GB):
  ~$30 USD/month ≈ 2,500 INR/month

Application hosting (single host, 4 vCPU/16 GB):
  ~$100 USD/month ≈ 8,400 INR/month

Email sending:
  ~3 emails/student/month × 1k × 0.5 INR each
  = 1,500 INR/month

Object storage:
  ~$20 USD/month ≈ 1,700 INR/month

Monitoring (PostHog free tier + Sentry developer + Grafana Cloud free):
  ~$50 USD/month ≈ 4,200 INR/month

──────────────────────────────────────
TOTAL MONTHLY COST (1k students):  ~283,200 INR/month  (~$3,400 USD)
PER STUDENT PER MONTH:             ~283 INR  (~$3.40 USD)
PER STUDENT PER DAY:               ~9.40 INR
```

### I.4 Tier 1 cost vs. revenue

The 50 INR/day per-student cost ceiling from Pass 3f is the *ceiling*. Average usage at 9-12 INR/day means the 50 INR ceiling protects you from 5x cost spikes per student, with real costs landing around 20% of the ceiling.

This is the right calibration. Ceiling tight enough to stop runaway abuse, generous enough that real students rarely hit it.

For revenue: at any course price > 1,000 INR, gross margin per student is positive even at heavy usage. Below 1,000 INR, the platform doesn't make sense — but you've indicated courses are priced higher than that.

### I.5 Tier 2 monthly projection (5,000 students)

Most line items scale linearly with student count. Some don't:

```
LLM (Sonnet + Haiku):  ~1,015,000 INR/month (linear)
Embeddings:             ~37,500 INR/month (linear)
Sandbox:                ~225,000 INR/month (linear)
MCP hosting:            ~16,800 INR/month (4x for dedicated host)
Postgres (Tier 2):      ~25,000 INR/month (4 vCPU/16 GB + replica)
Redis (Tier 2):         ~10,000 INR/month (8 GB)
Application + workers:  ~25,000 INR/month (separate hosts)
Email:                  ~7,500 INR/month (linear)
Storage:                ~8,500 INR/month
Monitoring:             ~12,000 INR/month (paid tiers needed)

TOTAL: ~1,382,000 INR/month  (~$16,600 USD)
PER STUDENT PER MONTH:  ~276 INR  (slight economy of scale)
```

### I.6 Tier 3 monthly projection (10,000 students)

```
LLM (Sonnet + Haiku):  ~2,030,000 INR/month
Embeddings:             ~75,000 INR/month
Sandbox:                ~450,000 INR/month  (consider self-hosted at this scale)
MCP hosting:            ~33,600 INR/month
Postgres (Tier 3):      ~75,000 INR/month (PgBouncer + replica + larger primary)
Redis (Tier 3):         ~25,000 INR/month (cluster)
Application + workers:  ~80,000 INR/month (multi-host)
Email:                  ~15,000 INR/month
Storage:                ~17,000 INR/month
Monitoring:             ~25,000 INR/month
Misc (load balancer, logging, secondary region considerations):  ~15,000 INR/month

TOTAL: ~2,840,600 INR/month  (~$34,200 USD)
PER STUDENT PER MONTH:  ~284 INR
```

The slight cost-per-student creep at Tier 3 reflects fixed overhead (LB, monitoring tier upgrades) amortizing over a larger base. Still well within margin for a platform pricing courses in thousands of INR.

### I.7 What could blow up

Items where actual cost could be 2-5x the projection if behavior diverges:

1. **Sandbox execution.** If practice_curator or senior_engineer prompts students into more sandbox runs than expected. Mitigation: per-student daily sandbox quota (separate from cost ceiling).

2. **Curriculum graph narrative queries.** Pass 3e §G.3 estimated ~50k INR/month. If natural-language queries become heavily used (Learning Coach calling them on every interaction), this could 3x. Mitigation: cache narrative results aggressively; rate-limit per student.

3. **Content ingestion.** If admin imports a large content backlog (entire YouTube playlists, GitHub orgs), one-time costs spike. Mitigation: ingestion is admin-triggered, so admin has visibility; budget allocation per ingestion campaign.

4. **Safety LLM classifier (Layer 2).** Currently estimated ~150 INR/day. If pattern bank quality degrades (more ambiguous inputs), Layer 2 fires more often. Mitigation: pattern bank version updates as part of regular release cycle.

Each is monitored via dashboards in §G.

---

## Section J — Capacity Checkpoints

What changes (and when) as you grow.

### J.1 Checkpoint at 2,000 active students

Trigger: sustained > 2,000 monthly-active-user count.

Required changes:
- Verify current Tier 1 sizing isn't approaching limits (CPU < 70%, DB connections < 70%, Redis memory < 70%)
- If any near limit: scale that resource vertically
- No architectural change yet

### J.2 Checkpoint at 5,000 active students

Trigger: > 5,000 MAU OR Postgres p95 query latency > 300ms sustained.

Required changes:
- **Split application and Celery hosts** (already designed; just deploy)
- **Add Postgres read replica** for analytics
- **Bump Redis to 8 GB**
- **Move MCP servers to dedicated host(s)**
- Update connection pool sizing (B.2 numbers)

Estimated effort: 2-3 days of operational work, no application code changes.

### J.3 Checkpoint at 10,000 active students

Trigger: > 10,000 MAU OR application CPU > 80% sustained OR Postgres connection slot saturation.

Required changes:
- **Introduce PgBouncer** in front of Postgres
- **Multiple FastAPI hosts** behind a load balancer
- **Multiple Celery worker hosts** segmented by queue
- **Redis cluster** or larger replicated instance
- **Possibly Anthropic Batch API** for proactive flows
- **Possibly OLAP database** for analytics if trace endpoint becomes slow

Estimated effort: 1-2 weeks of operational work, ~100 LOC of application changes (PgBouncer-aware connection handling, mostly disabling prepared statements where they break with transaction-pooling mode).

### J.4 What's NOT in the plan

Sub-second global latency, multi-region replication, edge deployment, custom database storage tiers — these are post-Tier-3 concerns that change the architecture more deeply than this pass covers. If AICareerOS hits 50,000+ users, that's a different planning exercise.

---

## Section K — Implementation Across Deliverables

### K.1 D9 (Supervisor + entitlement + safety)

- Apply initial connection pool sizes (Tier 1)
- Configure Redis with namespace conventions
- Set up Celery queues with the 5-queue split
- Build the trace endpoint (basic version — direct queries, no replica routing)
- Wire PostHog event taxonomy from Pass 3b §9.4
- Set up Sentry integration
- Initial Grafana dashboards: Supervisor health, basic system metrics

### K.2 D17 (final cleanup)

- Build the full dashboard set (engagement, safety, curriculum graph)
- Ship runbooks for the five primary incidents
- Implement the `RedisHelper` discipline class
- Performance baseline and regression test infrastructure
- Document the capacity checkpoint procedures

### K.3 Continuous (post-launch)

- Weekly review of dashboard signals
- Monthly cost reconciliation against projections
- Quarterly capacity check (are we approaching the next checkpoint?)
- Pattern bank, runbook, and dashboard evolution as needs surface

---

## Section L — What This Pass Earns

When the operational layer is in place:

**For students:**
- Predictable response times (rate limits, queue priorities, sized resources)
- Service stays up under load
- Their journey is debuggable when something goes wrong

**For the operator:**
- Single-pane-of-glass dashboard for system health
- Cost is observable and controllable at every tier
- Capacity checkpoints have explicit triggers and explicit fixes
- Incidents have runbooks; you don't reason from scratch under pressure
- Scale isn't a leap of faith — it's a documented progression

**For future contributors:**
- Adding a feature includes "how is this monitored?"
- Cost impact of features is visible in projections
- Adding an alert requires adding a runbook (forced discipline)
- Capacity questions have answers, not vibes

This is the layer that makes AICareerOS *operable*, not just *built*.

---

## Section M — What's Deferred

- **Multi-region** — out of scope for any of the three tiers in this pass
- **Custom database sharding** — managed Postgres handles all three tiers
- **OLAP database for analytics** — flagged as a Tier 3 consideration; not built
- **Self-hosted code sandbox** — Tier 3 consideration once E2B costs are unfavorable
- **On-call rotation** — Tier 2+ concern
- **Synthetic monitoring (uptime probes from external regions)** — basic uptime check in v1 is enough

---

## What's NOT covered by Pass 3i

- **Naming sweep + cleanup** → Pass 3j (next)
- **Implementation roadmap synthesis** → Pass 3k/3l (final)
