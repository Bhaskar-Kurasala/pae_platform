"""ChatPage — generic chat surface at /chat.

Selector strategy: testid-dominant. /chat is the most instrumented
surface in the app today (>60% testid coverage on critical elements);
ChatPage exclusively uses testids for the actions it exposes:
  * conversation-list, edit-textarea, edit-cancel, edit-save,
    edit-open, thinking-agent-dot, thinking-label,
    explain-differently-trigger, explain-differently-menu,
    explain-option-{value}, sibling-navigator,
    message-metadata, message-metadata-trigger,
    message-metadata-popover, routing-affordance,
    routing-override-dropdown, flashcard-button.
The composer textarea is reachable via role=textbox (the testid
`edit-textarea` applies to the edit-mode textarea, not the primary
composer). The mode chips and send button fall back to role+text.

Route: /chat (file: frontend/src/app/(portal)/chat/page.tsx)
"""

from __future__ import annotations

import re

from playwright.sync_api import expect

from .base_page import BasePage


class ChatPage(BasePage):
    path = "/chat"

    def wait_for_loaded(self) -> None:  # type: ignore[override]
        # Stronger readiness signal than the base spinner check: the
        # composer textbox must be visible before any send_message() call.
        composer = self.page.get_by_role("textbox", name=re.compile(r"message", re.IGNORECASE)).first
        expect(composer).to_be_visible(timeout=10_000)

    def send_message(self, text: str) -> None:
        composer = self.page.get_by_role("textbox", name=re.compile(r"message", re.IGNORECASE)).first
        composer.fill(text)
        self.page.keyboard.press("Enter")

    def wait_for_response_complete(self, timeout_ms: int = 30_000) -> None:
        """Wait for streaming to finish (thinking dot disappears)."""
        expect(
            self.page.get_by_test_id("thinking-agent-dot")
        ).to_be_hidden(timeout=timeout_ms)

    def open_explain_differently(self) -> None:
        self.page.get_by_test_id("explain-differently-trigger").first.click()

    def assert_conversation_list_visible(self) -> None:
        expect(self.page.get_by_test_id("conversation-list")).to_be_visible()

    def click_flashcard_button(self) -> None:
        self.page.get_by_test_id("flashcard-button").first.click()
