import { type Page, expect } from "@playwright/test";

const API = "http://localhost:8080/api/v1";
const EMAIL = "smoke@test.com";
const PASSWORD = "SmokePass123!";

/** Returns a JWT for the smoke test user (registers if needed). */
export async function getToken(): Promise<string> {
  try {
    await fetch(`${API}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: EMAIL, password: PASSWORD, full_name: "Smoke Test" }),
    });
  } catch {
    // already exists
  }
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  const { access_token } = await res.json();
  return access_token;
}

/** Inject JWT into the page's localStorage so Next.js picks it up on load. */
export async function injectAuth(page: Page, token: string) {
  await page.addInitScript((t: string) => {
    localStorage.setItem("auth_token", t);
    localStorage.setItem("access_token", t);
    // Zustand auth-storage: the app reads isAuthenticated from here on hydration.
    const existing = localStorage.getItem("auth-storage");
    if (existing) {
      try {
        const parsed = JSON.parse(existing) as { state?: { isAuthenticated?: boolean } };
        if (parsed.state?.isAuthenticated) return; // already authenticated, leave it alone
      } catch { /* fall through */ }
    }
    localStorage.setItem(
      "auth-storage",
      JSON.stringify({ state: { user: null, token: t, refreshToken: null, isAuthenticated: true }, version: 0 }),
    );
  }, token);
}

/** Navigate to /chat, wait for the composer, and send a message. Returns conversation URL. */
export async function sendChatMessage(page: Page, message: string): Promise<string> {
  await page.goto("/chat");
  const textarea = page.getByRole("textbox", { name: /message input/i });
  await textarea.waitFor({ state: "visible", timeout: 10_000 });
  await textarea.fill(message);
  await page.keyboard.press("Enter");
  // Wait for the conversation URL to include ?c=
  await page.waitForURL(/chat\?c=/, { timeout: 15_000 });
  return page.url();
}

/** Wait for streaming to finish (no more "Generating" in the action bar). */
export async function waitForStreamDone(page: Page, timeout = 30_000) {
  await expect(page.getByText(/generating/i)).toBeHidden({ timeout });
}

/** Hover the last assistant bubble to reveal action buttons. */
export async function hoverLastAssistantBubble(page: Page) {
  const bubbles = page.locator('[aria-label="Message actions"]');
  const count = await bubbles.count();
  if (count === 0) throw new Error("No assistant bubbles found");
  await bubbles.nth(count - 1).hover();
}
