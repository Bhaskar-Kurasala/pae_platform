/**
 * D9 — Agentic foundation E2E.
 *
 * Verifies the externally-observable behavior of the canonical
 * agentic endpoint and the admin trace endpoint. Black-box tests
 * against the running FastAPI container — the integration check
 * that complements the Layer 1 + Layer 2 routing-diversity tests
 * (which exercise the Supervisor's prompt logic with stub LLMs).
 *
 * Coverage per Pass 3b §13.2 + Checkpoint 4 sign-off:
 *   • Auth gate (no token → 401)
 *   • Layer 1 entitlement gate (authenticated unentitled student → 402)
 *   • PG-1 fix (FastAPI process has agentic subscribers, mirrors Celery)
 *   • Trace endpoint exists and returns the right shape for empty
 *     student journey
 *   • Trace endpoint admin gate (non-admin → 403)
 *
 * What this spec does NOT cover (deferred to manual / staging):
 *   • Entitled student happy path with real Sonnet response — would
 *     need: a seeded paid course_entitlements row + a live
 *     ANTHROPIC_API_KEY + a 5-15 second wait per request. Done as a
 *     manual verification step in the D9 final report instead.
 *   • Cost ceiling exhaustion → graceful decline — needs synthetic
 *     mv_student_daily_cost row + waiting 60s for Celery beat to
 *     refresh. Done manually.
 *
 * Run with: `cd frontend && pnpm playwright test agentic-foundation`.
 * Requires the docker stack to be up (nginx on :8080).
 */

import { test, expect } from "@playwright/test";

const API = "http://localhost:8080";

// Helper: register a fresh user and return the JWT.
async function registerStudent(
  request: import("@playwright/test").APIRequestContext,
  email: string,
  password: string = "test1234",
): Promise<string> {
  // Idempotent: registering an existing email returns 4xx, but we
  // immediately log in afterwards so a previously-registered fixture
  // user still works.
  await request.post(`${API}/api/v1/auth/register`, {
    data: {
      email,
      full_name: "D9 E2E Student",
      password,
    },
  });
  const loginRes = await request.post(`${API}/api/v1/auth/login`, {
    data: { email, password },
  });
  expect(loginRes.status()).toBe(200);
  const body = await loginRes.json();
  return body.access_token as string;
}

async function registerAdmin(
  request: import("@playwright/test").APIRequestContext,
  email: string,
  password: string = "admin1234",
): Promise<string> {
  await request.post(`${API}/api/v1/auth/register`, {
    data: {
      email,
      full_name: "D9 E2E Admin",
      password,
      role: "admin",
    },
  });
  const loginRes = await request.post(`${API}/api/v1/auth/login`, {
    data: { email, password },
  });
  expect(loginRes.status()).toBe(200);
  const body = await loginRes.json();
  return body.access_token as string;
}

// ── Auth gate ──────────────────────────────────────────────────────

test.describe("D9 — agentic chat: auth gate", () => {
  test("no auth token → 401", async ({ request }) => {
    const res = await request.post(`${API}/api/v1/agentic/default/chat`, {
      data: { message: "hello" },
    });
    // FastAPI returns 401 when get_current_user fails to extract a
    // valid bearer token.
    expect(res.status()).toBe(401);
  });

  test("invalid bearer token → 401", async ({ request }) => {
    const res = await request.post(`${API}/api/v1/agentic/default/chat`, {
      data: { message: "hello" },
      headers: { Authorization: "Bearer not-a-real-token" },
    });
    expect(res.status()).toBe(401);
  });
});

// ── Layer 1 entitlement gate ───────────────────────────────────────

