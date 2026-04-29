/**
 * F1-F6 — Retention engine E2E specs.
 *
 * Locks the contracts the user actually exercises:
 *   - F4 retention panels render with all 5 slip patterns
 *   - F4 panel totals match what the API reports
 *   - F4 student rows link to /admin/students/{id}
 *   - F2 admin notes textarea + Add note round-trip persists
 *
 * Backend coverage (F1 risk service + F3 outreach log + F5 email
 * service) is locked by 27 backend pytests; this spec covers the UI
 * contract only.
 *
 * Stack must be running (docker compose up -d) and the
 * student@pae.dev / admin@pae.dev accounts must exist with the admin
 * role promoted (see docs/runbooks/admin-management.md).
 */
import { test, expect, type Page } from "@playwright/test";

const API = "http://localhost:8080/api/v1";
const ADMIN_EMAIL = "admin@pae.dev";
const ADMIN_PASS = "Admin123!";

let adminToken: string;

test.beforeAll(async () => {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: ADMIN_EMAIL, password: ADMIN_PASS }),
  });
  const data = (await res.json()) as { access_token?: string };
  if (!data.access_token)
    throw new Error(`admin login failed: ${JSON.stringify(data)}`);
  adminToken = data.access_token;
});

async function injectAdmin(page: Page): Promise<void> {
  await page.addInitScript((t: string) => {
    const auth = {
      state: {
        user: {
          id: "admin-id",
          email: "admin@pae.dev",
          full_name: "Test Admin",
          role: "admin",
          is_active: true,
          is_verified: false,
          avatar_url: null,
        },
        token: t,
        refreshToken: null,
        isAuthenticated: true,
        _hasHydrated: true,
      },
      version: 0,
    };
    localStorage.setItem("auth-storage", JSON.stringify(auth));
    localStorage.setItem("auth_token", t);
    document.cookie = `auth_role=admin; path=/; max-age=86400`;
  }, adminToken);
}

