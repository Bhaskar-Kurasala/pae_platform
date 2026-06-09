"""CatalogPage — course catalog at /catalog.

Renamed from CoursePage at D18 Phase A CP3: /courses redirects to
/catalog, so /catalog is the actual surface. The /courses → /catalog
redirect is a Phase B journey concern, not a CP3 page-object concern.

Selector strategy: role-first. Course cards are addressed via
`get_by_role("link")` filtered by visible course title, which is
stable since titles are content (instructor-authored, slow-changing).
No testid additions needed for CP3.

Route: /catalog (file: frontend/src/app/(public)/catalog/page.tsx)
"""

from __future__ import annotations

from playwright.sync_api import expect

from .base_page import BasePage


class CatalogPage(BasePage):
    path = "/catalog"

    def assert_loaded(self) -> None:
        # Catalog renders an h1 with "Catalog" or similar; relax to
        # any h1 to avoid coupling to copy.
        expect(
            self.page.get_by_role("heading", level=1).first
        ).to_be_visible()

    def open_course(self, *, title: str) -> None:
        """Click into a course detail page by visible title."""
        self.page.get_by_role("link", name=title).click()

    def assert_course_visible(self, *, title: str) -> None:
        expect(self.page.get_by_role("link", name=title)).to_be_visible()
