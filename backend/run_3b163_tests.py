"""Standalone runner for 3B #163 Redis key namespacing.

The core/redis module imports `redis.asyncio` which isn't in the
sandbox Python; extract only `namespaced_key` and its module-level
constants, then test against a stub settings object.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).parent
MODULE = BACKEND / "app" / "core" / "redis.py"


def extract(src: str) -> str:
    tree = ast.parse(src)
    kept: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            ("redis", "app.")
        ):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            kept.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "namespaced_key":
            kept.append(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(
                t in {"_NAMESPACE_PREFIX", "_KEY_CATEGORIES"} for t in targets
            ):
                kept.append(node)
    return ast.unparse(ast.Module(body=kept, type_ignores=[]))


def main() -> int:
    src = MODULE.read_text(encoding="utf-8")
    pure = extract(src)

    # Stub `settings` so the helper can reach `.environment`.
    class _Settings:
        environment = "test"

    class _SettingsModule:
        settings = _Settings()

    ns: dict[str, object] = {
        "settings": _Settings(),
    }
    exec(compile(pure, str(MODULE), "exec"), ns)
    namespaced_key = ns["namespaced_key"]

    tests: list[tuple[str, callable]] = []

    def test_prefix_and_env() -> None:
        key = namespaced_key("conv", "abc")
        assert key == "pae:test:conv:abc", key

    def test_multi_part() -> None:
        key = namespaced_key("interview", "session", "s-1")
        assert key == "pae:test:interview:session:s-1", key

    def test_no_trailing_colon_on_category_only() -> None:
        key = namespaced_key("conv")
        assert key == "pae:test:conv", key
        assert not key.endswith(":")

    def test_unknown_category_raises() -> None:
        try:
            namespaced_key("sessions")
        except ValueError as e:
            assert "Unknown redis key category" in str(e)
        else:
            raise AssertionError("expected ValueError")

    def test_environment_swap_isolates_keyspaces() -> None:
        # Same caller, different env → different key.
        k_test = namespaced_key("courses", "published")
        ns["settings"].environment = "prod"
        k_prod = namespaced_key("courses", "published")
        ns["settings"].environment = "test"  # restore
        assert k_test != k_prod
        assert k_test.startswith("pae:test:")
        assert k_prod.startswith("pae:prod:")

    tests = [
        ("test_prefix_and_env", test_prefix_and_env),
        ("test_multi_part", test_multi_part),
        ("test_no_trailing_colon_on_category_only", test_no_trailing_colon_on_category_only),
        ("test_unknown_category_raises", test_unknown_category_raises),
        ("test_environment_swap_isolates_keyspaces", test_environment_swap_isolates_keyspaces),
    ]

    passed = 0
    failed: list[tuple[str, str]] = []
    for name, fn in tests:
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
