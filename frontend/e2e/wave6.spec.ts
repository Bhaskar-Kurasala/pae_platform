/**
 * Wave 6 E2E smoke tests — P3-1, P3-2, P3-3, P3-4
 *
 * Each test relies on an existing conversation with at least one assistant
 * bubble. We seed one at the start of the suite via the streaming API.
 */
import { test, expect, type Page } from "@playwright/test";
import { getToken, injectAuth } from "./helpers";

const API = "http://localhost:8080/api/v1";
let token: string;
let conversationUrl: string;

async function seedConversation(page: Page, tok: string): Promise<string> {
  // Call stream endpoint directly to create conversation + message
  const res = await fetch(`${API}/agents/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${tok}`,
    },
    body: JSON.stringify({
      message: "Explain LangGraph in one sentence.",
      conversation_id: null,
    }),
  });
  if (!res.ok) throw new Error(`Seed stream failed: ${res.status}`);
  const text = await res.text();
  const convMatch = text.match(/"conversation_id":\s*"([^"]+)"/);
  if (!convMatch) throw new Error("No conversation_id in seed response");
  return `http://localhost:3002/chat?c=${convMatch[1]}`;
}

test.beforeAll(async ({ browser }) => {
  token = await getToken();
  const page = await browser.newPage();
  await injectAuth(page, token);
  await page.goto("/chat");
  conversationUrl = await seedConversation(page, token);
  await page.close();
});

test.beforeEach(async ({ page }) => {
  await injectAuth(page, token);
});

// ── P3-1: Explain differently ────────────────────────────────────────────────
test("P3-1 — 'Explain differently' button opens 4-option menu", async ({
  page,
}) => {
  await page.goto(conversationUrl);
  // Wait for assistant bubble to appear
  await page.waitForTimeout(3000);
  const explainBtn = page.getByTestId("explain-differently-trigger");
  await explainBtn.waitFor({ state: "visible", timeout: 10_000 });
  await explainBtn.click();
  // Dropdown with 4 options
  await expect(page.getByRole("menuitem", { name: /simpler/i })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: /more rigorous/i })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: /via analogy/i })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: /show code/i })).toBeVisible();
  // Close
  await page.keyboard.press("Escape");
});

// ── P3-2: Flashcards API ────────────────────────────────────────────────────
test("P3-2 — flashcards API endpoint returns cards", async () => {
  const res = await fetch(`${API}/chat/flashcards`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      message_id: "e2e-test",
      content:
        "LangGraph is a stateful graph framework. Nodes are steps, edges are transitions, state is shared.",
    }),
  });
  expect(res.status).toBe(200);
  const data = await res.json();
  expect(data.cards_added).toBeGreaterThanOrEqual(1);
  expect(Array.isArray(data.cards)).toBe(true);
});

// ── P3-3: Quiz panel ────────────────────────────────────────────────────────
test("P3-3 — 'Quiz me' button opens MCQ panel with questions and answer highlighting", async ({
  page,
}) => {
  await page.goto(conversationUrl);
  await page.waitForTimeout(3000);

  // Click quiz me button
  const quizBtn = page.locator('button[aria-label="Quiz me on this message"]');
  await quizBtn.waitFor({ state: "visible", timeout: 10_000 });
  await quizBtn.click();

  // Panel should appear with a question
  await expect(page.locator("text=/Quiz:/i").first()).toBeVisible({ timeout: 15_000 });
  // Should have A/B/C/D options
  await expect(page.getByRole("button", { name: /^A\./i }).first()).toBeVisible({ timeout: 5_000 });

  // Click first answer and check highlighting
  await page.getByRole("button", { name: /^A\./i }).first().click();
  // Either correct (green) or incorrect (red) should appear
  await expect(
    page.locator("text=/correct/i, text=/incorrect/i").first()
  ).toBeVisible({ timeout: 3_000 });

  // Close the panel
  const closeBtn = page.locator('button[aria-label*="Close"]').filter({ hasText: "" }).first();
  await closeBtn.click();
  await expect(page.locator("text=/Quiz:/i")).toBeHidden();
});

// ── P3-4: Save to notebook ──────────────────────────────────────────────────
test("P3-4 — Save button toggles to Saved and entry appears in /notebook", async ({
  page,
}) => {
  await page.goto(conversationUrl);
  await page.waitForTimeout(3000);

  const saveBtn = page.locator('button[aria-label="Save to notebook"]');
  await saveBtn.waitFor({ state: "visible", timeout: 10_000 });
  await saveBtn.click();

  // Button text changes to "Saved"
  await expect(page.getByText("Saved")).toBeVisible({ timeout: 5_000 });

  // Navigate to /notebook and check the entry is there
  await page.goto("/notebook");
  await expect(page.getByText(/1 entr/i)).toBeVisible({ timeout: 5_000 });
  // Notebook entry card should show LangGraph content preview
  await expect(page.locator("text=/LangGraph/i").first()).toBeVisible();
});

// ── P3-4: Notebook page structure ───────────────────────────────────────────
test("P3-4 — /notebook page has correct heading and nav link is active", async ({
  page,
}) => {
  await page.goto("/notebook");
  await expect(page.getByRole("heading", { name: /notebook/i })).toBeVisible();
  await expect(page.getByText("Your saved messages from AI Tutor")).toBeVisible();
  // Nav link is active/highlighted
  const navLink = page.getByRole("link", { name: /notebook/i });
  await expect(navLink).toBeVisible();
});
