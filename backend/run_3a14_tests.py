"""Standalone runner for 3A-14 consistency helpers.

The service module imports `AgentAction`, which transitively imports
SQLAlchemy's `BaseRepository` using PEP 695 generic syntax — which
Python 3.10 can't parse. We sidestep by AST-extracting only the pure
helpers from the service and the pure test cases.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).parent
SERVICE = BACKEND / "app" / "services" / "consistency_service.py"
TESTS = BACKEND / "tests" / "test_services" / "test_consistency_service.py"


def extract_pure(src: str, *, names: set[str]) -> str:
    """Keep ast nodes whose top-level name is in `names`, plus imports."""
    tree = ast.parse(src)
    kept: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # skip SQLAlchemy and app-internal imports — they'd fail
            if isinstance(node, ast.ImportFrom) and (
                (node.module or "").startswith("sqlalchemy")
                or (node.module or "").startswith("app.")
            ):
                continue
            kept.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            kept.append(node)
        elif isinstance(node, ast.AsyncFunctionDef) and node.name in names:
            kept.append(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t in names for t in targets):
                kept.append(node)
    module = ast.Module(body=kept, type_ignores=[])
    return ast.unparse(module)


def main() -> int:
    svc_src = SERVICE.read_text(encoding="utf-8")
    svc_pure = extract_pure(
        svc_src, names={"_WINDOW_DAYS", "window_bounds", "count_active_days"}
    )
    # 3.10 compat: datetime.UTC was added in 3.11
    svc_pure = svc_pure.replace(
        "from datetime import UTC, date, datetime, timedelta",
        "from datetime import date, datetime, timedelta, timezone\nUTC = timezone.utc",
    )
    ns: dict[str, object] = {}
    exec(compile(svc_pure, str(SERVICE), "exec"), ns)

    test_src = TESTS.read_text(encoding="utf-8")
    # Remove `from app.services...` line; inject helpers by name
    test_tree = ast.parse(test_src)
    test_body: list[ast.stmt] = []
    for node in test_tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "app."
        ):
            continue
        test_body.append(node)
    test_tree.body = test_body
    test_src_clean = ast.unparse(test_tree)
    test_src_clean = test_src_clean.replace(
        "from datetime import UTC, datetime, timedelta",
        "from datetime import datetime, timedelta, timezone\nUTC = timezone.utc",
    )

    test_ns: dict[str, object] = {
        "window_bounds": ns["window_bounds"],
        "count_active_days": ns["count_active_days"],
    }
    exec(compile(test_src_clean, str(TESTS), "exec"), test_ns)

    passed = 0
    failed: list[tuple[str, str]] = []
    for name, fn in test_ns.items():
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"  ok   {name}")
            except Exception:  # noqa: BLE001
                failed.append((name, traceback.format_exc()))
                print(f"  FAIL {name}")

    print(f"\n{passed} passed, {len(failed)} failed")
    for name, tb in failed:
        print(f"\n--- {name} ---\n{tb}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
