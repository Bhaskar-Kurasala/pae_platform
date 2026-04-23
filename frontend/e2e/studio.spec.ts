/**
 * Studio E2E — golden-path + edge-case coverage for the Studio revamp.
 *
 * Covers:
 *   P0-1  Snippet toolbar (rich dropdown with hints)
 *   P0-2  Context-aware right rail (Tutor / Review / Trace tabs)
 *   P0-3  Try-in-Studio deep link from chat
 *   P0-4  Senior Review panel
 *   P1-1  Streak badge in header
 *   P1-2  Daily warm-up prompt
 *   P1-3  Quality score (bottom panel)
 *   P1-4  Error → "Why did this break?" explain button
 *   P1-5  Save to Notebook after successful run
 *   P2-1  Challenge ladder drawer
 *   P2-2  Skill graph tab
 *   P2-3  Mental model predict/compare flow
 *   P3-2  Badge gallery modal
 *   Edge cases
 */

import { test, expect, type Page } from "@playwright/test";
import { getToken, injectAuth } from "./helpers";

let token: string;

const HELLO_CODE = `print("hello from studio e2e")`;
const BROKEN_CODE = `def foo(\n  x = 1\n  return x\n`;

/** Encode code the same way the chat "Try in Studio" button does.
 *  Browser: btoa(unescape(encodeURIComponent(code)))
 *  Node equivalent: Buffer.from(unescape(encodeURIComponent(code)), 'binary').toString('base64')
 */
function encodeCode(code: string): string {
  // eslint-disable-next-line no-restricted-globals
  return Buffer.from(unescape(encodeURIComponent(code)), "binary").toString("base64");
}

test.beforeAll(async () => {
  token = await getToken();
});

test.beforeEach(async ({ page }) => {
  await injectAuth(page, token);
  await page.addInitScript(() => {
    // Clear studio state so each test starts fresh
    for (const key of [
      "studio-streak",
      "studio-warmup-dismissed",
      "studio-challenges-done",
      "studio-skills",
      "studio-skill-counts",
      "studio-stats",
      "studio-badges-earned",
      // Clear editor code so Monaco always starts from the injected value
      "studio.code",
      // Clear draft so context's restore-draft effect doesn't pull stale code
      "studio-draft-studio-global",
    ]) {
      localStorage.removeItem(key);
    }
    // Also clear any date-keyed warmup-dismissed keys
    for (const k of Object.keys(localStorage)) {
      if (k.startsWith("studio-warmup-dismissed-")) localStorage.removeItem(k);
    }
  });
});

// ── Helpers ──────────────────────────────────────────────────────────────────

async function gotoStudio(page: Page, code?: string) {
  if (code) {
    // Pre-seed studio.code in localStorage so Monaco picks it up immediately.
    // The URL ?code= param sets the context initialCode, but Monaco's own
    // useEffect reads localStorage and can override it — seeding prevents that.
    await page.addInitScript((c: string) => {
      localStorage.setItem("studio.code", c);
    }, code);
    await page.goto(`/studio?code=${encodeCode(code)}`);
  } else {
    await page.goto("/studio");
  }
  // Wait for the Run button — confirms the Studio layout is mounted.
  await page.waitForSelector('[aria-label="Run code"]', { timeout: 30_000 });
}

// ── P0-1: Snippet toolbar ────────────────────────────────────────────────────

test("P0-1 — Snippets button opens rich dropdown with category tags", async ({ page }) => {
  await gotoStudio(page);

  // Button aria-label is "Insert a code snippet — pick a ready-made Anthropic API pattern"
  const snippetsBtn = page.getByRole("button", {
    name: /insert a code snippet/i,
  });
  await expect(snippetsBtn).toBeVisible({ timeout: 10_000 });

  // Hint text next to button
  await expect(
    page.getByText(/click to insert ready-made claude api patterns/i)
  ).toBeVisible();

  await snippetsBtn.click();

  // Panel header
  await expect(page.getByText("Claude API Snippets")).toBeVisible();
  await expect(page.getByText(/click any pattern to insert/i)).toBeVisible();

  // All 7 category tags visible in the dropdown
  for (const tag of ["setup", "basics", "streaming", "tools", "errors", "multimodal", "advanced"]) {
    await expect(page.getByText(tag, { exact: true }).first()).toBeVisible();
  }

  // Snippet labels (use .first() to avoid strict-mode violation with duplicated text)
  await expect(page.getByText("Import anthropic").first()).toBeVisible();
  await expect(page.getByText("Streaming").first()).toBeVisible();
  await expect(page.getByText("Tool use").first()).toBeVisible();
});

