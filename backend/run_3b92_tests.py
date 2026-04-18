"""Standalone runner for 3B #92 fading-scaffolds helpers."""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).parent
MODULE = BACKEND / "app" / "services" / "fading_scaffolds_service.py"
TESTS = BACKEND / "tests" / "test_services" / "test_fading_scaffolds_service.py"


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
    # Module is already pure — no sqlalchemy/app imports.
    src = MODULE.read_text(encoding="utf-8")
    ns: dict[str, object] = {}
    exec(compile(src, str(MODULE), "exec"), ns)

    test_src = strip_app_imports(TESTS.read_text(encoding="utf-8"))
    test_ns: dict[str, object] = {
        "allowed_hint_count": ns["allowed_hint_count"],
        "fade_scaffolds": ns["fade_scaffolds"],
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
