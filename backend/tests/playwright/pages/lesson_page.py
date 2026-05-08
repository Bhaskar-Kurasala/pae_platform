"""LessonPage — lesson view at /lessons/[id].

Selector strategy: role-first. The complete/uncomplete toggle has a
clear accessible name ('Complete lesson' / 'Mark incomplete'), prev/
next nav are <a href> with stable text, and the enroll-to-unlock CTA
on 402 has an accessible name. No testid additions needed for CP3.

Route: /lessons/[id]
       (file: frontend/src/app/(portal)/lessons/[id]/page.tsx)
"""

from __future__ import annotations

import re

from playwright.sync_api import expect

from .base_page import BasePage


class LessonPage(BasePage):
    """Page object for a specific lesson.

    Construct with the lesson id; `path` is derived dynamically.
    """

    def __init__(self, page, lesson_id: str | None = None) -> None:
        super().__init__(page)
        self.lesson_id = lesson_id

    @property
    def path(self) -> str:  # type: ignore[override]
        if self.lesson_id is None:
            raise ValueError(
                "LessonPage requires a lesson_id before .navigate(); "
                "construct via LessonPage(page, lesson_id=...)."
            )
        return f"/lessons/{self.lesson_id}"

    def assert_loaded(self) -> None:
        # Either the lesson title heading is visible, or the
        # entitlement gate is visible. Tests assert which they expect.
        expect(self.page.get_by_role("heading", level=1).first).to_be_visible()

    def mark_complete(self) -> None:
        self.page.get_by_role("button", name=re.compile(r"^Complete lesson$")).click()

    def mark_incomplete(self) -> None:
        self.page.get_by_role("button", name=re.compile(r"^Mark incomplete$")).click()

    def go_to_next_lesson(self) -> None:
        self.page.get_by_role("link", name=re.compile(r"^Next", re.IGNORECASE)).click()

    def assert_paywall_visible(self) -> None:
        """402 entitlement-gate state: 'Enroll to unlock' CTA visible."""
        expect(
            self.page.get_by_role("link", name=re.compile(r"Enroll to unlock", re.IGNORECASE))
        ).to_be_visible()
