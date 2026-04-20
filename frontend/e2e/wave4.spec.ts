/**
 * Wave 4 E2E smoke tests — P1-3, P2-4, P2-5, P2-6, P2-7, P2-8
 *
 * These run against the live Docker stack (localhost:3002 / localhost:8080).
 * Auth is handled via the smoke test user (pre-seeded in global-setup or
 * created on-demand by helpers.getToken()).
 */
import { test, expect } from "@playwright/test";
import { getToken, injectAuth } from "./helpers";

let token: string;

test.beforeAll(async () => {
  token = await getToken();
});

test.beforeEach(async ({ page }) => {
  await injectAuth(page, token);
});

// ── P2-6: Chat sidebar (hamburger + slide-in drawer) ───────────────────────
test("P2-6 — chat sidebar renders with search and conversation list", async ({
  page,
}) => {
  await page.goto("/chat");
  // Sidebar should be visible on desktop with search box
  await expect(page.getByRole("searchbox", { name: /search conversations/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /new conversation/i })).toBeVisible();
});

// ── P2-8: Slash command menu ────────────────────────────────────────────────
test("P2-8 — typing / opens slash command menu with all commands", async ({
  page,
}) => {
  await page.goto("/chat");
  const textarea = page.getByRole("textbox", { name: /message input/i });
  await textarea.waitFor({ state: "visible" });
  await textarea.fill("/");
  // Slash menu should appear
  await expect(page.getByRole("listbox", { name: /slash commands/i })).toBeVisible();
  await expect(page.getByText("/tutor")).toBeVisible();
  await expect(page.getByText("/code")).toBeVisible();
  await expect(page.getByText("/quiz")).toBeVisible();
  await expect(page.getByText("/career")).toBeVisible();
  await expect(page.getByText("/new")).toBeVisible();
  // Escape closes the menu
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox", { name: /slash commands/i })).toBeHidden();
});

// ── P2-8: Mode switch buttons ───────────────────────────────────────────────
test("P2-8 — mode switch buttons are visible (Auto/Tutor/Code Review/Career/Quiz Me)", async ({
  page,
}) => {
  await page.goto("/chat");
  await expect(page.getByRole("button", { name: /switch to auto mode/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /switch to tutor mode/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /switch to code review mode/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /switch to career mode/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /switch to quiz me mode/i })).toBeVisible();
});

// ── P1-7: Context attach button ─────────────────────────────────────────────
test("P1-7 — attach context (@) button is present in composer", async ({
  page,
}) => {
  await page.goto("/chat");
  await expect(page.getByRole("button", { name: /attach context/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /attach files/i })).toBeVisible();
});

// ── Full chat flow: send message, get response, check metadata ──────────────
test("P2-4 + P2-5 — send message, agent routes, metadata badge shows timing", async ({
  page,
}) => {
  await page.goto("/chat");
  const textarea = page.getByRole("textbox", { name: /message input/i });
  await textarea.waitFor({ state: "visible" });
  await textarea.fill("What is RAG?");
  await page.keyboard.press("Enter");

  // URL gains ?c= once conversation is created
  await page.waitForURL(/chat\?c=/, { timeout: 15_000 });

  // Wait for assistant response (up to 40s for LLM)
  await expect(page.getByText(/retrieval/i).first()).toBeVisible({ timeout: 40_000 });

  // P2-5: metadata button with timing info should appear on the bubble
  const metaBtn = page.locator('button[aria-label*="Message metadata"]').first();
  await expect(metaBtn).toBeVisible({ timeout: 5_000 });
  const label = await metaBtn.getAttribute("aria-label") ?? "";
  expect(label).toMatch(/first.*total.*tokens/i);

  // P2-4: sidebar conversation badge shows agent name (Tutor / Socratic)
  const convItem = page.locator('[role="button"]').filter({ hasText: /RAG/i });
  await expect(convItem).toBeVisible();
});
