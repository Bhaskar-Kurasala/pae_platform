"""PracticePage — unified Practice surface at /practice.

Authored at D18 Phase A retrofit-2 (Phase B CP1 inventory) for the
capstone submission journey. Frontend is the v8 unified Practice
surface (`frontend/src/components/v8/screens/practice-screen.tsx`)
which serves both Exercises and Capstone modes from the same screen
with a Monaco editor, run+review buttons, and Save-to-Notebook.

Selector strategy: testid-dominant. /practice is well-instrumented
(15+ existing data-testids on the screen — practice-screen,
mode-exercises, mode-capstone, capstone-lab-{id}, exercise-task-{id},
run-and-review, request-review, save-to-notebook, practice-review,
output-pane, tests-pane). No frontend additions needed for CP1.

Deep-link contract from `/practice/page.tsx:17-21`:
  ?mode=exercises|capstone — opens that mode
  ?task=<exercise_id>      — pre-selects an exercise (Exercises mode)
  ?lab=A|B|C               — legacy My Path link; resolves to ordinal

Routes:
  /practice                  — landing (mode default)
  /practice?mode=capstone    — capstone work surface
  /practice/<problemId>      — focused per-problem view (rare in tests)
"""

from __future__ import annotations

from playwright.sync_api import expect

from .base_page import BasePage


class PracticePage(BasePage):
    path = "/practice"

    def navigate_to_capstone_mode(self) -> None:
        """Open /practice?mode=capstone and wait for the screen.

        Readiness signal is the practice-screen testid (always
        present once the React tree mounts); whether the
        `capstone-rail` testid is visible depends on whether the
        student has a populated capstone bundle. A fresh
        `seed_python_developer_fresh` student has no capstone
        labs → CapstoneRail renders the "No capstone yet"
        empty-state div which DOES NOT carry a stable testid.
        Phase B journey (c) tests should use a fixture-seeded
        student with a real capstone bundle and call
        `assert_capstone_rail_visible()` only then.
        """
        self.page.goto(f"{self.path}?mode=capstone")
        self.wait_for_loaded()

    def wait_for_loaded(self) -> None:  # type: ignore[override]
        # The screen testid is always present once the React tree
        # mounts; mode-specific rails come up after data resolves.
        expect(self.page.get_by_test_id("practice-screen")).to_be_visible(
            timeout=10_000
        )

    def select_capstone_lab(self, lab_id: str) -> None:
        """Click into a specific capstone lab by id.

        `lab_id` matches the backend's lab identifier (whatever the
        capstone bundle exposes — typically a slug). Targets the
        `data-testid="capstone-lab-{lab_id}"` element.
        """
        self.page.get_by_test_id(f"capstone-lab-{lab_id}").first.click()

    def fill_submission(self, code: str) -> None:
        """Replace the editor's contents with `code`.

        Monaco editors don't expose a stable single-input testid;
        we click the editor area then use keyboard shortcuts to
        select-all + paste. This is brittler than testid-based fill
        but Monaco's host element doesn't support `.fill()`.

        For CP1 capstone tests, code content shape doesn't matter —
        the test asserts on the DB row + the agent's evaluation, not
        the code per se. So a minimal placeholder is sufficient.
        """
        # Focus the editor by clicking the practice screen, which
        # activates the Monaco view.
        self.page.get_by_test_id("practice-screen").click()
        # Select-all + replace via keyboard (Monaco intercepts).
        self.page.keyboard.press("ControlOrMeta+a")
        self.page.keyboard.type(code)

    def submit_for_review(self) -> None:
        """Click Run & Review — fires backend run + senior_review agent."""
        self.page.get_by_test_id("run-and-review").click()

    def request_review_only(self) -> None:
        """Click Request review (review without re-running)."""
        self.page.get_by_test_id("request-review").click()

    def wait_for_review_visible(self, timeout_ms: int = 60_000) -> None:
        """Wait for the practice-review panel to render with content.

        Default 60s timeout because senior_review is a real LLM call
        that can take 20-40s under normal conditions. CP1 tests should
        budget for this wall-clock cost.
        """
        review = self.page.get_by_test_id("practice-review")
        expect(review).to_be_visible(timeout=timeout_ms)

    def assert_capstone_mode_active(self) -> None:
        """Assert the capstone mode toggle is selected.

        Works for both populated (capstone-rail visible) and empty
        (no-capstone-yet message) states. Use this when verifying
        the deep-link / mode-switch worked.
        """
        toggle = self.page.get_by_test_id("mode-capstone")
        expect(toggle).to_have_attribute("aria-selected", "true")

    def assert_capstone_rail_visible(self) -> None:
        """Assert the capstone bundle is populated and rail renders.

        Stronger than `assert_capstone_mode_active` — only passes when
        the student has at least one capstone lab. Fixture-seeded
        capstone-eligible students should use this; fresh-registered
        students should use `assert_capstone_mode_active` instead.
        """
        expect(self.page.get_by_test_id("capstone-rail")).to_be_visible()
