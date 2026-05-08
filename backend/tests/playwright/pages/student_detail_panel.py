"""StudentDetailPanel — admin per-student detail view.

Component (not standalone route) at frontend/src/app/admin/_components/
student-detail-panel.tsx. Opened by clicking a row on AdminCockpitPage.

Selector strategy: pure role-first. The agent-trigger dropdown is a
shadcn Select with `aria-label="Agent to trigger"` already wired,
options are addressable by visible label. Buttons + textareas have
accessible names. Existing `data-testid="channel-badge-{channel}"`
on activity timeline rows is reused unchanged. No new frontend
additions for CP3.

Route: /admin (component opened via row click)
"""

from __future__ import annotations

from playwright.sync_api import expect

from .base_page import BasePage


class StudentDetailPanel(BasePage):
    """Component object — has no `path` since it's modal/inline.

    Tests should open the panel via AdminCockpitPage.open_student_row()
    before constructing this object.
    """

    path = "/admin"  # parent route; navigate() is rarely used directly

    def assert_open(self) -> None:
        # The panel always renders the agent dropdown when open; use
        # its aria-label as the readiness signal.
        expect(
            self.page.get_by_label("Agent to trigger")
        ).to_be_visible()

    def trigger_agent(self, label: str) -> None:
        """Open the dropdown and pick an agent option by visible label.

        `label` ∈ {'Re-engage', 'Weekly report', 'Suggest path',
        'Celebrate milestone'} — exact strings used by the frontend
        TRIGGERABLE_AGENTS table at student-detail-panel.tsx:73.
        """
        self.page.get_by_label("Agent to trigger").click()
        self.page.get_by_role("option", name=label).click()

    def send_refund_offer(self, *, reason: str) -> None:
        # Refund button has accessible name; reason input is a
        # standard textarea reachable by label.
        self.page.get_by_role("button", name="Send refund offer").click()
        self.page.get_by_label("Reason").fill(reason)
        self.page.get_by_role("button", name="Submit").click()

    def add_admin_note(self, text: str) -> None:
        self.page.get_by_label("Admin notes").fill(text)
        self.page.get_by_role("button", name="Save note").click()

    def send_direct_message(self, text: str) -> None:
        self.page.get_by_label("Direct message").fill(text)
        self.page.get_by_role("button", name="Send").click()

    def find_timeline_event(self, *, channel: str) -> None:
        """Assert at least one timeline row with the given channel badge."""
        expect(
            self.page.get_by_test_id(f"channel-badge-{channel}").first
        ).to_be_visible()
