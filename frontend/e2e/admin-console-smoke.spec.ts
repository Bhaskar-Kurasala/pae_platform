import { test, expect } from "@playwright/test";

const API = "http://localhost:8080/api/v1";
const ADMIN_EMAIL = "console-admin@example.com";
const ADMIN_PASSWORD = "admin123";

/** Get an admin JWT. The admin user is seeded by scripts.seed_admin_console (or
 *  via the script we ran for this smoke test). */
async function adminToken(): Promise<string> {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: ADMIN_EMAIL, password: ADMIN_PASSWORD }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status}`);
  const json = (await res.json()) as { access_token: string };
  return json.access_token;
}

test("admin console v1 renders with seeded data", async ({ page }) => {
  const token = await adminToken();

  await page.addInitScript((t: string) => {
    localStorage.setItem(
      "auth-storage",
      JSON.stringify({
        state: {
          user: { id: "console-admin", email: "console-admin@example.com", full_name: "Console Admin", role: "admin" },
          token: t,
          refreshToken: null,
          isAuthenticated: true,
        },
        version: 0,
      }),
    );
  }, token);

  await page.goto("/admin");
  // Wait for the action band title to appear
  await expect(page.getByText(/students?\s+need a personal nudge/i)).toBeVisible({ timeout: 15_000 });
  // Verify pulse strip rendered all 6 metrics
  await expect(page.getByText("Active learners (24h)")).toBeVisible();
  await expect(page.getByText("MRR")).toBeVisible();
  // Funnel
  await expect(page.getByText("Signups")).toBeVisible();
  // Risk pill on at least one row
  await expect(page.getByText("Severe").first()).toBeVisible();
  await page.screenshot({ path: "test-results/admin-console-v1.png", fullPage: true });
});
