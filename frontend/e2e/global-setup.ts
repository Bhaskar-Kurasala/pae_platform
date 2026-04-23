import { chromium, type FullConfig } from "@playwright/test";

const API = "http://localhost:8080/api/v1";
const EMAIL = "smoke@test.com";
const PASSWORD = "SmokePass123!";

async function globalSetup(_config: FullConfig) {
  // Register (idempotent) + login via the API.
  await fetch(`${API}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD, full_name: "Smoke Test" }),
  });

  const loginRes = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  const { access_token, refresh_token } = await loginRes.json();
  if (!access_token) throw new Error("Login failed — no token");

  // Fetch the user profile so we can hydrate the Zustand auth-storage correctly.
  const meRes = await fetch(`${API}/auth/me`, {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  const user = await meRes.json();

  // Zustand persisted auth state — this is what the app reads on hydration.
  const authStorage = JSON.stringify({
    state: {
      user: {
        id: user.id,
        email: user.email,
        full_name: user.full_name,
        role: user.role,
        avatar_url: user.avatar_url ?? null,
      },
      token: access_token,
      refreshToken: refresh_token ?? null,
      isAuthenticated: true,
    },
    version: 0,
  });

  // Open a browser, inject all auth keys, save storage state.
  const browser = await chromium.launch();
  const context = await browser.newContext({ baseURL: "http://localhost:3002" });
  const page = await context.newPage();
  await page.goto("/");
  await page.evaluate(
    ({ token, authStorage }: { token: string; authStorage: string }) => {
      localStorage.setItem("auth_token", token);
      localStorage.setItem("access_token", token);
      localStorage.setItem("auth-storage", authStorage);
    },
    { token: access_token, authStorage },
  );

  await context.storageState({ path: "e2e/.auth/user.json" });
  await browser.close();
}

export default globalSetup;