test.describe("F4 — retention engine panels on /admin", () => {
  test("renders all 5 panels with correct titles", async ({ page }) => {
    await injectAdmin(page);
    await page.goto("http://localhost:3002/admin", {
      waitUntil: "domcontentloaded",
      timeout: 20_000,
    });

    // Wait for the retention engine section to mount.
    await expect(page.getByRole("heading", { name: "Retention engine" })).toBeVisible({
      timeout: 10_000,
    });

    // Each slip-pattern panel has a heading. Verify all 5 in order.
    const expected = [
      "Paid + silent",
      "Capstone stalled",
      "Streak broken",
      "Ready but stalled",
      "Never returned",
    ];
    for (const title of expected) {
      await expect(
        page.getByRole("heading", { name: title, level: 3 }),
      ).toBeVisible();
    }
  });

  test("panel totals match the /admin/risk-panels API response", async ({
    page,
    request,
  }) => {
    await injectAdmin(page);

    // Source of truth — direct API call.
    const apiRes = await request.get(`${API}/admin/risk-panels`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(apiRes.status()).toBe(200);
    const apiData = (await apiRes.json()) as Record<string, { total: number }>;

    await page.goto("http://localhost:3002/admin", {
      waitUntil: "domcontentloaded",
    });
    await expect(
      page.getByRole("heading", { name: "Retention engine" }),
    ).toBeVisible();

    // Read every panel's total badge from the DOM and compare to API.
    const totals = await page.evaluate(() => {
      const sections = Array.from(
        document.querySelectorAll('section[aria-labelledby^="panel-"]'),
      );
      return sections.map((s) => {
        const key =
          s.getAttribute("aria-labelledby")?.replace("panel-", "")
            .replace("-title", "") ?? "";
        const badge = s.querySelector("span.shrink-0")?.textContent?.trim();
        return { key, total: Number(badge ?? "0") };
      });
    });

    for (const { key, total } of totals) {
      expect(apiData[key]).toBeDefined();
      expect(total, `panel ${key} total mismatch`).toBe(apiData[key].total);
    }
  });

  test("student rows link to /admin/students/{id}", async ({ page }) => {
    await injectAdmin(page);
    await page.goto("http://localhost:3002/admin", {
      waitUntil: "domcontentloaded",
    });
    await expect(
      page.getByRole("heading", { name: "Retention engine" }),
    ).toBeVisible();

    // Find any student row in any panel — they should ALL link to
    // /admin/students/{uuid}. We don't care which one, only that the
    // shape is right.
    const link = page
      .locator('section[aria-labelledby^="panel-"] a[href^="/admin/students/"]')
      .first();
    if ((await link.count()) === 0) {
      // Edge case: every panel is empty. That's still a valid prod
      // state ("nice — every paid student is active") so we skip
      // rather than fail.
      test.skip(true, "no student rows in any panel — empty-state pass");
      return;
    }
    const href = await link.getAttribute("href");
    expect(href).toMatch(/^\/admin\/students\/[0-9a-f-]{36}$/);
  });
});

test.describe("F2 — admin notes on /admin/students/{id}", () => {
  test("typing + Add note posts and persists", async ({ page, request }) => {
    await injectAdmin(page);

    // Pick a student to exercise — pull the first user from /admin/students.
    const listRes = await request.get(`${API}/admin/students`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(listRes.status()).toBe(200);
    const students = (await listRes.json()) as Array<{ id: string }>;
    expect(students.length).toBeGreaterThan(0);
    const studentId = students[0].id;

    await page.goto(`http://localhost:3002/admin/students/${studentId}`, {
      waitUntil: "domcontentloaded",
      timeout: 20_000,
    });

    // The Admin notes card mounts once the timeline is rendered.
    await expect(page.getByRole("heading", { name: "Admin notes" })).toBeVisible(
      { timeout: 10_000 },
    );

    // Unique sentinel so multiple test runs don't collide on the
    // notes feed (the notes are append-only by design — F2 contract).
    const sentinel = `e2e ${Date.now()}-${Math.random().toString(36).slice(2, 8)} typed via Playwright`;
    const ta = page.getByRole("textbox", { name: "New admin note" });
    await ta.fill(sentinel);
    await page.getByRole("button", { name: "Add note", exact: true }).click();

    // After save the note shows up inside a <pre> in the notes list.
    // Target the pre directly so the still-being-cleared textarea
    // doesn't double-match in strict mode.
    await expect(page.locator("ol li pre", { hasText: sentinel })).toBeVisible({
      timeout: 5_000,
    });

    // Textarea clears AFTER the mutation resolves and React commits.
    await expect.poll(async () => await ta.inputValue(), { timeout: 5_000 }).toBe("");
  });

  test("zero console errors during note round-trip", async ({ page, request }) => {
    await injectAdmin(page);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
      if (m.type() === "error") {
        const t = m.text();
        if (
          t.includes("Download the React DevTools") ||
          t.includes("hydration")
        )
          return;
        errors.push(`console.error: ${t}`);
      }
    });

    const listRes = await request.get(`${API}/admin/students`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    const students = (await listRes.json()) as Array<{ id: string }>;
    const studentId = students[0].id;

    await page.goto(`http://localhost:3002/admin/students/${studentId}`);
    await expect(page.getByRole("heading", { name: "Admin notes" })).toBeVisible(
      { timeout: 10_000 },
    );
    const sentinel = `zero-error ${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    await page
      .getByRole("textbox", { name: "New admin note" })
      .fill(sentinel);
    await page.getByRole("button", { name: "Add note", exact: true }).click();
    await expect(page.locator("ol li pre", { hasText: sentinel })).toBeVisible({
      timeout: 5_000,
    });

    expect(errors).toEqual([]);
  });
});

// Targeted regression locks for the F1 risk-panels API contract.
test.describe("F1 + F4 API contract", () => {
  test("/admin/risk-panels returns all 5 slip-type buckets", async ({
    request,
  }) => {
    const res = await request.get(`${API}/admin/risk-panels`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(res.status()).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;

    const expected = [
      "paid_silent",
      "capstone_stalled",
      "streak_broken",
      "promotion_avoidant",
      "cold_signup",
    ];
    for (const key of expected) {
      expect(body[key], `missing panel ${key}`).toBeDefined();
      const panel = body[key] as { students: unknown[]; total: number };
      expect(panel).toHaveProperty("students");
      expect(panel).toHaveProperty("total");
      expect(Array.isArray(panel.students)).toBe(true);
      expect(typeof panel.total).toBe("number");
    }
  });

  test("/admin/risk-panels returns 403 for non-admin users", async ({
    request,
  }) => {
    // Get a student token.
    const studentRes = await request.post(`${API}/auth/login`, {
      data: { email: "student@pae.dev", password: "Student123!" },
      headers: { "Content-Type": "application/json" },
    });
    const studentData = (await studentRes.json()) as { access_token?: string };
    expect(studentData.access_token).toBeTruthy();

    const res = await request.get(`${API}/admin/risk-panels`, {
      headers: { Authorization: `Bearer ${studentData.access_token}` },
    });
    expect(res.status()).toBe(403);
  });
});
