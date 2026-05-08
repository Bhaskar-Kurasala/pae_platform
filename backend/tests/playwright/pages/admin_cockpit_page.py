"""AdminCockpitPage — admin retention surface at /admin.

Selector strategy: role-first with the existing `aria-label="Search
students"` for the search input. Filter chips and pulse-window tabs
are addressed via `get_by_role("button", name=...)` with text patterns
that mirror the existing frontend/e2e admin-console-smoke.spec.ts
suite. The roster table uses `get_by_role("row")` filtered by name.

No frontend testid additions for CP3 — the admin surface has enough
accessible-name coverage that role-based selection is stable for the
critical actions a Phase B journey needs (filter, search, sort, click
into student detail).

Route: /admin (file: frontend/src/app/admin/page.tsx)
"""

from __future__ import annotations

from playwright.sync_api import expect

from .base_page import BasePage


class AdminCockpitPage(BasePage):
    path = "/admin"

    def assert_loaded(self) -> None:
        # The admin landing always renders the "students need a personal
        # nudge" tagline; mirrors the TS e2e smoke pattern.
        expect(
            self.page.get_by_text(
                "students need a personal nudge", exact=False
            ).first
        ).to_be_visible()

    def search_students(self, query: str) -> None:
        self.page.get_by_label("Search students").fill(query)

    def click_filter(self, label: str) -> None:
        """Click a filter chip by visible label (e.g. 'Severe', 'High')."""
        self.page.get_by_role("button", name=label, exact=True).click()

    def select_pulse_window(self, label: str) -> None:
        """Click a pulse window tab. `label` ∈ {'24h', '7d', '30d'}."""
        self.page.get_by_role("button", name=label, exact=True).click()

    def open_student_row(self, student_name: str) -> None:
        """Click into a student's detail panel by visible name."""
        self.page.get_by_role("row", name=student_name).click()