test("P0-1 — Clicking a snippet closes the panel", async ({ page }) => {
  await gotoStudio(page);
  await page.getByRole("button", { name: /insert a code snippet/i }).click();
  await expect(page.getByText("Claude API Snippets")).toBeVisible();

  // Each snippet button aria-label = "Insert {label} snippet: {hint}"
  await page.getByRole("button", { name: /insert import anthropic snippet/i }).click();
  await expect(page.getByText("Claude API Snippets")).toBeHidden();
});

test("P0-1 — Close X button dismisses snippet panel", async ({ page }) => {
  await gotoStudio(page);
  await page.getByRole("button", { name: /insert a code snippet/i }).click();
  await expect(page.getByText("Claude API Snippets")).toBeVisible();

  await page.getByRole("button", { name: "Close snippets panel" }).click();
  await expect(page.getByText("Claude API Snippets")).toBeHidden();
});

// ── P0-2: Context-aware right rail ───────────────────────────────────────────

test("P0-2 — Right rail shows TUTOR panel by default with chat prompts", async ({ page }) => {
  await gotoStudio(page);

  // "TUTOR" label in the right rail header (exact text in a span)
  await expect(page.locator("text=TUTOR").first()).toBeVisible({ timeout: 10_000 });

  // Quick-prompt chips
  await expect(page.getByText("What's wrong with this code?")).toBeVisible();
  await expect(page.getByText("Ask your Studio tutor")).toBeVisible();

  // Chat input
  await expect(page.getByPlaceholder(/ask about your code/i)).toBeVisible();
});

test("P0-2 — Right rail tab icons exist (Tutor, Review, Trace)", async ({ page }) => {
  await gotoStudio(page);

  // Tabs are in a tablist with aria-label="Right panel"
  const tablist = page.getByRole("tablist", { name: /right panel/i });
  await expect(tablist).toBeVisible({ timeout: 10_000 });

  // 3 tab buttons within the tablist
  const tabs = tablist.getByRole("tab");
  await expect(tabs).toHaveCount(3);
});

// ── P0-3: Try-in-Studio deep link ────────────────────────────────────────────

test("P0-3 — /studio?code= pre-loads code into the editor", async ({ page }) => {
  const code = 'print("deep linked")';
  // gotoStudio seeds studio.code via addInitScript so Monaco picks up the code.
  await gotoStudio(page, code);

  // Confirm Monaco rendered the deep-linked code by looking for the text in the editor.
  // Use getByText scoped to .monaco-editor to avoid issues with textContent() internals.
  await page.waitForSelector(".monaco-editor", { timeout: 30_000 });
  await expect(page.locator(".monaco-editor").getByText("deep linked").first()).toBeVisible({ timeout: 10_000 });
});

// ── P0-4: Senior Review ───────────────────────────────────────────────────────

test("P0-4 — Senior review button is visible in the editor header", async ({ page }) => {
  await gotoStudio(page);
  await expect(
    page.getByRole("button", { name: "Request senior engineer review" })
  ).toBeVisible({ timeout: 10_000 });
});

test("P0-4 — Clicking Senior review switches to REVIEW rail", async ({ page }) => {
  // Use code so the Senior review button is enabled (it's disabled when code is empty)
  await gotoStudio(page, HELLO_CODE);

  const reviewBtn = page.getByRole("button", { name: "Request senior engineer review" });
  // Wait for button to be enabled (Monaco fires onCodeChange, context code gets populated)
  await expect(reviewBtn).toBeEnabled({ timeout: 15_000 });
  await reviewBtn.click();

  // Right rail should auto-switch to review tab and show review content or empty state
  await expect(
    page.getByText('No review yet. Click "Senior review" to request one.')
      .or(page.getByText(/reviewing|reading your code|summary|nit|bug|security|suggestion/i).first())
  ).toBeVisible({ timeout: 30_000 });
});

