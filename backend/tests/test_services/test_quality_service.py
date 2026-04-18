"""Unit tests for the code-quality analyzer (P2-08).

Pure function — no IO, no fixtures. Every assertion pins a specific rule's
behavior on a minimal source fragment.
"""

from __future__ import annotations

from app.services.quality_service import analyze_quality


def _rules(source: str) -> list[str]:
    return [i.rule for i in analyze_quality(source).issues]


def test_clean_code_has_no_issues_and_full_score() -> None:
    source = 'def add(x: int, y: int) -> int:\n    return x + y\n'
    report = analyze_quality(source)
    assert report.issues == []
    assert report.score == 100
    assert "Clean" in report.summary


def test_missing_type_hints_flagged_on_public_function() -> None:
    assert "missing-type-hints" in _rules("def greet(name):\n    return name\n")


def test_missing_type_hints_not_flagged_on_private() -> None:
    assert "missing-type-hints" not in _rules("def _helper(x):\n    return x\n")


def test_bare_except_flagged() -> None:
    source = "def f() -> int:\n    try:\n        return 1\n    except:\n        return 0\n"
    assert "bare-except" in _rules(source)


def test_print_flagged_as_info() -> None:
    rules = _rules("def f() -> None:\n    print('hi')\n")
    assert "print-debug" in rules


def test_mutable_default_arg_flagged() -> None:
    assert "mutable-default" in _rules("def f(x: list = []) -> None:\n    x.append(1)\n")
    assert "mutable-default" in _rules("def f(x: dict = {}) -> None:\n    x.update({})\n")


def test_todo_marker_flagged() -> None:
    source = "def f() -> None:\n    # TODO: fix this\n    return None\n"
    assert "todo-marker" in _rules(source)


def test_syntax_error_returns_single_issue_not_raise() -> None:
    report = analyze_quality("def broken(:\n")
    assert len(report.issues) == 1
    assert report.issues[0].rule == "syntax-error"
    assert report.score == 0


def test_long_function_flagged() -> None:
    body = "\n".join(f"    x{i} = {i}" for i in range(50))
    source = f"def f() -> None:\n{body}\n"
    assert "long-function" in _rules(source)


def test_no_docstring_flagged_on_nontrivial_public() -> None:
    body = "\n".join(f"    x{i} = {i}" for i in range(20))
    source = f"def process(arg: int) -> None:\n{body}\n"
    assert "no-docstring" in _rules(source)


def test_docstring_present_no_flag() -> None:
    body = "\n".join(f"    x{i} = {i}" for i in range(20))
    source = f'def process(arg: int) -> None:\n    """Do the thing."""\n{body}\n'
    assert "no-docstring" not in _rules(source)


def test_score_penalizes_warnings_more_than_infos() -> None:
    warning_source = "def f(x: list = []) -> None:\n    pass\n"
    info_source = "def f() -> None:\n    print('x')\n"
    w = analyze_quality(warning_source).score
    i = analyze_quality(info_source).score
    assert w < i  # warning penalty (−8) > info penalty (−3)


def test_issues_sorted_by_line() -> None:
    source = (
        "def f(x: list = []) -> None:  # line 1\n"
        "    print('x')  # line 2\n"
        "    # TODO: fix  line 3\n"
    )
    lines = [i.line for i in analyze_quality(source).issues]
    assert lines == sorted(lines)


def test_async_function_also_checked() -> None:
    source = "async def fetch(url):\n    return await get(url)\n"
    assert "missing-type-hints" in _rules(source)
