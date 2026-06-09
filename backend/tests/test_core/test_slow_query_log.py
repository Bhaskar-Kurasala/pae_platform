"""PR3/C8.1 — slow-query SQLAlchemy event hook test.

Verifies:
  1. A query that runs *under* the threshold does NOT emit a warning.
  2. A query that runs *over* the threshold emits a structlog warning
     with `event="slow_query"`, the SQL preview, the parameters preview,
     and a `duration_ms` field.
  3. The truncation helper bounds SQL and params at the documented
     character limits so a 1MB blob doesn't blow up a log line.

We don't need a real Postgres for this — SQLAlchemy fires
`before/after_cursor_execute` on any engine. The test uses an in-memory
SQLite engine, attaches the same listener via `_attach_slow_query_logger`,
and pumps a query through it. To force the "slow" path we monkey-patch
`SLOW_QUERY_THRESHOLD_MS` down to 0.0 so any query exceeds it.

structlog is configured with `PrintLoggerFactory` (see
`app/core/logging.py`) so log lines land on stdout, not stdlib logging.
We assert against `capsys.readouterr().out`.
"""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text

from app.core import database as db_module


def test_truncate_under_limit_passthrough() -> None:
    out = db_module._truncate("hello", 100)
    assert out == "hello"


def test_truncate_over_limit_appends_suffix() -> None:
    huge = "x" * 1000
    out = db_module._truncate(huge, 100)
    assert out.startswith("x" * 100)
    assert "[+900 chars]" in out
    assert len(out) == 100 + len("…[+900 chars]")


def _slow_query_lines(stdout: str) -> list[dict]:
    """Pull out every JSON log line whose `event` is `slow_query`."""
    matches: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "slow_query":
            matches.append(record)
    return matches


def test_slow_query_logs_when_threshold_exceeded(
    monkeypatch, capsys
) -> None:
    """A query exceeding the threshold emits a `slow_query` log line."""
    monkeypatch.setattr(db_module, "SLOW_QUERY_THRESHOLD_MS", 0.0)

    engine = create_engine("sqlite:///:memory:")
    db_module._attach_slow_query_logger(engine)

    with engine.connect() as conn:
        conn.execute(text("SELECT 1 AS one"))

    out = capsys.readouterr().out
    matched = _slow_query_lines(out)
    assert matched, f"Expected a slow_query log line, got: {out!r}"
    record = matched[0]
    assert record["level"] == "warning"
    assert record["sql"] == "SELECT 1 AS one"
    assert "duration_ms" in record
    assert "threshold_ms" in record
    assert record["executemany"] is False


def test_fast_query_emits_nothing(monkeypatch, capsys) -> None:
    """A query under the threshold does NOT log a warning."""
    # Threshold higher than any plausible local SELECT
    monkeypatch.setattr(db_module, "SLOW_QUERY_THRESHOLD_MS", 60_000)

    engine = create_engine("sqlite:///:memory:")
    db_module._attach_slow_query_logger(engine)

    with engine.connect() as conn:
        conn.execute(text("SELECT 1 AS one"))

    out = capsys.readouterr().out
    matched = _slow_query_lines(out)
    assert matched == [], (
        f"Expected no slow_query line under the high threshold, got: {matched!r}"
    )