// ── P1-1: Streak badge ───────────────────────────────────────────────────────

test("P1-1 — Streak badge is visible in the Studio header", async ({ page }) => {
  await gotoStudio(page);

  // aria-label="N-day coding streak", title="N-day coding streak"
  const streak = page.getByTitle(/day coding streak/i);
  await expect(streak).toBeVisible({ timeout: 10_000 });
});

// ── P1-2: Daily warm-up ──────────────────────────────────────────────────────

test("P1-2 — Daily warm-up banner appears when editor has no user code", async ({ page }) => {
  // beforeEach already cleared studio.code and studio-draft-studio-global.
  // Monaco falls back to DEFAULT_CODE; warm-up now also shows for DEFAULT_CODE.
  await gotoStudio(page);

  // Warm-up uses role="note" aria-label="Daily warm-up challenge"
  const warmup = page.getByRole("note", { name: "Daily warm-up challenge" });
  await expect(warmup).toBeVisible({ timeout: 10_000 });
});

test("P1-2 — Dismissing warm-up removes the banner", async ({ page }) => {
  // beforeEach cleared studio.code so Monaco shows DEFAULT_CODE.
  // Warm-up now also shows for DEFAULT_CODE (no user code yet).
  await gotoStudio(page);

  const dismissBtn = page.getByRole("button", { name: "Dismiss warm-up challenge for today" });
  await dismissBtn.waitFor({ state: "visible", timeout: 10_000 });
  await dismissBtn.click();

  await expect(
    page.getByRole("note", { name: "Daily warm-up challenge" })
  ).toBeHidden({ timeout: 3_000 });
});

// ── P1-3: Quality score ──────────────────────────────────────────────────────

test("P1-3 — CODE QUALITY panel is visible at the bottom", async ({ page }) => {
  await gotoStudio(page);
  await expect(page.getByText("CODE QUALITY")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: /^quality$/i })).toBeVisible();
});

test("P1-3 — Running code populates the quality panel", async ({ page }) => {
  await gotoStudio(page, HELLO_CODE);

  // Dismiss warm-up if present
  const dismissBtn = page.getByRole("button", { name: /dismiss warm-up/i });
  if (await dismissBtn.isVisible().catch(() => false)) await dismissBtn.click();

  await page.getByRole("button", { name: "Run code" }).click();

  await expect(
    page.getByText(/style|quality|ruff|pylint|no issues|score|passed/i).first()
  ).toBeVisible({ timeout: 25_000 });
});

// ── P1-4: Error explain button ───────────────────────────────────────────────

test("P1-4 — Running broken code shows error in Trace tab", async ({ page }) => {
  await gotoStudio(page, BROKEN_CODE);

  // Dismiss warm-up if it appears (since BROKEN_CODE seeded = Monaco shows it truthy)
  const dismissBtn = page.getByRole("button", { name: /dismiss warm-up/i });
  if (await dismissBtn.isVisible().catch(() => false)) await dismissBtn.click();

  // Wait for Run button to be enabled (code seeded and context updated)
  const runBtn = page.getByRole("button", { name: "Run code" });
  await expect(runBtn).toBeEnabled({ timeout: 15_000 });
  await runBtn.click();

  // The Execution trace tab has role="tab" (not button) in the right rail tablist
  await page.getByRole("tab", { name: "Execution trace" }).click();

  await expect(
    page.getByText(/error|syntax|traceback|exception|SyntaxError/i).first()
  ).toBeVisible({ timeout: 25_000 });
});

