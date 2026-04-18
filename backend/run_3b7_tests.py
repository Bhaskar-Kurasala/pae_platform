"""Standalone runner for 3B #7 first-day-plan helpers.

Pulls pure helpers from two services:
  - first_day_plan_service.{pick_starter_skills, build_plan, _activities_for_day}
  - goal_contract_service.daily_minutes_target  (its dependency)
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).parent
PLAN_MOD = BACKEND / "app" / "services" / "first_day_plan_service.py"
GC_MOD = BACKEND / "app" / "services" / "goal_contract_service.py"
TESTS = BACKEND / "tests" / "test_services" / "test_first_day_plan_service.py"

PLAN_FUNCS = {"pick_starter_skills", "_activities_for_day", "build_plan"}
PLAN_CLASSES = {"PlannedActivity", "FirstDayPlan"}
PLAN_CONSTS = {
    "_PLAN_DAYS",
    "_LESSON_MINUTES",
    "_EXERCISE_MINUTES",
    "_REVIEW_MINUTES",
}

GC_FUNCS = {"daily_minutes_target"}
GC_CONSTS = {"_WEEKLY_HOURS_TO_DAILY_MINUTES"}


def _extract(
    src: str, funcs: set[str], classes: set[str], consts: set[str]
) -> str:
    tree = ast.parse(src)
    kept: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith(("sqlalchemy", "app.", "structlog")):
                continue
            kept.append(node)
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
            if any(n == "structlog" for n in names):
                continue
            kept.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in funcs:
            kept.append(node)
        elif isinstance(node, ast.ClassDef) and node.name in classes:
            kept.append(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t in consts for t in targets):
                kept.append(node)
    return ast.unparse(ast.Module(body=kept, type_ignores=[]))


def strip_app_imports(src: str) -> str:
    tree = ast.parse(src)
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "app."
        ):
            continue
        body.append(node)
    tree.body = body
    return ast.unparse(tree)


def main() -> int:
    gc_pure = _extract(
        GC_MOD.read_text(encoding="utf-8"), GC_FUNCS, set(), GC_CONSTS
    )
    plan_pure = _extract(
        PLAN_MOD.read_text(encoding="utf-8"),
        PLAN_FUNCS,
        PLAN_CLASSES,
        PLAN_CONSTS,
    )

    ns: dict[str, object] = {}
    exec(compile(gc_pure, str(GC_MOD), "exec"), ns)
    # `build_plan` uses daily_minutes_target from same namespace.
    exec(compile(plan_pure, str(PLAN_MOD), "exec"), ns)

    test_src = strip_app_imports(TESTS.read_text(encoding="utf-8"))
    test_ns: dict[str, object] = {
        "build_plan": ns["build_plan"],
        "pick_starter_skills": ns["pick_starter_skills"],
    }
    exec(compile(test_src, str(TESTS), "exec"), test_ns)

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
