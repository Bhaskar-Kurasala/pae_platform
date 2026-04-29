"""PR1/A3.1 — Schema↔UI invariant tests for every aggregator endpoint.

Each aggregator endpoint (the "single round-trip" routes that hydrate an
entire screen — Today, Path, Promotion, Readiness Overview, Catalog,
Notebook summary, etc.) is contract-tested against a declarative shape
spec. The spec mirrors the frontend's TypeScript interface for the
endpoint's response. If the backend ever drops a field the frontend
expects, OR the field type changes shape, this test fails loudly with
the exact field name that drifted.

This is the single highest-value test suite we don't yet have. It
prevents the entire class of "renamed a backend field, frontend rendered
undefined silently" bugs.

## How it works

A spec is a `dict[str, FieldSpec]` where `FieldSpec` is one of:
  - `"required"`        — field must be present, may be any value (incl. null)
  - `"required_nonnull"`— field must be present AND non-null
  - `"optional"`        — field may be present or absent
  - `("list", spec)`    — field is a list; each item must match the inner spec
  - dict                — nested object spec

The walker iterates the spec, checks each rule against the actual JSON,
and accumulates errors. ONE failure per field means a clean diff in CI.

## Sync rule

When a frontend `interface` changes, the matching spec in this file MUST
change in the same PR. Treat the two as a single edit. The spec is
intentionally hand-mirrored (not auto-generated from OpenAPI) because
the goal is to catch *intentional* drift, not document the schema.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Shape spec primitives
# ---------------------------------------------------------------------------

REQUIRED = "required"
REQUIRED_NONNULL = "required_nonnull"
OPTIONAL = "optional"


def list_of(item_spec: Any) -> tuple[str, Any]:
    """Marker for a list field whose every element matches `item_spec`."""
    return ("list", item_spec)


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------


def _walk(
    actual: Any,
    spec: Any,
    path: str,
    errors: list[str],
) -> None:
    if isinstance(spec, str):
        if spec == REQUIRED:
            return  # presence already checked by caller
        if spec == REQUIRED_NONNULL:
            if actual is None:
                errors.append(f"{path}: expected non-null, got null")
            return
        if spec == OPTIONAL:
            return
        errors.append(f"{path}: unknown spec '{spec}'")
        return

    if isinstance(spec, tuple) and spec and spec[0] == "list":
        inner = spec[1]
        if not isinstance(actual, list):
            errors.append(f"{path}: expected list, got {type(actual).__name__}")
            return
        for i, item in enumerate(actual):
            _walk(item, inner, f"{path}[{i}]", errors)
        return

    if isinstance(spec, Mapping):
        if not isinstance(actual, Mapping):
            errors.append(
                f"{path}: expected object, got {type(actual).__name__}"
            )
            return
        for key, sub_spec in spec.items():
            sub_path = f"{path}.{key}" if path else key
            if key not in actual:
                if sub_spec == OPTIONAL:
                    continue
                errors.append(f"{sub_path}: missing field")
                continue
            _walk(actual[key], sub_spec, sub_path, errors)
        return

    errors.append(f"{path}: unhandled spec shape {spec!r}")


def assert_shape(actual: Any, spec: Any, *, label: str) -> None:
    errors: list[str] = []
    _walk(actual, spec, label, errors)
    if errors:
        joined = "\n  ".join(errors)
        raise AssertionError(
            f"Contract violations in {label}:\n  {joined}"
        )


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Contract Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Specs — mirror the frontend TypeScript interfaces. Update both together.
# ---------------------------------------------------------------------------

# TodaySummaryResponse — frontend/src/lib/api-client.ts:1078
TODAY_SUMMARY_SPEC: Mapping[str, Any] = {
    "user": {"first_name": REQUIRED},
    "goal": {
        "success_statement": REQUIRED,
        "target_role": REQUIRED,
        "days_remaining": REQUIRED_NONNULL,
        "motivation": REQUIRED,
    },
    "consistency": {
        "days_active": REQUIRED_NONNULL,
        "window_days": REQUIRED_NONNULL,
    },
    "progress": {
        "overall_percentage": REQUIRED_NONNULL,
        "lessons_completed_total": REQUIRED_NONNULL,
        "lessons_total": REQUIRED_NONNULL,
        "today_unlock_percentage": REQUIRED_NONNULL,
        "active_course_id": REQUIRED,
        "active_course_title": REQUIRED,
        "next_lesson_id": REQUIRED,
        "next_lesson_title": REQUIRED,
    },
    "session": {
        "id": REQUIRED,
        "ordinal": REQUIRED_NONNULL,
        "started_at": REQUIRED,
        "warmup_done_at": REQUIRED,
        "lesson_done_at": REQUIRED,
        "reflect_done_at": REQUIRED,
    },
    "current_focus": {
        "skill_slug": REQUIRED,
        "skill_name": REQUIRED,
        "skill_blurb": REQUIRED,
    },
    "capstone": {
        "exercise_id": REQUIRED,
        "title": REQUIRED,
        "days_to_due": REQUIRED,
        "draft_quality": REQUIRED,
        "drafts_count": REQUIRED_NONNULL,
    },
    "next_milestone": {"label": REQUIRED, "days": REQUIRED_NONNULL},
    "readiness": {"current": REQUIRED_NONNULL, "delta_week": REQUIRED_NONNULL},
    "intention": {"text": REQUIRED},
    "due_card_count": REQUIRED_NONNULL,
    "peers_at_level": REQUIRED_NONNULL,
    "promotions_today": REQUIRED_NONNULL,
    "micro_wins": list_of(
        {
            "kind": REQUIRED_NONNULL,
            "label": REQUIRED_NONNULL,
            "occurred_at": REQUIRED_NONNULL,
        }
    ),
    "cohort_events": list_of(
        {
            "kind": REQUIRED_NONNULL,
            "actor_handle": REQUIRED_NONNULL,
            "label": REQUIRED_NONNULL,
            "occurred_at": REQUIRED_NONNULL,
        }
    ),
}

# PathSummaryResponse — frontend/src/lib/api-client.ts:1611
PATH_SUMMARY_SPEC: Mapping[str, Any] = {
    "overall_progress": REQUIRED_NONNULL,
    "active_course_id": REQUIRED,
    "active_course_title": REQUIRED,
    "constellation": list_of(
        {
            "label": REQUIRED_NONNULL,
            "sub": REQUIRED_NONNULL,
            "state": REQUIRED_NONNULL,
            "badge": REQUIRED_NONNULL,
        }
    ),
    "levels": list_of(
        {
            "badge": REQUIRED_NONNULL,
            "title": REQUIRED_NONNULL,
            "blurb": REQUIRED_NONNULL,
            "progress_percentage": REQUIRED_NONNULL,
            "lessons": list_of(
                {
                    "id": REQUIRED_NONNULL,
                    "title": REQUIRED_NONNULL,
                    "meta": REQUIRED_NONNULL,
                    "duration_minutes": REQUIRED_NONNULL,
                    "status": REQUIRED_NONNULL,
                    "labs": list_of(
                        {
                            "id": REQUIRED_NONNULL,
                            "title": REQUIRED_NONNULL,
                            "description": REQUIRED,
                            "duration_minutes": REQUIRED_NONNULL,
                            "status": REQUIRED_NONNULL,
                        }
                    ),
                    "labs_completed": REQUIRED_NONNULL,
                }
            ),
            "state": REQUIRED_NONNULL,
            "unlock_course_id": REQUIRED,
            "unlock_price_cents": REQUIRED,
            "unlock_currency": REQUIRED,
            "unlock_lesson_count": REQUIRED,
            "unlock_lab_count": REQUIRED,
        }
    ),
    "proof_wall": list_of(
        {
            "submission_id": REQUIRED_NONNULL,
            "code_snippet": REQUIRED_NONNULL,
            "author_name": REQUIRED_NONNULL,
            "score": REQUIRED_NONNULL,
            "promoted": REQUIRED_NONNULL,
        }
    ),
}

# PromotionSummaryResponse — frontend/src/lib/api-client.ts:1658
PROMOTION_SUMMARY_SPEC: Mapping[str, Any] = {
    "overall_progress": REQUIRED_NONNULL,
    "rungs": list_of(
        {
            "kind": REQUIRED_NONNULL,
            "title": REQUIRED_NONNULL,
            "detail": REQUIRED_NONNULL,
            "state": REQUIRED_NONNULL,
            "progress": REQUIRED_NONNULL,
            "short_label": REQUIRED_NONNULL,
        }
    ),
    "role": {
        "from_role": REQUIRED_NONNULL,
        "to_role": REQUIRED_NONNULL,
    },
    "stats": {
        "completed_lessons": REQUIRED_NONNULL,
        "total_lessons": REQUIRED_NONNULL,
        "due_card_count": REQUIRED_NONNULL,
        "completed_interviews": REQUIRED_NONNULL,
        "capstone_submissions": REQUIRED_NONNULL,
    },
    "gate_status": REQUIRED_NONNULL,
    "promoted_at": REQUIRED,
    "promoted_to_role": REQUIRED,
    "user_first_name": REQUIRED,
}

# CatalogResponse — frontend/src/lib/api-client.ts:1446
CATALOG_SPEC: Mapping[str, Any] = {
    "courses": list_of(
        {
            "id": REQUIRED_NONNULL,
            "slug": REQUIRED_NONNULL,
            "title": REQUIRED_NONNULL,
            "description": REQUIRED,
            "price_cents": REQUIRED_NONNULL,
            "currency": REQUIRED_NONNULL,
            "is_unlocked": REQUIRED_NONNULL,
            "bullets": REQUIRED,  # may be empty list
        }
    ),
    "bundles": list_of(
        {
            "id": REQUIRED_NONNULL,
            "slug": REQUIRED_NONNULL,
            "title": REQUIRED_NONNULL,
            "course_ids": REQUIRED_NONNULL,
            "price_cents": REQUIRED_NONNULL,
            "currency": REQUIRED_NONNULL,
        }
    ),
}

# ExerciseResponse list — frontend/src/lib/api-client.ts:270 (ExerciseResponse)
EXERCISES_LIST_ITEM_SPEC: Mapping[str, Any] = {
    "id": REQUIRED_NONNULL,
    "lesson_id": REQUIRED,  # optional in some responses
    "title": REQUIRED_NONNULL,
    "description": REQUIRED,
    "exercise_type": REQUIRED_NONNULL,
    "difficulty": REQUIRED_NONNULL,
    "starter_code": REQUIRED,
    "points": REQUIRED_NONNULL,
    "order": REQUIRED_NONNULL,
}

# NotebookEntryOut list — frontend/src/lib/chat-api.ts (NotebookEntryOut)
NOTEBOOK_ENTRY_SPEC: Mapping[str, Any] = {
    "id": REQUIRED_NONNULL,
    "message_id": REQUIRED,
    "conversation_id": REQUIRED,
    "content": REQUIRED_NONNULL,
    "title": REQUIRED,
    "user_note": REQUIRED,
    "source_type": REQUIRED,
    "topic": REQUIRED,
    "tags": REQUIRED,  # list, may be empty
    "graduated_at": REQUIRED,
    "created_at": REQUIRED_NONNULL,
}

# SRSCard list — frontend/src/lib/api-client.ts:959
SRS_DUE_ITEM_SPEC: Mapping[str, Any] = {
    "id": REQUIRED_NONNULL,
    "concept_key": REQUIRED_NONNULL,
    "prompt": REQUIRED_NONNULL,
    "answer": REQUIRED,  # may be empty string
    "hint": REQUIRED,
    "ease_factor": REQUIRED_NONNULL,
    "interval_days": REQUIRED_NONNULL,
    "repetitions": REQUIRED_NONNULL,
    "next_due_at": REQUIRED_NONNULL,
    "last_reviewed_at": REQUIRED,
}


# ---------------------------------------------------------------------------
# Tests — one per aggregator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_today_summary_contract(client: AsyncClient) -> None:
    token = await _register_and_login(client, "contract.today@test.dev")
    resp = await client.get("/api/v1/today/summary", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert_shape(resp.json(), TODAY_SUMMARY_SPEC, label="TodaySummaryResponse")


@pytest.mark.asyncio
async def test_path_summary_contract(client: AsyncClient) -> None:
    token = await _register_and_login(client, "contract.path@test.dev")
    resp = await client.get("/api/v1/path/summary", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert_shape(resp.json(), PATH_SUMMARY_SPEC, label="PathSummaryResponse")


@pytest.mark.asyncio
async def test_promotion_summary_contract(client: AsyncClient) -> None:
    token = await _register_and_login(client, "contract.promo@test.dev")
    resp = await client.get("/api/v1/promotion/summary", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert_shape(
        resp.json(), PROMOTION_SUMMARY_SPEC, label="PromotionSummaryResponse"
    )


@pytest.mark.asyncio
async def test_catalog_contract(client: AsyncClient) -> None:
    token = await _register_and_login(client, "contract.catalog@test.dev")
    resp = await client.get("/api/v1/catalog/", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert_shape(resp.json(), CATALOG_SPEC, label="CatalogResponse")


@pytest.mark.asyncio
async def test_exercises_list_contract(client: AsyncClient) -> None:
    token = await _register_and_login(client, "contract.ex@test.dev")
    resp = await client.get("/api/v1/exercises", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list), f"expected list, got {type(body).__name__}"
    for i, item in enumerate(body):
        assert_shape(
            item, EXERCISES_LIST_ITEM_SPEC, label=f"ExerciseResponse[{i}]"
        )


@pytest.mark.asyncio
async def test_notebook_list_contract(client: AsyncClient) -> None:
    token = await _register_and_login(client, "contract.nb@test.dev")
    resp = await client.get("/api/v1/chat/notebook", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list), f"expected list, got {type(body).__name__}"
    for i, item in enumerate(body):
        assert_shape(item, NOTEBOOK_ENTRY_SPEC, label=f"NotebookEntryOut[{i}]")


@pytest.mark.asyncio
async def test_srs_due_contract(client: AsyncClient) -> None:
    token = await _register_and_login(client, "contract.srs@test.dev")
    resp = await client.get("/api/v1/srs/due", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list), f"expected list, got {type(body).__name__}"
    for i, item in enumerate(body):
        assert_shape(item, SRS_DUE_ITEM_SPEC, label=f"SRSCard[{i}]")


# ---------------------------------------------------------------------------
# Walker self-tests — guard the test harness itself
# ---------------------------------------------------------------------------


def test_walker_catches_missing_required_field() -> None:
    spec = {"a": REQUIRED, "b": REQUIRED}
    with pytest.raises(AssertionError, match=r"\.b: missing field"):
        assert_shape({"a": 1}, spec, label="self_test")


def test_walker_catches_null_in_required_nonnull() -> None:
    spec = {"a": REQUIRED_NONNULL}
    with pytest.raises(AssertionError, match=r"\.a: expected non-null"):
        assert_shape({"a": None}, spec, label="self_test")


def test_walker_allows_optional_missing() -> None:
    spec = {"a": REQUIRED, "b": OPTIONAL}
    assert_shape({"a": 1}, spec, label="self_test")  # no raise


def test_walker_walks_into_lists() -> None:
    spec = {"items": list_of({"id": REQUIRED_NONNULL})}
    with pytest.raises(AssertionError, match=r"items\[1\]\.id: expected non-null"):
        assert_shape(
            {"items": [{"id": "ok"}, {"id": None}]}, spec, label="self_test"
        )


def test_walker_aggregates_multiple_errors() -> None:
    spec = {"a": REQUIRED_NONNULL, "b": REQUIRED_NONNULL, "c": REQUIRED}
    with pytest.raises(AssertionError) as exc:
        assert_shape({"a": None, "b": None}, spec, label="self_test")
    msg = str(exc.value)
    assert ".a: expected non-null" in msg
    assert ".b: expected non-null" in msg
    assert ".c: missing field" in msg


def test_walker_handles_nested_objects() -> None:
    spec = {"outer": {"inner": {"deep": REQUIRED_NONNULL}}}
    with pytest.raises(
        AssertionError, match=r"outer\.inner\.deep: expected non-null"
    ):
        assert_shape(
            {"outer": {"inner": {"deep": None}}}, spec, label="self_test"
        )


# ---------------------------------------------------------------------------
# Sanity that the type Sequence is referenced (mypy hint when adding new
# spec shapes that need ordered iteration).
# ---------------------------------------------------------------------------
_ = Sequence  # silence unused-import warning if mypy ever runs strict here