test("P1-4 — Error output in Trace shows 'Why did this break?' button", async ({ page }) => {
  await gotoStudio(page, BROKEN_CODE);

  const dismissBtn = page.getByRole("button", { name: /dismiss warm-up/i });
  if (await dismissBtn.isVisible().catch(() => false)) await dismissBtn.click();

  const runBtn = page.getByRole("button", { name: "Run code" });
  await expect(runBtn).toBeEnabled({ timeout: 15_000 });
  await runBtn.click();

  // Switch to Trace tab (role="tab" in right rail tablist, not role="button")
  await page.getByRole("tab", { name: "Execution trace" }).click();

  // Wait for error output
  await expect(
    page.getByText(/error|syntax|SyntaxError/i).first()
  ).toBeVisible({ timeout: 25_000 });

  // aria-label="Ask the tutor to explain this error" — text "Why did this break?"
  await expect(
    page.getByRole("button", { name: /ask the tutor to explain this error/i })
  ).toBeVisible({ timeout: 5_000 });
});

// ── P1-5: Save to Notebook ───────────────────────────────────────────────────

test("P1-5 — Save to Notebook button is hidden before running", async ({ page }) => {
  await gotoStudio(page, HELLO_CODE);
  await expect(
    page.getByRole("button", { name: /save.*notebook/i })
  ).toBeHidden({ timeout: 5_000 });
});

test("P1-5 — Save to Notebook button appears after a successful run", async ({ page }) => {
  await gotoStudio(page, HELLO_CODE);

  const dismissBtn = page.getByRole("button", { name: /dismiss warm-up/i });
  if (await dismissBtn.isVisible().catch(() => false)) await dismissBtn.click();

  await page.getByRole("button", { name: "Run code" }).click();

  const saveBtn = page.getByRole("button", { name: /save.*notebook/i });
  await expect(saveBtn).toBeVisible({ timeout: 25_000 });
});

test("P1-5 — Save to Notebook transitions to saved state on click", async ({ page }) => {
  await gotoStudio(page, HELLO_CODE);

  const dismissBtn = page.getByRole("button", { name: /dismiss warm-up/i });
  if (await dismissBtn.isVisible().catch(() => false)) await dismissBtn.click();

  await page.getByRole("button", { name: "Run code" }).click();

  const saveBtn = page.getByRole("button", { name: /save.*notebook/i });
  await saveBtn.waitFor({ state: "visible", timeout: 25_000 });
  await saveBtn.click();

  await expect(page.getByText(/saved/i).first()).toBeVisible({ timeout: 10_000 });
});

// ── P2-1: Challenge ladder ───────────────────────────────────────────────────

test("P2-1 — Challenges button opens challenge drawer", async ({ page }) => {
  await gotoStudio(page);

  // aria-label="Open challenge ladder"
  await page.getByRole("button", { name: "Open challenge ladder" }).click();

  await expect(page.getByText(/challenge/i).first()).toBeVisible({ timeout: 5_000 });
});

test("P2-1 — Challenge drawer shows difficulty tiers", async ({ page }) => {
  await gotoStudio(page);
  await page.getByRole("button", { name: "Open challenge ladder" }).click();

  await expect(page.getByText(/warm.?up/i).first()).toBeVisible({ timeout: 8_000 });
  await expect(page.getByText(/intermediate/i).first()).toBeVisible();
  await expect(page.getByText(/interview/i).first()).toBeVisible();
});

test("P2-1 — Escape key closes challenge drawer", async ({ page }) => {
  await gotoStudio(page);
  await page.getByRole("button", { name: "Open challenge ladder" }).click();
  // "Intermediate" tab only appears inside the challenge drawer, not elsewhere
  await expect(page.getByText(/intermediate/i).first()).toBeVisible({ timeout: 5_000 });

  await page.keyboard.press("Escape");
  await expect(page.getByText(/intermediate/i).first()).toBeHidden({ timeout: 3_000 });
});

// ── P2-2: Skill graph ────────────────────────────────────────────────────────

test("P2-2 — Skills tab shows skill graph nodes", async ({ page }) => {
  await gotoStudio(page);

  // aria-label="Skill tree" on the Skills button
  await page.getByRole("button", { name: "Skill tree" }).click();

  await expect(
    page.getByText(/api client|messages|foundation|streaming/i).first()
  ).toBeVisible({ timeout: 8_000 });
});

