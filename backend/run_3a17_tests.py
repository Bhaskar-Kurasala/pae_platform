"""Standalone runner for 3A-17 micro-wins pure helpers.

Like 3A-14's runner, we AST-extract only the pure helpers + dataclass
since the service imports SQLAlchemy models (which transitively trip
PEP 695 generic syntax on Python 3.10).
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).parent
SERVICE = BACKEND / "app" / "services" / "micro_wins_service.py"
TESTS = BACKEND / "tests" / "test_services" / "test_micro_wins_service.py"

PURE_NAMES = {
    "WinKind",
    "_WINDOW_HOURS",
    "_MAX_WINS",
    "MicroWin",
    "window_start",
    "rank_wins",
    "format_misconception_label",
    "format_lesson_label",
    "format_hard_exercise_label",
}


def extract_pure(src: str, *, names: set[str]) -> str:
    tree = ast.parse(src)
    kept: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
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
        elif isinstance(node, ast.ClassDef) and node.name in names:
            kept.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets: list[str] = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
            if any(t in names for t in targets):
                kept.append(node)
    module = ast.Module(body=kept, type_ignores=[])
    return ast.unparse(module)


def py310_compat(src: str) -> str:
    return src.replace(
        "from datetime import UTC, datetime, timedelta",
        "from datetime import datetime, timedelta, timezone\nUTC = timezone.utc",
    ).replace(
        "from datetime import UTC, date, datetime, timedelta",
        "from datetime import date, datetime, timedelta, timezone\nUTC = timezone.utc",
    )


def main() -> int:
    svc_src = SERVICE.read_text(encoding="utf-8")
    svc_pure = py310_compat(extract_pure(svc_src, names=PURE_NAMES))
    ns: dict[str, object] = {}
    exec(compile(svc_pure, str(SERVICE), "exec"), ns)

    test_src = TESTS.read_text(encoding="utf-8")
    test_tree = ast.parse(test_src)
    test_body: list[ast.stmt] = []
    for node in test_tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "app."
        ):
            continue
        test_body.append(node)
    test_tree.body = test_body
    test_src_clean = py310_compat(ast.unparse(test_tree))

    test_ns: dict[str, object] = {
        name: ns[name]
        for name in (
            "MicroWin",
            "window_start",
            "rank_wins",
            "format_misconception_label",
            "format_lesson_label",
            "format_hard_exercise_label",
        )
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
