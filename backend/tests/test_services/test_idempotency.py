"""PR2/B6.1 — idempotency helper unit tests.

Confirms:
  - `make_request_hash` is deterministic and order-insensitive.
  - `make_request_hash` salts by user_id so two students saving the
    same payload don't collide.
  - The integration with Redis is exercised separately by the route
    test in `tests/test_routes/test_notebook_idempotent.py`.
"""

from __future__ import annotations

from app.services.idempotency import make_request_hash


def test_hash_is_deterministic() -> None:
    h1 = make_request_hash(user_id="u1", payload={"a": 1, "b": "two"})
    h2 = make_request_hash(user_id="u1", payload={"a": 1, "b": "two"})
    assert h1 == h2
    assert len(h1) == 16
    assert all(c in "0123456789abcdef" for c in h1)


def test_hash_is_key_order_insensitive() -> None:
    h1 = make_request_hash(user_id="u1", payload={"a": 1, "b": 2})
    h2 = make_request_hash(user_id="u1", payload={"b": 2, "a": 1})
    assert h1 == h2


def test_hash_separates_users() -> None:
    payload = {"content": "x"}
    a = make_request_hash(user_id="u1", payload=payload)
    b = make_request_hash(user_id="u2", payload=payload)
    assert a != b


def test_hash_changes_with_payload() -> None:
    a = make_request_hash(user_id="u1", payload={"content": "x"})
    b = make_request_hash(user_id="u1", payload={"content": "y"})
    assert a != b


def test_hash_handles_nested_payload() -> None:
    a = make_request_hash(
        user_id="u1", payload={"content": "x", "tags": ["a", "b"]}
    )
    b = make_request_hash(
        user_id="u1", payload={"content": "x", "tags": ["a", "b"]}
    )
    assert a == b
