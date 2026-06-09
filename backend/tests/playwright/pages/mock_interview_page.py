"""MockInterviewPage — multi-turn interview UI at /interview.

Selector strategy: role-first for input/send (textarea has a
placeholder; send button has accessible name). One inline testid
addition for the verdict span where role-based selection is
genuinely insufficient:
  * `data-testid="interview-verdict-badge"` on the final verdict
    span — Strong Hire / On the Fence / No Hire are state-dependent
    labels and the span has no stable role/accessible name.
A turn-counter testid was scoped at CP3 design time but the current
UI doesn't render a separate counter element; deferred to whenever
that surface ships.

Route: /interview (file: frontend/src/app/(portal)/interview/page.tsx)
"""

from __future__ import annotations

import re

from playwright.sync_api import expect

from .base_page import BasePage


class MockInterviewPage(BasePage):
    path = "/interview"

    def assert_loaded(self) -> None:
        # The picker view always renders an h1 with "Mock interview"
        # or similar; settle for any visible h1 to avoid copy coupling.
        expect(self.page.get_by_role("heading", level=1).first).to_be_visible()

    def start_interview(self, *, problem_title: str | None = None) -> None:
        """Begin a session, optionally selecting a specific problem first.

        If `problem_title` is None, the first available problem button
        is used.
        """
        if problem_title is not None:
            self.page.get_by_role("button", name=problem_title).click()
        self.page.get_by_role("button", name=re.compile(r"^Start", re.IGNORECASE)).click()

    def send_turn(self, message: str) -> None:
        textarea = self.page.get_by_role("textbox").first
        textarea.fill(message)
        self.page.get_by_role("button", name=re.compile(r"^Send$", re.IGNORECASE)).click()

    def request_debrief(self) -> None:
        self.page.get_by_role("button", name=re.compile(r"Debrief", re.IGNORECASE)).click()

    def assert_verdict_populated(self) -> None:
        """The final verdict badge is visible and has non-empty text."""
        badge = self.page.get_by_test_id("interview-verdict-badge")
        expect(badge).to_be_visible()
        expect(badge).not_to_have_text("")
