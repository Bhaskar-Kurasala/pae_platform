"""Regression guards for the free_tier_grants INSERT path.

Origin: auth-signup-grace-jsonb investigation (2026-05-13). The
``:meta::jsonb`` cast pattern collided with SQLAlchemy /
asyncpg named-parameter parsing, raising
``PostgresSyntaxError: syntax error at or near ':'`` and
silently shortchanging signup_grace + placement_quiz_session
grants for ~10 days post-D9 (commit 1df4b3d, 2026-05-03 →
fix in this commit).

The fix dropped the explicit ``::jsonb`` cast; Postgres
auto-casts to the column type at INSERT. The test below pins
the inverse contract: **the source SQL must not contain
``::jsonb``** — if anyone re-adds the cast (defensive habit,
copy-paste from one of the alembic migrations where
``'{}'::jsonb`` is a valid server_default literal), this test
fails immediately.

Test shape choice (vs live-DB integration):

  * The conftest's ``db_session`` fixture binds SQLite, which
    happily accepts ``:meta::jsonb`` because the JSONB cast is
    Postgres-only and SQLite is permissive — so a live-DB
    integration test on the unit-test fixture wouldn't catch
    the regression.
  * The playwright_test DB IS Postgres and would catch the
    regression at run time, but that's the Phase B journey
    suite (expensive — real-LLM cost; not appropriate for a
    cheap unit-level regression guard).
  * Lexical assertion against the SQL strings is the cheapest
    and most deterministic gate: 0.01s; fails the moment the
    regression resurfaces; documents the discipline in-place.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap

from app.services.entitlement_service import (
    grant_placement_quiz_session,
    grant_signup_grace,
)


def _sql_strings(fn: object) -> list[str]:
    """Return every string literal passed as the first argument of
    a ``text(...)`` call inside the function's source.

    Uses Python's ``ast`` to parse the function body — bypasses
    docstrings + comments + implicit-string-concatenation quirks.
    A multi-line concatenated string ``text("INSERT ..." "VALUES ...")``
    becomes one logical SQL statement (Python concatenates at
    parse time; the AST sees a single ``Constant(s=...)``).

    Critically: this inspects the actual AST nodes inside text()
    calls, NOT raw source text. Comments + docstrings explaining
    why the SQL is shaped a particular way can mention '::jsonb'
    freely without tripping the guard.
    """
    source = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(source)
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match calls whose callee is named `text` (either bare
        # `text(...)` or `sql_text(...)` aliases — entitlement_service
        # uses bare `text`).
        callee = node.func
        callee_name: str | None = None
        if isinstance(callee, ast.Name):
            callee_name = callee.id
        elif isinstance(callee, ast.Attribute):
            callee_name = callee.attr
        if callee_name not in {"text", "sql_text"}:
            continue
        if not node.args:
            continue
        first = node.args[0]
        # ast.Constant for normal string literals; multi-line
        # implicit-concatenation already collapsed by the parser.
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            out.append(first.value)
    return out


def test_signup_grace_insert_does_not_use_double_colon_jsonb_cast() -> None:
    """auth-signup-grace-jsonb regression guard.

    SQL-level check: the actual SQL string(s) passed to text()
    must not contain '::jsonb'. asyncpg / SQLAlchemy text-mode
    parses ':meta::jsonb' as the parameter ':meta' followed by
    another colon-introduced reference, raising
    PostgresSyntaxError at INSERT time. Drop the cast; the JSONB
    column auto-casts the JSON-shaped text payload. See
    docs/operations/auth-signup-grace-jsonb-investigation.md.
    """
    sqls = _sql_strings(grant_signup_grace)
    assert sqls, (
        "grant_signup_grace doesn't appear to call text(...) — has "
        "the SQL builder changed shape? Update this test alongside."
    )
    for stmt in sqls:
        assert "::jsonb" not in stmt, (
            f"auth-signup-grace-jsonb REGRESSION: '::jsonb' cast "
            f"re-introduced in a SQL statement: {stmt!r}"
        )


def test_placement_quiz_session_insert_does_not_use_double_colon_jsonb_cast() -> None:
    """Companion guard for grant_placement_quiz_session — same bug
    pattern; same fix; same regression surface. Pinned
    independently because each insert site is independently
    re-introducable."""
    sqls = _sql_strings(grant_placement_quiz_session)
    assert sqls
    for stmt in sqls:
        assert "::jsonb" not in stmt, (
            f"auth-signup-grace-jsonb companion REGRESSION: '::jsonb' "
            f"cast re-introduced in: {stmt!r}"
        )


def test_signup_grace_insert_uses_meta_bind_parameter_form() -> None:
    """Positive-shape: the INSERT statement uses the cast-free
    bind form '(... :meta)' verified end-to-end against the dev
    Postgres at investigation time. Catches drift in the opposite
    direction — e.g., someone wrapping the bind with a SQLAlchemy
    cast(:meta, JSONB) that doesn't resolve the root colon-parse
    issue."""
    sqls = _sql_strings(grant_signup_grace)
    insert_stmt = next((s for s in sqls if "INSERT INTO free_tier_grants" in s), None)
    assert insert_stmt is not None, (
        f"No INSERT INTO free_tier_grants statement found; sqls={sqls!r}"
    )
    # VALUES tuple ends with ':exp, :meta)' — the post-fix shape.
    assert re.search(r":exp,\s*:meta\)", insert_stmt), (
        f"grant_signup_grace INSERT shape drift: VALUES tuple no "
        f"longer ends with ':exp, :meta)'. Actual SQL: {insert_stmt!r}"
    )