// ── P2-3: Mental model ───────────────────────────────────────────────────────

test("P2-3 — Mental model tab shows prediction textarea", async ({ page }) => {
  await gotoStudio(page, HELLO_CODE);

  await page.getByRole("button", { name: /mental model/i }).click();

  // Prediction textarea placeholder = "e.g. 5\nHello, world!"
  await expect(
    page.getByPlaceholder(/e\.g\. 5|Hello, world/i)
  ).toBeVisible({ timeout: 8_000 });
});

test("P2-3 — Locking prediction and running shows compare view", async ({ page }) => {
  await gotoStudio(page, HELLO_CODE);

  const dismissBtn = page.getByRole("button", { name: /dismiss warm-up/i });
  if (await dismissBtn.isVisible().catch(() => false)) await dismissBtn.click();

  await page.getByRole("button", { name: /mental model/i }).click();

  const predictInput = page.getByPlaceholder(/e\.g\. 5|Hello, world/i);
  await predictInput.waitFor({ state: "visible", timeout: 8_000 });
  await predictInput.fill("hello from studio e2e");

  // aria-label="Lock in prediction and run code"
  await page.getByRole("button", { name: "Lock in prediction and run code" }).click();

  // After run, compare view shows prediction vs actual
  await expect(
    page.getByText(/your prediction|actual output|prediction/i).first()
  ).toBeVisible({ timeout: 30_000 });
});

// ── P3-2: Badge gallery ──────────────────────────────────────────────────────

test("P3-2 — Badges button opens badge gallery modal", async ({ page }) => {
  await gotoStudio(page);

  // aria-label="View earned badges"
  await page.getByRole("button", { name: "View earned badges" }).click();

  await expect(page.getByRole("heading", { name: /your badges/i })).toBeVisible({ timeout: 5_000 });
});

test("P3-2 — Badge gallery shows content", async ({ page }) => {
  await gotoStudio(page);
  await page.getByRole("button", { name: "View earned badges" }).click();

  await expect(page.getByRole("heading", { name: /your badges/i })).toBeVisible({ timeout: 5_000 });
  // Badge gallery dialog
  await expect(
    page.getByRole("dialog", { name: "Badge gallery" })
  ).toBeVisible();
});

test("P3-2 — Escape key closes badge gallery", async ({ page }) => {
  await gotoStudio(page);
  await page.getByRole("button", { name: "View earned badges" }).click();
  await expect(page.getByRole("heading", { name: /your badges/i })).toBeVisible({ timeout: 5_000 });

  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: /your badges/i })).toBeHidden({ timeout: 3_000 });
});

test("P3-2 — Clicking outside badge modal closes it", async ({ page }) => {
  await gotoStudio(page);
  await page.getByRole("button", { name: "View earned badges" }).click();
  await expect(page.getByRole("heading", { name: /your badges/i })).toBeVisible({ timeout: 5_000 });

  // Click outside the modal (top-left corner)
  await page.mouse.click(10, 10);
  await expect(page.getByRole("heading", { name: /your badges/i })).toBeHidden({ timeout: 3_000 });
});

// ── Edge cases ───────────────────────────────────────────────────────────────

test("Edge — Studio loads without code param", async ({ page }) => {
  await page.goto("/studio");
  await page.waitForSelector('[aria-label="Run code"]', { timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Run code" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Request senior engineer review" })).toBeVisible();
});

test("Edge — Studio does not crash navigating from /chat", async ({ page }) => {
  await page.goto("/chat");
  await page.waitForSelector("main", { timeout: 10_000 });
  await page.goto("/studio");
  await page.waitForSelector('[aria-label="Run code"]', { timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Run code" })).toBeVisible();
});

test("Edge — History tab exists in bottom panel", async ({ page }) => {
  await gotoStudio(page);
  await expect(page.getByRole("button", { name: /history/i })).toBeVisible({ timeout: 10_000 });
});

test("Edge — Preview tab exists in bottom panel", async ({ page }) => {
  await gotoStudio(page);
  await expect(page.getByRole("button", { name: /preview/i })).toBeVisible({ timeout: 10_000 });
});
