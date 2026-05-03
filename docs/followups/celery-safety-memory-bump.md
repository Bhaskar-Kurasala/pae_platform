# Celery worker memory bump for the safety primitive

**Status:** Open — **launch-blocker for D16** (interrupt_agent + proactive runs).
**Created:** 2026-05-02 (D9 Checkpoint 1 wrap-up).
**Blocked by:** D9 Checkpoint 3 (safety primitive wiring into
`AgenticBaseAgent.run()`).

## The problem

Once Checkpoint 3 lands the SafetyGate inside `AgenticBaseAgent.run()`,
**every** invocation of an agent inside a Celery task loads Microsoft
Presidio + spaCy `en_core_web_lg` into the worker's Python process.
That's ~750 MB resident per process per Pass 3g §H.3.

This is the **same OOM math** that bit the FastAPI app at D9 Checkpoint 1:

```
4 workers × ~750 MB Presidio = ~3 GB safety-only memory
vs. an unprovisioned Celery Fly app at default 512 MB
                                = deterministic OOM on first task
```

The FastAPI side was fixed in D9 Checkpoint 1 (memory_mb 512 → 4096,
gunicorn workers 4 → 1; see fly.toml VM block + backend/Dockerfile CMD
comments). The Celery side has no equivalent fix yet — it currently
runs from `docker-compose` locally and does NOT have its own
production fly.toml. The follow-up referenced at fly.toml line 105-106
("Celery worker + beat run as separate Fly apps... their fly.toml
configs land in a follow-up infra-PR") is where this remediation
must land.

## Why this is a launch-blocker for D16, not just D9

Until Checkpoint 3 wires the safety primitive, Celery workers don't
import Presidio. So D9 itself does not OOM Celery. But:

- D9 Checkpoint 3 wires safety into `AgenticBaseAgent.run()`.
- D9 Checkpoint 4 doesn't deploy production yet, but Celery still
  loads Presidio on every dev `agent.run()` after Checkpoint 3.
- D16 introduces `interrupt_agent` as a `@proactive(cron=...)` agent
  that runs on Celery beat → Celery worker. **That's the moment a
  production Fly Celery app exists and runs agentic code in a
  resource-bounded environment.** If the Fly app lands at 512 MB
  by default, the first scheduled `interrupt_agent` run OOMs.

So: between Checkpoint 3 and D16, the issue stays latent. D16 is the
deploy that surfaces it.

## Three-action remediation (when the per-Celery-app fly.toml lands)

### (a) Bump memory to 4 GB on every Celery Fly app

Mirror the D9 fix on the FastAPI side. Per fly.toml's existing comment
block (around the `[[vm]]` section), the math + reasoning is documented
once and shared across the API + Celery apps:

```toml
[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 4096    # NOT 512 — see API fly.toml [[vm]] block for why
```

This applies to both the worker and the beat scheduler apps. Beat
itself doesn't import agent code, but it shares the image and any
stray import path during boot would still pull spaCy into the process.
Default to 4 GB everywhere; tighten later with real data.

### (b) Cap Celery worker concurrency so workers × Presidio fits the cap

Celery's default worker concurrency is `# of CPUs` (typically 2-4 on
shared-cpu-1x). With Presidio at ~750 MB/process:

| concurrency | Presidio total | OK at memory_mb=4096? |
|---|---|---|
| 1 | 750 MB | Yes — ~70% headroom |
| 2 | 1.5 GB | Yes — ~40% headroom |
| 4 | 3.0 GB | Risky — ~10% headroom |
| 8 | 6.0 GB | OOM |

Recommendation: **start at concurrency=2** for the worker app. Beat
uses concurrency=1 by definition (it's a singleton scheduler).

Wire via `--concurrency=2` flag in the worker's Dockerfile CMD, or
`CELERYD_CONCURRENCY=2` env var, whichever is consistent with the
existing celery startup pattern.

### (c) Eager-load Presidio at worker boot (not lazy on first task)

Lazy-loading would mean the first scheduled `interrupt_agent` run
takes 4-5 seconds longer than subsequent runs (the Pass 3g §H.1
boot-time cost lands on request 1). More importantly, the memory
profile becomes unpredictable — operators see "worker is fine" → "worker
hits 1.4 GB" mid-task with no warning.

Eager-load by importing the safety primitive at Celery worker startup:

```python
# In celery startup signal or a worker-init hook:
from app.agents.primitives.safety import SafetyGate
_GLOBAL_SAFETY_GATE = SafetyGate.default()  # forces Presidio load
```

This makes the memory profile deterministic from the moment the
worker boots, which means the `memory_mb` budget can be calibrated
against a real number, not a worst-case guess.

## Verification checklist (apply when the Celery fly.toml lands)

- [ ] memory_mb = 4096 on both worker and beat apps
- [ ] Worker concurrency capped (default: 2)
- [ ] SafetyGate loaded at worker boot, not lazily
- [ ] Verified worker boot takes ~5 s (Presidio + spaCy load) and
      grace_period in fly.toml is wide enough
- [ ] Verified resident memory ~1.5 GB at idle with concurrency=2
- [ ] Run `interrupt_agent` synthetically against the deployed Celery
      app; confirm no OOM, verify task completes

## Cross-references

- `fly.toml` `[[vm]]` block + Dockerfile CMD comment (D9 Checkpoint 1
  fix on the FastAPI side; same math, same reasoning)
- Pass 3g §H.3 — Presidio per-process memory cost (~750 MB)
- Pass 3i §D — single-worker / I/O-bound rationale
- D9 Checkpoint 1 wrap-up status — measured numbers
  (1.378 GB resident at 1 worker, 4.28 s spaCy load)
- Pass 3h §G.2 — interrupt_agent + proactive cost is platform overhead,
  not student daily ceiling
- D16 deliverable spec — `interrupt_agent` is the first production
  Celery agent that triggers this constraint

## Tag

**Launch-blocker for D16.** Cannot deploy interrupt_agent or any
proactive agent to production Celery without this remediation in
place. Verifiable: any production deploy of D16 onto a default-sized
Celery Fly app will OOM on the first scheduled run.
