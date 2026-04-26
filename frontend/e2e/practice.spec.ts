/**
 * /practice — happy-path coverage for the unified workspace (Option A slice).
 *
 * Covers:
 *   - Catalog loads with tier groupings and the New Scratchpad button
 *   - Workspace opens for a real exercise from /api/v1/exercises
 *   - Monaco renders with starter code
 *   - Run executes against /api/v1/execute and surfaces output
 *   - Get AI Review calls /api/v1/practice/review and renders structured JSON
 *   - Clicking a comment line jumps the editor (smoke check via highlight class)
 *   - Submit triggers /exercises/:id/submit and Tests tab updates as it grades
 *   - History tab lists submissions
 *   - Cmd/Ctrl+Enter triggers Run from inside the editor
 *
 * Stack assumed running:
 *   docker compose up -d  &&  pnpm dev
 *   backend on http://localhost:8080  (nginx proxy)
 *   frontend on http://localhost:3002
 *   migrations applied through 0043_ai_reviews
 *   seed_e2e_exercises.sql + seed_e2e_courses.sql applied
 */

import { test, expect, type Page } from "@playwright/test";
import { getToken } from "./helpers";

const API = "http://localhost:8080/api/v1";

let token: string;
let firstExerciseId: string | null = null;

test.beforeAll(async () => {
  token = await getToken();
  const res = await fetch(`${API}/exercises?limit=50`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const list = (await res.json()) as Array<{ id: string }>;
  if (Array.isArray(list) && list.length > 0) {
    firstExerciseId = list[0].id;
  }
});

async function gotoPractice(page: Page) {
  await page.goto("/practice");
  await expect(page.getByTestId("practice-header")).toBeVisible({
    timeout: 15_000,
  });
}

test.describe("/practice catalog", () => {
  test("catalog renders header, scratchpad button, and tier groupings", async ({
    page,
  }) => {
    await gotoPractice(page);
    const scratchpad = page.getByTestId("new-scratchpad-btn");
    await expect(scratchpad).toBeVisible();
    // Scratchpad route ships in Phase 2 — the button is intentionally disabled
    // for the internal-preview release so users don't land on the broken
    // /practice/scratchpad path that the [problemId] segment swallows.
    await expect(scratchpad).toBeDisabled();
    await expect(scratchpad).toHaveAttribute("title", /Coming soon/i);
    // Preview-mode pill must be present until E2B replaces the subprocess
    // sandbox path.
    await expect(page.getByTestId("practice-preview-note")).toBeVisible();
    // Wait for the catalog to hydrate with at least one card before counting
    // tier sections — otherwise we race the React Query fetch.
    await expect(
      page.getByTestId("practice-problem-card").first(),
    ).toBeVisible({ timeout: 15_000 });
    const tierVisible = await page.locator('[data-testid^="tier-"]').count();
    expect(tierVisible).toBeGreaterThan(0);
  });

  test("clicking a problem card navigates to its workspace", async ({
    page,
  }) => {
    test.skip(!firstExerciseId, "No exercises seeded — skipping deep link");
    await gotoPractice(page);
    const firstCard = page.getByTestId("practice-problem-card").first();
    await expect(firstCard).toBeVisible({ timeout: 10_000 });
    await firstCard.click();
    await expect(page).toHaveURL(/\/practice\/[0-9a-f-]{36}/, {
      timeout: 10_000,
    });
  });
});

test.describe("/practice/[problemId] workspace", () => {
  test.beforeEach(async () => {
    test.skip(!firstExerciseId, "No exercise seeded for workspace tests");
  });

  test("two-pane layout renders with problem + Monaco editor", async ({
    page,
  }) => {
    await page.goto(`/practice/${firstExerciseId}`);
    await expect(page.getByTestId("problem-pane")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("problem-title")).not.toHaveText("Loading…", {
      timeout: 15_000,
    });
    // Monaco mounts asynchronously. Wait for the editor container, then for
    // either the loading shim to disappear or for a textarea (Monaco's text
    // input layer) to appear.
    await expect(page.getByTestId("practice-editor")).toBeVisible();
    await page
      .locator('.monaco-editor, [data-testid="practice-editor"] textarea')
      .first()
      .waitFor({ timeout: 20_000 });
  });

  test("Run executes code and shows output (exit code + stdout)", async ({
    page,
  }) => {
    await page.goto(`/practice/${firstExerciseId}`);
    await expect(page.getByTestId("practice-editor")).toBeVisible({
      timeout: 15_000,
    });
    // Wait for Monaco to mount before clicking — otherwise the editor's value
    // may still be the empty string.
    await page.locator(".monaco-editor").first().waitFor({ timeout: 20_000 });
    await page.getByTestId("run-btn").click();
    // Output tab becomes active and shows exit code within the run timeout.
    await expect(page.getByTestId("output-tab")).toBeVisible();
    await expect(page.getByTestId("output-exit-code")).toBeVisible({
      timeout: 30_000,
    });
  });

  test("Get AI Review populates the AI Review tab with structured response", async ({
    page,
  }) => {
    // Stub the review endpoint so we don't burn an LLM call per test run and
    // we get a deterministic structured payload to assert on.
    await page.route("**/api/v1/practice/review", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "00000000-0000-0000-0000-000000000001",
          problem_id: firstExerciseId,
          created_at: new Date().toISOString(),
          review: {
            verdict: "request_changes",
            headline: "Tighten the retry loop and surface the failure path.",
            strengths: [
              "Function signature is clear and idiomatic.",
              "You separated parsing from I/O.",
            ],
            comments: [
              {
                line: 2,
                severity: "concern",
                message:
                  "This swallows exceptions silently — the caller can't tell when the parse failed.",
                suggested_change: null,
              },
              {
                line: 5,
                severity: "suggestion",
                message: "Prefer an explicit Optional return over a sentinel.",
                suggested_change: "def classify_prompt(text: str) -> str | None:",
              },
            ],
            next_step:
              "Add one negative test that proves the failure path returns the right value.",
          },
        }),
      });
    });

    await page.goto(`/practice/${firstExerciseId}`);
    await expect(page.getByTestId("practice-editor")).toBeVisible({
      timeout: 15_000,
    });
    await page.locator(".monaco-editor").first().waitFor({ timeout: 20_000 });

    await page.getByTestId("review-btn").click();
    await expect(page.getByTestId("review-tab")).toBeVisible();
    await expect(page.getByTestId("ai-review-verdict")).toContainText(
      /Request changes/i,
    );
    await expect(page.getByTestId("ai-review-headline")).toContainText(
      /Tighten the retry loop/,
    );
    await expect(page.getByTestId("ai-review-strengths")).toBeVisible();
    await expect(page.getByTestId("ai-review-comments")).toBeVisible();
    await expect(page.getByTestId("ai-review-next-step")).toBeVisible();
  });

  test("clicking a line-anchored comment scrolls the editor", async ({
    page,
  }) => {
    await page.route("**/api/v1/practice/review", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "00000000-0000-0000-0000-000000000002",
          problem_id: firstExerciseId,
          created_at: new Date().toISOString(),
          review: {
            verdict: "comment",
            headline: "Looks good — one nit.",
            strengths: [],
            comments: [
              {
                line: 1,
                severity: "nit",
                message: "Module docstring would help future-you.",
                suggested_change: null,
              },
            ],
            next_step: "Ship it.",
          },
        }),
      });
    });

    await page.goto(`/practice/${firstExerciseId}`);
    await page.locator(".monaco-editor").first().waitFor({ timeout: 20_000 });
    await page.getByTestId("review-btn").click();
    await expect(page.getByTestId("ai-review-line-1")).toBeVisible({
      timeout: 15_000,
    });
    await page.getByTestId("ai-review-line-1").click();
    // Highlight class is applied on the gutter for ~1.5s; assert it appears.
    await expect(page.locator(".practice-line-highlight").first()).toBeVisible({
      timeout: 3_000,
    });
  });

  test("Submit calls /exercises/:id/submit and updates Tests tab", async ({
    page,
  }) => {
    await page.goto(`/practice/${firstExerciseId}`);
    await page.locator(".monaco-editor").first().waitFor({ timeout: 20_000 });
    await page.getByTestId("submit-btn").click();
    // Tests tab activates immediately. Either a "Grading…" intermediate or
    // the final status pill is the success signal. The backend uses an LLM
    // grader that can take >60s; we only assert the submission was accepted
    // and the UI is responsive, not that grading finished.
    await expect(page.getByTestId("tests-tab")).toBeVisible();
    const status = page.getByTestId("submission-status");
    const grading = page
      .getByTestId("tests-tab")
      .getByText(/Grading…|Submitting…/);
    await expect(status.or(grading)).toBeVisible({ timeout: 30_000 });
  });

  test("History tab shows past submissions after Submit", async ({ page }) => {
    await page.goto(`/practice/${firstExerciseId}`);
    await page.locator(".monaco-editor").first().waitFor({ timeout: 20_000 });
    await page.getByTestId("tab-history").click();
    await expect(page.getByTestId("history-tab")).toBeVisible();
    // Either rows exist (from the submit test above) or the empty state shows —
    // both are valid happy paths since tests run in undefined order.
    const rows = page.getByTestId("history-row");
    const emptyText = page.getByTestId("history-tab").getByText(
      /No submissions yet/,
    );
    await expect(rows.first().or(emptyText)).toBeVisible({ timeout: 10_000 });
  });

  test("Cmd/Ctrl+Enter inside the editor triggers Run", async ({ page }) => {
    await page.goto(`/practice/${firstExerciseId}`);
    await page.locator(".monaco-editor").first().waitFor({ timeout: 20_000 });
    // Click the editor's view-lines area to focus it (Monaco's hidden textarea
    // has 0×0 hit area; clicking it directly is intercepted by the overlay).
    await page.locator(".monaco-editor .view-lines").first().click();
    const isMac = process.platform === "darwin";
    await page.keyboard.press(isMac ? "Meta+Enter" : "Control+Enter");
    await expect(page.getByTestId("output-tab")).toBeVisible();
    await expect(page.getByTestId("output-exit-code")).toBeVisible({
      timeout: 30_000,
    });
  });

  // Bug-1 regression: an unknown problemId must render a full-screen error
  // and refuse to mount the editor / Submit button. Previously the workspace
  // rendered with "Loading…" forever and a live Submit that 404s silently.
  test("invalid problemId renders full-screen error, no editor, no Submit", async ({
    page,
  }) => {
    await page.goto("/practice/00000000-0000-0000-0000-000000000000");
    await expect(page.getByTestId("practice-workspace-error")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("practice-editor")).toHaveCount(0);
    await expect(page.getByTestId("submit-btn")).toHaveCount(0);
    await expect(page.getByTestId("run-btn")).toHaveCount(0);
    // The "Back to practice catalog" link is the only path forward.
    await expect(
      page.getByRole("link", { name: /back to practice catalog/i }),
    ).toBeVisible();
  });

  // Bug-2 regression: Reset must restore the starter code in Monaco itself,
  // not just the React state. @monaco-editor/react treats `value` as
  // initial-only after mount, so React updates alone don't replace contents.
  test("Reset restores starter code in the Monaco editor", async ({
    page,
  }) => {
    await page.goto(`/practice/${firstExerciseId}`);
    await page.locator(".monaco-editor").first().waitFor({ timeout: 20_000 });
    // Capture the starter code, mutate it, then Reset twice (confirm dance).
    const starter = await page.evaluate(() => {
      // window.monaco is the global Monaco namespace once any editor mounts.
      const w = window as unknown as { monaco?: { editor: { getEditors: () => Array<{ getValue: () => string; setValue: (s: string) => void }> } } };
      return w.monaco?.editor.getEditors()[0]?.getValue() ?? null;
    });
    expect(starter).not.toBeNull();
    expect(starter!.length).toBeGreaterThan(0);

    await page.evaluate(() => {
      const w = window as unknown as { monaco?: { editor: { getEditors: () => Array<{ setValue: (s: string) => void }> } } };
      w.monaco?.editor.getEditors()[0]?.setValue("# RUBBISH\nprint('mutated')\n");
    });
    const mutated = await page.evaluate(() => {
      const w = window as unknown as { monaco?: { editor: { getEditors: () => Array<{ getValue: () => string }> } } };
      return w.monaco?.editor.getEditors()[0]?.getValue() ?? null;
    });
    expect(mutated).toContain("RUBBISH");

    await page.getByTestId("reset-btn").click(); // arms confirm
    await page.getByTestId("reset-btn").click(); // confirms
    // Give React + Monaco one tick to reconcile.
    await page.waitForTimeout(200);

    const restored = await page.evaluate(() => {
      const w = window as unknown as { monaco?: { editor: { getEditors: () => Array<{ getValue: () => string }> } } };
      return w.monaco?.editor.getEditors()[0]?.getValue() ?? null;
    });
    expect(restored).toBe(starter);
  });
});
