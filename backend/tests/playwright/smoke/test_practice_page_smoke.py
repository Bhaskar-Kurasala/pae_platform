"""D18 Phase A retrofit-2 smoke — PracticePage.

Two smoke tests verifying PracticePage works end-to-end against the
runner overlay topology:

  1. test_practice_page_loads — bare navigate + assert_loaded;
     verifies the page object's readiness signal works against the
     real /practice screen for an authed student.
  2. test_practice_page_capstone_mode — navigate_to_capstone_mode;
     verifies the deep-link `?mode=capstone` lands on the capstone
     rail (the work surface for D18 Phase B journey c).

Does NOT exercise:
  * Submit + senior_review flow — that's an LLM-cost path, deferred
    to the actual Phase B CP1 journey (c) test where the cost is
    budgeted (~₹2-3).
  * Editor-fill mechanics — Monaco interaction is brittle to verify
    in isolation; covered when a real journey test exercises it.

Cost: ~₹0 (no LLM, no agent invocations).
"""

from __future__ import annotations

from playwright.sync_api import Page

from tests.playwright.pages import PracticePage
from tests.playwright.pages._helpers import login_as_student


def test_practice_page_loads(page: Page) -> None:
    """PracticePage smoke: authed student lands on /practice."""
    login_as_student(page)
    practice = PracticePage(page)
    practice.navigate()
    # wait_for_loaded asserts practice-screen testid is visible.


def test_practice_page_capstone_mode(page: Page) -> None:
    """PracticePage smoke: ?mode=capstone deep-link activates the mode.

    Asserts the mode toggle landed on capstone for a fresh student.
    Does NOT assert the populated rail — fresh `login_as_student`
    has no capstone bundle and renders the empty-state div (no
    testid). Phase B journey (c) tests with fixture-seeded
    capstone-eligible students should use
    `assert_capstone_rail_visible()` for the stronger assertion.
    """
    login_as_student(page)
    practice = PracticePage(page)
    practice.navigate_to_capstone_mode()
    practice.assert_capstone_mode_active()
