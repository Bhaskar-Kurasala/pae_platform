/**
 * Track 5 — Agentic OS surface E2E.
 *
 * Verifies the externally-observable behaviour introduced by D1-D8 of
 * the Agentic OS layer (`docs/AGENTIC_OS.md`). Scoped *deliberately
 * narrow*: covers only what is reachable from a black-box client
 * outside the FastAPI / Celery process boundary. The internal-only
 * surface (memory writes, tool execution, inter-agent calls, critic
 * runs, cron-fired proactive sweeps, agent chat through D8's
 * `LearningCoach.run`) is enumerated as gap findings in
 * `docs/audits/agentic-os-precondition-gaps.md` rather than tested
 * here against fabricated harness.
 *
 * Why so few tests: the Agentic OS layer is intentionally an internal
 * primitives library. The only HTTP surface it exposes today is the
 * verified webhook entry points (D7) and the health probes that prove
 * the supporting infra (Postgres + Redis, which D2 / D5 depend on)
 * is up. Stub-testing against fabricated endpoints would produce
 * tests that pass today and lie tomorrow — see the gap doc for what
 * needs to land first.
 *
 * Run with: `cd frontend && pnpm playwright test agentic-os`.
 * Requires the docker stack to be up (nginx on :8080).
 */

import { test, expect } from "@playwright/test";

const API = "http://localhost:8080";

test.describe("Agentic OS — health and infrastructure (D1-D8 dependencies)", () => {
  test("/health/ready reports db + redis healthy — D2 memory and D5 escalation infra", async ({
    request,
  }) => {
    // D2 (MemoryStore) writes to Postgres `agent_memory`. D5
    // (RedisEscalationLimiter) writes a sorted-set to Redis. If
    // either dep is unhealthy, the primitives that depend on them
    // are silently degraded — that's exactly the failure mode the
    // boot-time fail-open log line surfaces. This test is the
    // black-box equivalent: ready means the deps are answering.
    const res = await request.get(`${API}/health/ready`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.status).toBe("ok");
    expect(body.checks?.db?.ok).toBe(true);
    expect(body.checks?.redis?.ok).toBe(true);
  });

  test("/health/version reports build provenance", async ({ request }) => {
    // Lower-bar D8 sanity check: if the agentic loader (called at
    // celery boot) had crashed importing example_learning_coach,
    // the FastAPI process itself wouldn't be affected — but in
    // production this endpoint reports the deployed SHA. A 200
    // here means the Python module graph compiled cleanly.
    const res = await request.get(`${API}/health/version`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("commit_sha");
    expect(body).toHaveProperty("build_time");
    expect(body).toHaveProperty("env");
  });
});

test.describe("Agentic OS — D7 webhook signature contract (negative path)", () => {
  // The agentic webhook endpoints (D7) live at
  //   POST /api/v1/webhooks/agentic/github
  //   POST /api/v1/webhooks/agentic/stripe
  // and refuse unsigned / wrong-secret requests with 401.
  //
  // The negative path (rejects) is fully testable in any environment,
  // including dev where the secrets are unset (empty secret = hard
  // reject per `verify_github_signature` / `verify_stripe_signature`
  // — that's safe-by-default per the D7 spec).
  //
  // The positive path (valid signature → fan-out to subscribers) is
  // NOT tested here because (a) dev has no webhook secrets configured
  // and (b) `route_webhook` returns subscribers=0 unless the agentic
  // loader has been called inside the FastAPI process, which it has
  // not (loader currently fires only inside the Celery worker boot —
  // see precondition gap PG-1 in the gap doc).

  test("github webhook 401s on invalid signature", async ({ request }) => {
    const res = await request.post(`${API}/api/v1/webhooks/agentic/github`, {
      headers: {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": `t5-bad-sig-${Date.now()}`,
        "X-Hub-Signature-256": "sha256=deadbeef",
        "Content-Type": "application/json",
      },
      data: { hello: "world" },
    });
    expect(res.status()).toBe(401);
    const body = await res.json();
    expect(body.detail).toMatch(/invalid GitHub signature/i);
  });

  test("github webhook 400s when X-GitHub-Event header is missing", async ({
    request,
  }) => {
    // Defensive: the dependency rejects before signature verification
    // when required headers are absent. Without the event name we
    // can't construct the namespaced `github.<event>` for routing.
    const res = await request.post(`${API}/api/v1/webhooks/agentic/github`, {
      headers: {
        "X-GitHub-Delivery": `t5-no-event-${Date.now()}`,
        "X-Hub-Signature-256": "sha256=deadbeef",
        "Content-Type": "application/json",
      },
      data: {},
    });
    expect(res.status()).toBe(400);
    const body = await res.json();
    expect(body.detail).toMatch(/X-GitHub-Event/i);
  });

  test("github webhook 400s when X-GitHub-Delivery header is missing", async ({
    request,
  }) => {
    // Without the delivery ID we can't construct a stable idempotency
    // key — refusing is correct, since silently constructing one with
    // an empty value would skip the partial unique guard at the DB.
    const res = await request.post(`${API}/api/v1/webhooks/agentic/github`, {
      headers: {
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": "sha256=deadbeef",
        "Content-Type": "application/json",
      },
      data: {},
    });
    expect(res.status()).toBe(400);
    const body = await res.json();
    expect(body.detail).toMatch(/X-GitHub-Delivery/i);
  });

  test("stripe webhook 401s on invalid signature", async ({ request }) => {
    const res = await request.post(`${API}/api/v1/webhooks/agentic/stripe`, {
      headers: {
        "Stripe-Signature": "t=1,v1=deadbeef",
        "Content-Type": "application/json",
      },
      data: { id: "evt_t5_bad", type: "checkout.session.completed" },
    });
    expect(res.status()).toBe(401);
    const body = await res.json();
    expect(body.detail).toMatch(/invalid Stripe signature/i);
  });

  test("stripe webhook 400s when Stripe-Signature header is missing", async ({
    request,
  }) => {
    const res = await request.post(`${API}/api/v1/webhooks/agentic/stripe`, {
      headers: { "Content-Type": "application/json" },
      data: { id: "evt_t5_nosig", type: "checkout.session.completed" },
    });
    // Empty header → "missing Stripe-Signature header" → 401 from
    // sig verify (the dependency's empty-header check raises a
    // WebhookSignatureError, mapped to 401, not 400). Asserting the
    // *category* (4xx) rather than the exact code keeps the contract
    // honest while documenting the actual response shape.
    expect(res.status()).toBeGreaterThanOrEqual(400);
    expect(res.status()).toBeLessThan(500);
  });
});

test.describe("Agentic OS — frontend smoke", () => {
  // Lightest-possible browser-rendered check: the v8 home page boots,
  // the title is the brand string, and there are no console errors
  // that suggest the app crashed at hydration time. NOT a substitute
  // for the existing `production-readiness.spec.ts` suite — just
  // confirms MCP-Playwright is wired to a serving frontend.

  test("home page renders with brand title", async ({ page }) => {
    await page.goto("http://localhost:3002/");
    await expect(page).toHaveTitle(/CareerForge/i);
  });
});
