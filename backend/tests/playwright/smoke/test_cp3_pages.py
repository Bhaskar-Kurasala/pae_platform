"""D18 Phase A CP3 — Page object smoke tests.

Each test exercises at least one method on the corresponding page
object so a Phase B author can read this file as a working example.

Auth: tests that need a session use the temporary CP3 helper at
backend/tests/playwright/pages/_helpers.py. CP4 supersedes those
calls with proper fixtures.

Admin tests (AdminCockpitPage, StudentDetailPanel): the playwright_test
template doesn't yet seed an admin user (CP4 will). Those smoke tests
are marked xfail at CP3 to surface the gap clearly without polluting
the test baseline. Once CP4's admin fixture lands, drop the xfail
markers.

Why no fixtures here: CP4 lands the fixture library (per_test seed +
cleanup, role_state_fixtures, journey_fixtures). CP3 deliberately
keeps smoke surface minimal — page objects + auth helper only.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.playwright.pages import (
    AdminCockpitPage,
    CatalogPage,
    ChatPage,
    LessonPage,
    LoginPage,
    MockInterviewPage,
    StudentDetailPanel,
    TodayPage,
)
from tests.playwright.pages._helpers import (
    login_as_admin,
    login_as_student,
)


# ── No-auth surfaces ────────────────────────────────────────────────


def test_login_page_renders_form(page: Page) -> None:
    """LoginPage smoke: navigate to /login, assert the form is visible."""
    login = LoginPage(page)
    login.navigate()
    login.assert_on_login_page()


def test_catalog_page_renders(page: Page) -> None:
    """CatalogPage smoke: /catalog (public) renders an h1."""
    catalog = CatalogPage(page)
    catalog.navigate()
    catalog.assert_loaded()


# ── Student-auth surfaces ───────────────────────────────────────────


def test_today_page_loads_for_student(page: Page) -> None:
    """TodayPage smoke: authed student lands on /today, page loads."""
    login_as_student(page)
    today = TodayPage(page)
    today.navigate()
    today.assert_loaded()


def test_chat_page_composer_visible_for_student(page: Page) -> None:
    """ChatPage smoke: composer textbox is reachable after auth."""
    login_as_student(page)
    chat = ChatPage(page)
    chat.navigate()
    # wait_for_loaded() asserts the composer is visible.


def test_mock_interview_page_loads_for_student(page: Page) -> None:
    """MockInterviewPage smoke: /interview renders the picker view."""
    login_as_student(page)
    interview = MockInterviewPage(page)
    interview.navigate()
    interview.assert_loaded()


def test_lesson_page_requires_lesson_id(page: Page) -> None:
    """LessonPage smoke: constructing without a lesson_id raises.

    A real lesson_id requires CP4 catalog/lesson fixtures. CP3 only
    asserts the constructor contract works.
    """
    lesson = LessonPage(page, lesson_id=None)
    with pytest.raises(ValueError, match="lesson_id"):
        _ = lesson.path


# ── Admin-auth surfaces (CP4 supersedes) ────────────────────────────


@pytest.mark.xfail(
    reason=(
        "CP3: playwright_test template does not yet seed an admin user. "
        "CP4 fixture-based admin auth will replace login_as_admin and "
        "this xfail can be dropped."
    ),
    strict=False,
)
def test_admin_cockpit_page_loads(page: Page) -> None:
    login_as_admin(page)
    cockpit = AdminCockpitPage(page)
    cockpit.navigate()
    cockpit.assert_loaded()


@pytest.mark.xfail(
    reason=(
        "CP3: opening StudentDetailPanel requires a seeded student row "
        "in the admin cockpit; CP4 fixtures will provide that."
    ),
    strict=False,
)
def test_student_detail_panel_opens(page: Page) -> None:
    login_as_admin(page)
    cockpit = AdminCockpitPage(page)
    cockpit.navigate()
    cockpit.assert_loaded()
    # CP4 will seed at least one student here. For now just construct
    # the panel object to verify import works.
    _ = StudentDetailPanel(page)
