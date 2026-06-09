# On-call runbook

PR3/D7 — How we know production is healthy and how on-call gets paged
when it isn't.

This document is the **single source of truth** for the SLO + alert
configuration. None of this lives in code (Healthchecks.io and Sentry
are external services); but every change to thresholds, channels, or
response procedure goes through a PR that updates this file so there's
an audit trail.

---

## TL;DR for on-call

You will get paged via two channels:

| Channel | What it means | Where to look |
|---|---|---|
| **Slack `#pae-alerts`** | Healthchecks.io — the API hasn't responded to its readiness probe in >15 min, or Sentry error rate spiked past the SLO. | Check `https://pae-platform.fly.dev/health/ready` first. If 503, follow the dependency-down procedure below. |
| **Email (oncall@pae.dev)** | Backup channel for everything Slack-paged plus daily backup-success digest. | Inbox is on a 1-day SLA — Slack is the real-time channel. |

---

## D7.1 — Healthchecks.io readiness probe

**What:** Healthchecks.io pings `GET https://pae-platform.fly.dev/health/ready` every 5 minutes from three regions (US-East, EU, Asia). The endpoint is the one we built in PR3/C6.1 — it returns 200 only when DB + Redis are both reachable; otherwise 503 with structured detail naming the failed deps.

**Threshold:** Two consecutive misses = page. Why two: Fly occasionally cycles a machine for an internal restart and a single in-flight check window can drop. Two-miss avoids the false positive that would burn on-call goodwill in the first week.

**Setup (one-time, by the human deploying):**

```bash
# 1. Create a check at https://healthchecks.io/projects/<project>/checks
#    Name: "pae-platform-readiness"
#    Period: 5 minutes
#    Grace: 5 minutes (= "two consecutive misses" effectively)
#    Schedule type: simple
#
# 2. Configure HTTP probing — NOT cron-style "ping-then-fail" (which
#    requires the API to *call* healthchecks.io). We want the inverse:
#    healthchecks calls us. That's the "Web Pings" feature on the
#    pricing page — free up to 20 monitors.
#
# 3. URL: https://pae-platform.fly.dev/health/ready
#    Expected status: 200
#    Expected body contains: "ok"
#
# 4. Integrations:
#    - Slack #pae-alerts (incoming webhook URL)
#    - Email: oncall@pae.dev
#
# 5. Save the check ID to:
#    fly secrets set HEALTHCHECKS_CHECK_ID=<id>
#    (Currently informational only; future enhancement could ping
#    on every successful deploy as a "we just rolled a new
#    revision, expect health to recover within 60s" signal.)
```

**Verification:**

```bash
# Force a paged-state to confirm Slack/email integrations work:
fly machines stop --app pae-platform <machine-id>
# Wait ~10 minutes — check #pae-alerts for the page.
# Then bring it back:
fly machines start --app pae-platform <machine-id>
# After ~10 more minutes the channel should post a "recovered" message.
```

**Cost:** $0 — free tier covers up to 20 monitors with 1-minute resolution.

---

## D7.2 — Sentry error-rate alert

**What:** Sentry emails on-call when the unhandled-error rate exceeds **0.5% of requests** over a rolling **10-minute window**. That threshold means roughly: "5 errors per 1,000 requests sustained for 10 minutes" gets a page.

**Why those specific numbers:**

- **0.5% over 10 min** is significantly above the steady-state error rate we measured in PR2/B4.1 (which was 0.05–0.1% — mostly client-side ApiTimeoutErrors and known 401 → refresh flows). Setting it lower paged on noise; setting it higher missed real incidents.
- The 10-minute window is wide enough that a single bad deploy's tail doesn't page (it self-recovers as users navigate away), but tight enough to catch a sustained backend regression within one on-call rotation slot.

**Setup (one-time, by the human deploying):**

1. Sentry → Project `pae-platform-backend` → **Alerts** → **Create Alert**
2. **Alert type:** "Number of errors" (NOT "issues affected" — we want
   raw error count rate, not unique-issues rate).
3. **When:** "events seen" "is more than" "0.5%" "of total events" "in 10 minutes".
4. **Filter:** `level:error` (skip warnings; warnings include the deprecated_endpoint_called events from PR2/A4.1 which are intentional).
5. **Actions:**
   - Send email to `oncall@pae.dev`
   - Send Slack notification to `#pae-alerts`
6. **Frequency:** "Send notification once per hour while the issue is active". Avoids alert-storm if the same regression is firing on every request.

Repeat steps 1–6 for the **frontend** project (`pae-platform-web`) — same threshold, separate alert. Two separate alerts (not one combined) so the on-call message says "frontend rate climbing" vs "backend rate climbing" rather than just "the rate is up somewhere."

**Cost:** $0 — alerts are included in the Sentry free tier (5k errors/month). If we ever exceed that we'll see the over-quota notice on the Sentry billing page well before alerts get throttled.

---

## Common incidents — runbook

### Symptom: Healthchecks.io page, /health/ready returns 503

1. Check the structured response body: `curl -s https://pae-platform.fly.dev/health/ready | jq`. The body identifies which dep is unreachable (`db.status` or `redis.status` will be `"unreachable"`).
2. **DB down (Neon):** Check status.neon.tech. If Neon is up but our app can't connect, check if a recent migration has held an exclusive lock — `fly logs --app pae-platform | grep "alembic"`. Roll back the migration if needed (`docs/runbooks/restore.md` covers the procedure).
3. **Redis down (Upstash):** Check Upstash console. Redis is non-load-bearing for most flows (chat history is a cache; expiring it just means the user starts a new conversation), but the readiness probe is conservatively strict. If you need to bypass briefly, set `REDIS_URL=` empty and the app degrades gracefully.

### Symptom: Sentry alert spike, /health/ready returns 200

1. Open the Sentry issues board, sort by "events in last 10 min".
2. The top issue's `tags` include `route` and `agent_name` (we set these in PR3/C5.1). That tells you which endpoint regressed.
3. Compare the issue's `release` tag to the most recent deploy SHA (`fly releases list`). If they match, the most recent deploy is the regression — `fly deploy --image <previous-tag>` rolls back without rebuilding.
4. If they don't match, the regression is older and was triggered by something other than a deploy (data shape, third-party API change, etc.). Keep digging.

### Symptom: cost_estimate_inr in PostHog dashboard is climbing

This is the per-LLM-call event we instrumented in PR3/C7.1. The query `SUM(cost_estimate_inr) BY user_id WHERE event = 'llm.call'` over the last 24h is the "who's burning budget" board.

1. Top spender per day in the steady state is ~₹5–₹10 (a heavy student doing 2–3 long tutor sessions). Anything >₹50/day for a single user_id is anomalous.
2. Check the `agent_name` breakdown. If it's `socratic_tutor` heavy, that's normal — Socratic dialogue eats tokens. If it's spaced_repetition or knowledge_graph, something's broken (those agents shouldn't be calling LLMs at all per the C7.1 cost-tracking guarantees).
3. The absolute ₹20-per-message-pair cost-cap circuit breaker (PR2 era) is the failsafe. If it's tripping for a user, they see "I had to stop early — try a more focused question" in the tutor reply.
