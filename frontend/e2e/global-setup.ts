import { chromium, type FullConfig } from "@playwright/test";

const API = "http://localhost:8080/api/v1";
const EMAIL = `e2e-pw-${Date.now()}@test.com`;
const PASSWORD = "E2ePass123!";

async function globalSetup(config: FullConfig) {
  // Register + login via the API, persist auth cookie/token for all specs.
  const regRes = await fetch(`${API}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD, full_name: "PW E2E" }),
  });
  if (!regRes.ok && regRes.status !== 409) {
    throw new Error(`Register failed: ${regRes.status}`);
  }

  const loginRes = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  const { access_token } = await loginRes.json();
  if (!access_token) throw new Error("Login failed — no token");

  // Open a browser, set the token in localStorage, save storage state.
  const browser = await chromium.launch();
  const context = await browser.newContext({ baseURL: "http://localhost:3002" });
  const page = await context.newPage();
  await page.goto("/");
  await page.evaluate((token: string) => {
    localStorage.setItem("auth_token", token);
    localStorage.setItem("access_token", token);
    // Try both common key names used by the app
    document.cookie = `auth_token=${token}; path=/`;
  }, access_token);

  await context.storageState({ path: "e2e/.auth/user.json" });
  await browser.close();
}

export default globalSetup;
