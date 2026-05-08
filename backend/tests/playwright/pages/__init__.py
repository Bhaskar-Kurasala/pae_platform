"""Page object models — D18 Phase A CP3.

Selector convention (Path C, ratified at CP3):
  * Role-first via Playwright's get_by_role / get_by_label / get_by_text.
  * data-testid where role-based selection is genuinely insufficient
    (state-driven elements, dynamic disambiguation, badges).
  * If a page object needs a testid the frontend doesn't have:
    - Trivial 1-line addition: inline as part of the CP3 commit.
    - Non-trivial: register at
      docs/followups/frontend-testid-additions-d18.md.

See base_page.BasePage for shared methods (navigate, wait_for_loaded,
assert_no_console_errors, expect_error_toast).
"""

from .admin_cockpit_page import AdminCockpitPage
from .base_page import BasePage
from .catalog_page import CatalogPage
from .chat_page import ChatPage
from .lesson_page import LessonPage
from .login_page import LoginPage
from .mock_interview_page import MockInterviewPage
from .student_detail_panel import StudentDetailPanel
from .today_page import TodayPage

__all__ = [
    "AdminCockpitPage",
    "BasePage",
    "CatalogPage",
    "ChatPage",
    "LessonPage",
    "LoginPage",
    "MockInterviewPage",
    "StudentDetailPanel",
    "TodayPage",
]
