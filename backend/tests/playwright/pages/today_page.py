"""TodayPage — student dashboard at /today.

Selector strategy: role-first with two inline testid additions for
state-driven elements that have no stable accessible name:
  * `data-testid="today-capstone-trailer"` on the capstone teaser
    section (frontend/src/components/v8/screens/today-screen.tsx).
  * `data-testid="today-step-{kind}"` on each step toggle (warmup,
    lesson, reflect).
Both additions are 1-line attribute additions per Path C policy. See
docs/followups/frontend-testid-additions-d18.md for the rationale.

Capstone note: The capstone teaser is a non-functional card today
(Preview brief button has no onclick). The page object exposes only
read-only assertions on the teaser; submission flow is at
/practice?mode=capstone — see
docs/followups/capstone-submission-frontend-not-built.md.

Route: /today (file: frontend/src/app/(portal)/today/page.tsx
        → component: frontend/src/components/v8/screens/today-screen.tsx)
"""

from __future__ import annotations

from playwright.sync_api import expect

from .base_page import BasePage


class TodayPage(BasePage):
    path = "/today"

    def assert_loaded(self) -> None:
        """Today screen has loaded enough that header content is visible.

        Today renders progressively — we only need the top section to
        consider the page interactive.
        """
        # The greeting heading is always rendered once data resolves.
        expect(
            self.page.get_by_role("heading", level=1)
        ).to_be_visible()

    def assert_capstone_trailer_visible(self) -> None:
        """The capstone teaser card is mounted (whether or not it's clickable).

        Uses the testid added at CP3 to disambiguate from other
        sections with similar visual structure.
        """
        expect(
            self.page.get_by_test_id("today-capstone-trailer")
        ).to_be_visible()

    def click_step(self, kind: str) -> None:
        """Click a step toggle. `kind` ∈ {"warmup", "lesson", "reflect"}.

        Uses the per-kind testid (added at CP3) — role-based selection
        wouldn't disambiguate three identically-shaped step cards.
        """
        self.page.get_by_test_id(f"today-step-{kind}").click()
