"""D18 Phase A CP3 — Page object base class.

All page objects in `backend/tests/playwright/pages/` inherit from
BasePage. The base owns the shared selector vocabulary (loading
spinner, error toast) plus a small set of cross-cutting methods used
by every page (navigate, wait_for_loading_done, assert_no_console_errors).

Selector convention (Path C, ratified at D18 Phase A CP3):

  * Role-first via Playwright's `get_by_role` / `get_by_label` /
    `get_by_text`. Mirrors the existing frontend/e2e TS suite.
  * `data-testid` only where role-based selection is genuinely
    insufficient (state-driven elements with no accessible name,
    dynamic disambiguation, badges/chips that share a parent role).
  * If a page object needs a testid that doesn't exist on the
    frontend, two paths:
      - Trivial 1-line addition: add inline as part of the CP3
        commit; cite the page object that needs it in the diff.
      - Non-trivial: register at
        docs/followups/frontend-testid-additions-d18.md with the
        specific element + context.

Per-page object selector strategy is documented in each subclass's
docstring so Phase B authors can read the page object and immediately
know whether they're following a stable API or an evolving one.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

# Cross-cutting selectors shared by all surfaces. Kept in module-level
# constants so tests can import them directly when they need raw access
# (the page object methods below are the primary API).
LOADING_SPINNER_TESTID = "loading-spinner"
ERROR_TOAST_ROLE = "alert"


class BasePage:
    """Shared base for every page object in the suite.

    Subclasses declare a class-level `path` attribute (e.g. "/login")
    and may override `wait_for_loaded()` to add per-page readiness
    checks beyond the default loading-spinner-gone signal.
    """

    path: str = "/"

    def __init__(self, page: Page) -> None:
        self.page = page

    # ── Navigation ──────────────────────────────────────────────────
    def navigate(self, *, wait_for_loaded: bool = True) -> None:
        """Navigate to this page's `path` and (by default) wait for load.

        Tests that need to assert mid-load state (e.g. spinner visible)
        can pass `wait_for_loaded=False`.
        """
        self.page.goto(self.path)
        if wait_for_loaded:
            self.wait_for_loaded()

    def wait_for_loaded(self) -> None:
        """Default page-loaded signal: any global loading spinner is gone.

        Subclasses with stronger readiness signals (e.g. ChatPage waits
        for the textarea to be visible) override this. The default is
        cheap and safe for surfaces without a known per-page sentinel.
        """
        self.wait_for_loading_done()

    # ── Cross-cutting helpers ───────────────────────────────────────
    def wait_for_loading_done(self, timeout_ms: int = 10_000) -> None:
        """Wait until any element with data-testid=loading-spinner is hidden.

        Uses `expect(...).to_be_hidden(...)` instead of a polling loop
        so flake messages are clear ("expected hidden, was visible").
        """
        spinner = self.page.get_by_test_id(LOADING_SPINNER_TESTID)
        # If the spinner never mounts at all, to_be_hidden passes
        # immediately; if it mounts and then unmounts, it waits.
        expect(spinner).to_be_hidden(timeout=timeout_ms)

    def assert_no_console_errors(self) -> None:
        """Assert the page has no captured console errors.

        Phase B may extend this — CP3 ships a stub that lets tests
        call the method without it failing on surfaces that haven't
        wired console capture yet. Wiring console capture is a CP5
        concern (assertion helpers / budget tracking).
        """
        # Stub for CP3. CP5 lands the real implementation.
        # Intentionally a no-op so tests can call it today and the
        # call site doesn't change when CP5 wires real capture.
        return

    def expect_error_toast(self, message_substring: str | None = None) -> None:
        """Assert an error toast (role=alert) is visible.

        If `message_substring` is given, the toast text must contain it.
        Used by tests that exercise failure paths.
        """
        toast = self.page.get_by_role(ERROR_TOAST_ROLE)
        expect(toast).to_be_visible()
        if message_substring is not None:
            expect(toast).to_contain_text(message_substring)
