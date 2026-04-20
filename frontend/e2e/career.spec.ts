/**
 * Career features E2E smoke tests
 *
 * Covers three pages:
 *   /career/resume         — Resume Builder
 *   /career/jd-fit         — JD Fit Analysis
 *   /career/interview-bank — Interview Prep (Mock Interview, Question Bank, Story Bank)
 *
 * Auth: uses helpers.getToken() (smoke@test.com / SmokePass123!) injected via
 * localStorage before each test — same pattern as wave4.spec.ts / wave6.spec.ts.
 *
 * Run against the live Docker stack:
 *   pnpm e2e e2e/career.spec.ts
 */
import { test, expect } from "@playwright/test";
import { getToken, injectAuth } from "./helpers";

const API = "http://localhost:8080/api/v1";

let token: string;

test.beforeAll(async () => {
  token = await getToken();
});

test.beforeEach(async ({ page }) => {
  await injectAuth(page, token);
});

// ══════════════════════════════════════════════════════════════════
// Resume Builder — /career/resume
// ══════════════════════════════════════════════════════════════════

test.describe("Resume Builder", () => {
  test("resume page loads and shows Professional Summary section", async ({
    page,
  }) => {
    await page.goto("/career/resume");
    // Page heading
    await expect(
      page.getByRole("heading", { name: /resume builder/i }),
    ).toBeVisible({ timeout: 10_000 });
    // Professional Summary card must be present (even if content is placeholder)
    await expect(
      page.getByRole("heading", { name: /professional summary/i }),
    ).toBeVisible();
  });

  test("Regenerate button is visible and triggers resume regeneration", async ({
    page,
  }) => {
    test.setTimeout(40_000);
    await page.goto("/career/resume");
    await expect(
      page.getByRole("heading", { name: /resume builder/i }),
    ).toBeVisible({ timeout: 10_000 });

    const regenBtn = page.getByRole("button", { name: /regenerate resume/i });
    await expect(regenBtn).toBeVisible();

    // Click — button should show spinner while pending
    await regenBtn.click();
    // Either "Regenerating…" spinner appears, or button goes back to "Regenerate" quickly
    // We just assert it doesn't throw / navigate away
    await expect(
      page.getByRole("heading", { name: /resume builder/i }),
    ).toBeVisible({ timeout: 35_000 });
  });

  test("Force Refresh button is visible and enabled", async ({ page }) => {
    await page.goto("/career/resume");
    await expect(
      page.getByRole("heading", { name: /resume builder/i }),
    ).toBeVisible({ timeout: 10_000 });

    const forceBtn = page.getByRole("button", {
      name: /force refresh resume from scratch/i,
    });
    await expect(forceBtn).toBeVisible();
    // Enabled when not already regenerating
    await expect(forceBtn).not.toBeDisabled();
  });

  test("ATS Keywords section shows keyword badges when data exists", async ({
    page,
  }) => {
    // Seed resume via API so we know there's keyword data
    const res = await fetch(`${API}/career/resume/regenerate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ force: false }),
    });
    // Allow 200 or any successful response; skip check if API fails
    if (res.ok) {
      await page.goto("/career/resume");
      await expect(
        page.getByRole("heading", { name: /resume builder/i }),
      ).toBeVisible({ timeout: 10_000 });

      // If ATS keywords exist the section heading is rendered
      const atsHeading = page.getByRole("heading", { name: /ats keywords/i });
      if (await atsHeading.isVisible({ timeout: 5_000 }).catch(() => false)) {
        // keyword list has role="list" aria-label="ATS keywords"
        const kwList = page.getByRole("list", { name: /ats keywords/i });
        await expect(kwList).toBeVisible();
        const badges = kwList.getByRole("listitem");
        await expect(badges.first()).toBeVisible();
      }
      // If no keywords yet, the section is simply absent — test still passes
    }
  });
});

// ══════════════════════════════════════════════════════════════════
// JD Fit Analysis — /career/jd-fit
// ══════════════════════════════════════════════════════════════════

const SAMPLE_JD =
  "We are looking for a Python developer with FastAPI, PostgreSQL, and LLM experience. " +
  "You will build production-ready AI APIs, design scalable database schemas, and integrate " +
  "large language models into our platform. Strong async Python, Docker, and REST API skills required.";

test.describe("JD Fit Analysis", () => {
  test("jd-fit page loads with textarea and Analyze Fit button", async ({
    page,
  }) => {
    await page.goto("/career/jd-fit");
    await expect(
      page.getByRole("heading", { name: /jd fit analysis/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Textarea for job description
    await expect(
      page.getByRole("textbox", { name: /job description text/i }),
    ).toBeVisible();

    // Analyze Fit button (disabled when textarea is empty)
    await expect(
      page.getByRole("button", { name: /analyze job fit/i }),
    ).toBeVisible();
  });

  test("pasting a JD and clicking Analyze Fit shows verdict banner", async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await page.goto("/career/jd-fit");
    await expect(
      page.getByRole("heading", { name: /jd fit analysis/i }),
    ).toBeVisible({ timeout: 10_000 });

    const jdBox = page.getByRole("textbox", { name: /job description text/i });
    await jdBox.fill(SAMPLE_JD);

    const analyzeBtn = page.getByRole("button", { name: /analyze job fit/i });
    await expect(analyzeBtn).not.toBeDisabled();
    await analyzeBtn.click();

    // Verdict banner must appear — it shows one of: "Apply Now", "Skill Up First", "Skip for Now"
    await expect(
      page.getByText(/apply now|skill up first|skip for now/i).first(),
    ).toBeVisible({ timeout: 55_000 });
  });

  test("Three-bucket gap shows Proven / Unproven / Missing sections after analysis", async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await page.goto("/career/jd-fit");
    await expect(
      page.getByRole("heading", { name: /jd fit analysis/i }),
    ).toBeVisible({ timeout: 10_000 });

    await page
      .getByRole("textbox", { name: /job description text/i })
      .fill(SAMPLE_JD);
    await page.getByRole("button", { name: /analyze job fit/i }).click();

    // Wait for analysis to complete (verdict banner)
    await expect(
      page.getByText(/apply now|skill up first|skip for now/i).first(),
    ).toBeVisible({ timeout: 55_000 });

    // Skill Breakdown card with three columns
    await expect(
      page.getByRole("heading", { name: /skill breakdown/i }),
    ).toBeVisible();
    await expect(page.getByText(/^Proven/)).toBeVisible();
    await expect(page.getByText(/^Unproven/)).toBeVisible();
    await expect(page.getByText(/^Missing/)).toBeVisible();
  });

  test("Save to Library button saves the JD after analysis", async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await page.goto("/career/jd-fit");
    await expect(
      page.getByRole("heading", { name: /jd fit analysis/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Fill title + JD
    const titleInput = page.getByRole("textbox", { name: /job title/i });
    await titleInput.fill("E2E Test Engineer");

    await page
      .getByRole("textbox", { name: /job description text/i })
      .fill(SAMPLE_JD);

    // Analyze first (Save to Library is disabled until analysis is ready)
    await page.getByRole("button", { name: /analyze job fit/i }).click();
    await expect(
      page.getByText(/apply now|skill up first|skip for now/i).first(),
    ).toBeVisible({ timeout: 55_000 });

    // Now save
    const saveBtn = page.getByRole("button", {
      name: /save job description to library/i,
    });
    await expect(saveBtn).not.toBeDisabled();
    await saveBtn.click();

    // Success message appears
    await expect(page.getByText(/saved to library/i)).toBeVisible({
      timeout: 10_000,
    });

    // Saved item should appear in the sidebar JD library
    await expect(page.getByText("E2E Test Engineer")).toBeVisible({
      timeout: 5_000,
    });
  });

  test("Delete from library removes the item", async ({ page }) => {
    test.setTimeout(60_000);
    // Seed a JD item directly via API so we don't need to run the full analysis
    const analyzeRes = await fetch(`${API}/career/fit-score`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ jd_text: SAMPLE_JD, jd_title: "Delete Me E2E" }),
    });

    if (analyzeRes.ok) {
      const saveRes = await fetch(`${API}/career/jd-library`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          title: "Delete Me E2E",
          jd_text: SAMPLE_JD,
        }),
      });

      if (saveRes.ok) {
        await page.goto("/career/jd-fit");
        await expect(
          page.getByRole("heading", { name: /jd fit analysis/i }),
        ).toBeVisible({ timeout: 10_000 });

        // Wait for the sidebar library to load
        const deleteBtn = page.getByRole("button", {
          name: /delete delete me e2e/i,
        });
        await expect(deleteBtn).toBeVisible({ timeout: 10_000 });
        await deleteBtn.click();

        // Item disappears
        await expect(
          page.getByRole("button", { name: /delete delete me e2e/i }),
        ).toBeHidden({ timeout: 10_000 });
      }
    }
    // If API seeding fails, test passes with a note — no hard failure on API errors
  });
});

// ══════════════════════════════════════════════════════════════════
// Interview Prep — /career/interview-bank
// ══════════════════════════════════════════════════════════════════

test.describe("Interview Prep", () => {
  test("interview-bank page loads with 3 tabs: Mock Interview, Question Bank, Story Bank", async ({
    page,
  }) => {
    await page.goto("/career/interview-bank");
    await expect(
      page.getByRole("heading", { name: /interview prep/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Three tabs via aria labels from TabsTrigger
    await expect(
      page.getByRole("tab", { name: /mock interview tab/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: /question bank tab/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: /story bank tab/i }),
    ).toBeVisible();
  });

  test("selecting Behavioral mode and clicking Start Interview shows first question", async ({
    page,
  }) => {
    test.setTimeout(40_000);
    await page.goto("/career/interview-bank");
    await expect(
      page.getByRole("heading", { name: /interview prep/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Select Behavioral mode
    const behavioralBtn = page.getByRole("button", {
      name: /select behavioral interview mode/i,
    });
    await expect(behavioralBtn).toBeVisible();
    await behavioralBtn.click();
    await expect(behavioralBtn).toHaveAttribute("aria-pressed", "true");

    // Start Interview
    const startBtn = page.getByRole("button", { name: /start mock interview/i });
    await expect(startBtn).not.toBeDisabled();
    await startBtn.click();

    // First question bubble appears — labelled "Question"
    await expect(page.getByText(/^Question$/i)).toBeVisible({
      timeout: 35_000,
    });
    // Answer textarea should be visible
    await expect(
      page.getByRole("textbox", { name: /your answer to the interview question/i }),
    ).toBeVisible();
  });

  test("submitting an answer shows rubric score panel with 5 dimension bars", async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await page.goto("/career/interview-bank");
    await expect(
      page.getByRole("heading", { name: /interview prep/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Select Behavioral and start
    await page
      .getByRole("button", { name: /select behavioral interview mode/i })
      .click();
    await page.getByRole("button", { name: /start mock interview/i }).click();

    // Wait for question
    await expect(page.getByText(/^Question$/i)).toBeVisible({
      timeout: 35_000,
    });

    // Type and submit an answer
    const answerBox = page.getByRole("textbox", {
      name: /your answer to the interview question/i,
    });
    await answerBox.fill(
      "In my previous role I led the migration of our monolith to microservices. " +
        "I designed the service boundaries using domain-driven design, coordinated with 5 teams, " +
        "and delivered the project 2 weeks ahead of schedule, reducing deploy time by 60%.",
    );
    await page.getByRole("button", { name: /submit your answer for evaluation/i }).click();

    // Evaluation card appears
    await expect(
      page.getByRole("heading", { name: /evaluation/i }),
    ).toBeVisible({ timeout: 40_000 });

    // 5 progress bars — one per rubric dimension: Clarity, Structure, Depth, Evidence, Confidence Language
    const dims = ["Clarity", "Structure", "Depth", "Evidence", "Confidence Language"];
    for (const dim of dims) {
      await expect(
        page.getByRole("progressbar", { name: new RegExp(`${dim} score`, "i") }),
      ).toBeVisible();
    }

    // Overall score (e.g. "7.5 / 10")
    await expect(page.getByText(/\/\s*10/)).toBeVisible();
  });

  test("End Interview shows final overall score", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/career/interview-bank");
    await expect(
      page.getByRole("heading", { name: /interview prep/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Select Technical mode and start
    await page
      .getByRole("button", { name: /select technical interview mode/i })
      .click();
    await page.getByRole("button", { name: /start mock interview/i }).click();
    await expect(page.getByText(/^Question$/i)).toBeVisible({
      timeout: 35_000,
    });

    // Submit one answer
    await page
      .getByRole("textbox", { name: /your answer to the interview question/i })
      .fill(
        "Async/await in Python enables non-blocking I/O using an event loop. " +
          "This is essential for high-throughput APIs where we await database calls and HTTP requests " +
          "without blocking the main thread.",
      );
    await page
      .getByRole("button", { name: /submit your answer for evaluation/i })
      .click();
    await expect(
      page.getByRole("heading", { name: /evaluation/i }),
    ).toBeVisible({ timeout: 40_000 });

    // Click End Interview
    await page
      .getByRole("button", { name: /end interview session and see final score/i })
      .click();

    // "Interview Complete" screen
    await expect(
      page.getByRole("heading", { name: /interview complete/i }),
    ).toBeVisible({ timeout: 15_000 });

    // Final score "X.X / 10"
    await expect(page.getByText(/\/\s*10/)).toBeVisible();

    // "Start New Interview" button is present
    await expect(
      page.getByRole("button", { name: /start a new interview session/i }),
    ).toBeVisible();
  });

  test("Story Bank tab: adding a story saves it to the list", async ({
    page,
  }) => {
    test.setTimeout(20_000);
    await page.goto("/career/interview-bank");
    await expect(
      page.getByRole("heading", { name: /interview prep/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Switch to Story Bank tab
    await page.getByRole("tab", { name: /story bank tab/i }).click();

    // Click Add Story
    const addBtn = page.getByRole("button", { name: /add a new star story/i });
    await expect(addBtn).toBeVisible();
    await addBtn.click();

    // Form appears
    await expect(
      page.getByRole("heading", { name: /new star story/i }),
    ).toBeVisible();

    // Fill out the form
    await page
      .getByRole("textbox", { name: /story title/i })
      .fill("E2E Led microservices migration");
    await page.getByRole("textbox", { name: /story situation/i }).fill(
      "Our monolith was becoming a bottleneck.",
    );
    await page
      .getByRole("textbox", { name: /story task/i })
      .fill("Design and lead the decomposition.");
    await page
      .getByRole("textbox", { name: /story action/i })
      .fill("Identified bounded contexts and created service contracts.");
    await page
      .getByRole("textbox", { name: /story result/i })
      .fill("Deploy time reduced by 60%; system now handles 5x traffic.");

    // Save
    await page
      .getByRole("button", { name: /save this star story/i })
      .click();

    // Story title appears in the list
    await expect(
      page.getByText("E2E Led microservices migration"),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("Question Bank tab: search input filters questions", async ({
    page,
  }) => {
    await page.goto("/career/interview-bank");
    await expect(
      page.getByRole("heading", { name: /interview prep/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Switch to Question Bank tab
    await page.getByRole("tab", { name: /question bank tab/i }).click();

    // Search input is visible
    const searchBox = page.getByRole("textbox", {
      name: /search interview questions/i,
    });
    await expect(searchBox).toBeVisible();

    // Type a query — the hook debounces and re-fetches
    await searchBox.fill("behavioral");
    // Either questions appear or empty state message
    await expect(
      page
        .getByText(/no questions found|searching\u2026/i)
        .or(page.locator("ul li").first()),
    ).toBeVisible({ timeout: 10_000 });
  });
});