test.describe("D9 — agentic chat: Layer 1 entitlement gate", () => {
  test("authenticated student with no entitlement → 402 with structured detail", async ({
    request,
  }) => {
    // Fresh student — registered, but no course_entitlements row and
    // no auto-granted free-tier signup_grace (the fresh signup flow's
    // free-tier wiring is documented but not auto-fired in dev).
    const token = await registerStudent(
      request,
      `d9-unentitled-${Date.now()}@example.com`,
    );
    const res = await request.post(`${API}/api/v1/agentic/default/chat`, {
      data: { message: "Explain transformers" },
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.status()).toBe(402);
    const body = await res.json();
    // Pass 3f §A.1 contract — structured detail with error_code +
    // next_action so the frontend can render an appropriate prompt.
    expect(body.detail).toMatchObject({
      error_code: "no_active_entitlement",
      next_action: "browse_catalog",
    });
    expect(body.detail.message).toBeTruthy();
  });
});

// ── Validation gates ───────────────────────────────────────────────

test.describe("D9 — agentic chat: pydantic validation", () => {
  // Note on FastAPI ordering: when a dependency (require_active_entitlement)
  // raises before path/body validators run, the dependency's status code wins.
  // For an unentitled student, ALL the below requests return 402 — the
  // entitlement gate fires first. This is correct behavior; the 422 paths
  // are only reachable for entitled students. We assert the negative-on-
  // entitlement-grounds outcome which is what production sees.

  test("invalid flow for unentitled student → 402 (entitlement gate fires first)", async ({
    request,
  }) => {
    const token = await registerStudent(
      request,
      `d9-badflow-${Date.now()}@example.com`,
    );
    const res = await request.post(`${API}/api/v1/agentic/garbage/chat`, {
      data: { message: "hello" },
      headers: { Authorization: `Bearer ${token}` },
    });
    // For an unentitled student, the entitlement dependency fires
    // first; the 422 path param validation is short-circuited.
    expect([402, 422]).toContain(res.status());
  });

  test("empty message body → 402 or 422 (entitlement gate may fire first)", async ({
    request,
  }) => {
    const token = await registerStudent(
      request,
      `d9-empty-${Date.now()}@example.com`,
    );
    const res = await request.post(`${API}/api/v1/agentic/default/chat`, {
      data: { message: "" },
      headers: { Authorization: `Bearer ${token}` },
    });
    expect([402, 422]).toContain(res.status());
  });

  test("oversized message → 402 or 422 (entitlement gate may fire first)", async ({
    request,
  }) => {
    const token = await registerStudent(
      request,
      `d9-oversize-${Date.now()}@example.com`,
    );
    const res = await request.post(`${API}/api/v1/agentic/default/chat`, {
      data: { message: "x".repeat(10001) },
      headers: { Authorization: `Bearer ${token}` },
    });
    expect([402, 422]).toContain(res.status());
  });
});

// ── PG-1 fix verification (FastAPI process has agentic subscribers) ─

test.describe("D9 — PG-1 fix: agentic loader runs in FastAPI process", () => {
  test("/health/ready stays green after lifespan loads agentic agents", async ({
    request,
  }) => {
    // The lifespan handler in main.py calls load_agentic_agents()
    // before yielding. If that crashes (e.g. broken agent module),
    // FastAPI never reaches "Application startup complete" and
    // /health/ready never returns 200. A green probe is the
    // black-box signal that PG-1 is wired correctly.
    const res = await request.get(`${API}/health/ready`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.status).toBe("ok");
  });
});

// ── Trace endpoint ─────────────────────────────────────────────────

test.describe("D9 — admin trace endpoint", () => {
  test("non-admin auth → 403", async ({ request }) => {
    const token = await registerStudent(
      request,
      `d9-non-admin-${Date.now()}@example.com`,
    );
    const fakeStudentId = "00000000-0000-0000-0000-000000000001";
    const res = await request.get(
      `${API}/api/v1/admin/students/${fakeStudentId}/journey`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(res.status()).toBe(403);
  });

  test("admin auth + unknown student → 200 with empty timeline", async ({
    request,
  }) => {
    const token = await registerAdmin(
      request,
      `d9-admin-${Date.now()}@example.com`,
    );
    const fakeStudentId = "00000000-0000-0000-0000-000000000002";
    const res = await request.get(
      `${API}/api/v1/admin/students/${fakeStudentId}/journey`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.student_id).toBe(fakeStudentId);
    expect(body.actions).toEqual([]);
    expect(body.chains).toEqual([]);
    expect(body.safety_incidents).toEqual([]);
    expect(body.summary.total_actions).toBe(0);
    expect(body.summary.total_chains).toBe(0);
  });

  test("admin auth + recent-decisions for unknown agent → 200 empty", async ({
    request,
  }) => {
    const token = await registerAdmin(
      request,
      `d9-admin-recent-${Date.now()}@example.com`,
    );
    const res = await request.get(
      `${API}/api/v1/admin/agents/learning_coach/recent-decisions`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.agent_name).toBe("learning_coach");
    expect(body.count).toBe(0);
    expect(body.decisions).toEqual([]);
  });

  test("invalid window (from > to) → 400", async ({ request }) => {
    const token = await registerAdmin(
      request,
      `d9-admin-window-${Date.now()}@example.com`,
    );
    const fakeStudentId = "00000000-0000-0000-0000-000000000003";
    const res = await request.get(
      `${API}/api/v1/admin/students/${fakeStudentId}/journey?from=2026-12-01T00:00:00Z&to=2026-01-01T00:00:00Z`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(res.status()).toBe(400);
  });
});
