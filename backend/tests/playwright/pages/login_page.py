"""LoginPage — auth surface.

Selector strategy: pure role-based. The form has well-wired
`<label htmlFor>` pairs and an accessible submit button name, so
get_by_label / get_by_role resolves every critical element without
needing testids. No frontend additions needed for CP3.

Route: /login (file: frontend/src/app/(public)/login/page.tsx)
"""

from __future__ import annotations

from playwright.sync_api import expect

from .base_page import BasePage


class LoginPage(BasePage):
    path = "/login"

    def fill_credentials(self, *, email: str, password: str) -> None:
        self.page.get_by_label("Email").fill(email)
        self.page.get_by_label("Password").fill(password)

    def submit(self) -> None:
        self.page.get_by_role("button", name="Sign in").click()

    def login(self, *, email: str, password: str) -> None:
        """Convenience: fill + submit."""
        self.fill_credentials(email=email, password=password)
        self.submit()

    def assert_on_login_page(self) -> None:
        expect(
            self.page.get_by_role("heading", name="Welcome back")
        ).to_be_visible()
