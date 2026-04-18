"""Standalone runner for 3B #4 diagnostic-CTA normalization helper."""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).parent
MODULE = BACKEND / "app" / "services" / "diagnostic_cta_service.py"
TESTS = BACKEND / "tests" / "test_services" / "test_diagnostic_cta_service.py"


def extract(src: str) -> str:
    tree = ast.parse(src)
    kept: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith(("sqlalchemy", "app.")):
                continue
            kept.append(node)
        elif isinstance(node, ast.Import):
            kept.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "normalize_decision":
            kept.append(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t == "_VALID_DECISIONS" for t in targets):
                kept.append(node)
    return ast.unparse(ast.Module(body=kept, type_ignores=[]))


def strip_app_and_pytest_imports(src: str) -> str:
    tree = ast.parse(src)
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "app."
        ):
            continue
        if isinstance(node, ast.Import) and any(
            a.name == "pytest" for a in node.names
        ):
            continue
        body.append(node)
    tree.body = body
    return ast.unparse(tree)


class _FakePytest:
    class _Raises:
        def __init__(self, exc: type[BaseException]) -> None:
            self._exc = exc

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            if exc_type is None:
                raise AssertionError(f"expected {self._exc.__name__}")
            return issubclass(exc_type, self._exc)

    @staticmethod
    def raises(exc: type[BaseException]) -> "_FakePytest._Raises":
        return _FakePytest._Raises(exc)


def main() -> int:
    src = MODULE.read_text(encoding="utf-8")
    pure = extract(src)
    ns: dict[str, object] = {}
    exec(compile(pure, str(MODULE), "exec"), ns)

    test_src = strip_app_and_pytest_imports(TESTS.read_text(encoding="utf-8"))
    test_ns: dict[str, object] = {
        "normalize_decision": ns["normalize_decision"],
        "pytest": _FakePytest,
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
