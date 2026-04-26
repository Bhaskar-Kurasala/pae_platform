"""Action router — resolves a verdict's ``next_action.intent`` into a
concrete deep link.

The router is rule-based by design. Every routable destination on the
Job Readiness page registers itself in the ``NextActionCatalog`` below
with a default route + label. The verdict generator picks the intent;
the router picks the URL. This split lets us:

  * change deep links without retraining the prompt
  * deep-link with pre-filled query params (mock mode, JD anchor, etc.)
  * register new destinations (Phase 2 agents) without rewriting the
    verdict prompt

If the LLM emits an unknown intent (the prompt constrains the
vocabulary, but defense-in-depth), we fall back to ``thin_data``
routing rather than ship a verdict with a broken CTA.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

log = structlog.get_logger()

NextActionIntent = Literal[
    "skills_gap",
    "story_gap",
    "interview_gap",
    "jd_target_unclear",
    "ready_but_stalling",
    "thin_data",
    "ready_to_apply",
]


@dataclass(frozen=True)
class CatalogEntry:
    """A single routable destination."""

    intent: str
    route: str
    default_label: str


# The catalog. Routes are FE-side deep links — the readiness page uses
# query strings to pre-select views (e.g. ``?view=interview`` opens the
# Interview Coach). When new agents land, they register here.
_CATALOG: dict[str, CatalogEntry] = {
    "skills_gap": CatalogEntry(
        intent="skills_gap",
        route="/courses",
        default_label="Open the next lesson",
    ),
    "story_gap": CatalogEntry(
        intent="story_gap",
        route="/readiness?view=resume",
        default_label="Open the Resume Lab",
    ),
    "interview_gap": CatalogEntry(
        intent="interview_gap",
        route="/readiness?view=interview",
        default_label="Run a mock interview",
    ),
    "jd_target_unclear": CatalogEntry(
        intent="jd_target_unclear",
        route="/readiness?view=jd",
        default_label="Decode a JD",
    ),
    "ready_but_stalling": CatalogEntry(
        intent="ready_but_stalling",
        route="/readiness?view=interview&warmup=1",
        default_label="Warm up with a mock, then apply",
    ),
    "thin_data": CatalogEntry(
        intent="thin_data",
        route="/today",
        default_label="Build a week of activity",
    ),
    "ready_to_apply": CatalogEntry(
        intent="ready_to_apply",
        route="/readiness?view=kit",
        default_label="Open the Application Kit",
    ),
}


@dataclass(frozen=True)
class RoutedAction:
    intent: str
    route: str
    label: str


def route_intent(
    intent: str | None,
    *,
    suggested_label: str | None = None,
) -> RoutedAction:
    """Resolve an intent to a concrete RoutedAction.

    *suggested_label* is the label the verdict generator wrote. When
    valid (non-empty, ≤120 chars), it wins over the catalog's default;
    otherwise we fall back to the catalog default. This keeps the
    final CTA imperative-voiced (per the verdict prompt) without
    sacrificing safety.
    """
    if not intent or intent not in _CATALOG:
        log.info(
            "readiness_action_router.unknown_intent",
            intent=intent,
            fallback="thin_data",
        )
        entry = _CATALOG["thin_data"]
        return RoutedAction(
            intent=entry.intent,
            route=entry.route,
            label=entry.default_label,
        )

    entry = _CATALOG[intent]
    label = (
        suggested_label.strip()
        if suggested_label and suggested_label.strip()
        else entry.default_label
    )
    if len(label) > 120:
        label = label[:117] + "…"
    return RoutedAction(intent=entry.intent, route=entry.route, label=label)


def known_intents() -> tuple[str, ...]:
    return tuple(_CATALOG.keys())


__all__ = [
    "CatalogEntry",
    "NextActionIntent",
    "RoutedAction",
    "known_intents",
    "route_intent",
]
