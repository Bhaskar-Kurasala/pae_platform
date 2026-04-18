"""Unit tests for the misconception detector (P2-09).

Pure function — every test pins one rule on a minimal, unambiguous fragment.
Explicitly includes *negative* cases: the detector's value is killed by false
positives, so clean code must stay silent.
"""

from __future__ import annotations

from app.services.misconception_service import (
    detect_misconceptions,
    format_overlay,
)


def _codes(source: str) -> list[str]:
    return [m.code for m in detect_misconceptions(source).items]


def test_clean_code_no_findings() -> None:
    source = (
        "def add(x: int, y: int) -> int:\n"
        "    return x + y\n"
    )
    report = detect_misconceptions(source)
    assert report.items == []
    assert "No misconceptions" in report.summary


def test_is_with_string_literal_flagged() -> None:
    assert "is-with-literal" in _codes('def f(x):\n    return x is "foo"\n')


def test_is_with_int_literal_flagged() -> None:
    assert "is-with-literal" in _codes("def f(x):\n    return x is 42\n")


def test_is_none_not_flagged_as_identity_error() -> None:
    # `x is None` is the correct idiom — must not be flagged by is-with-literal
    assert "is-with-literal" not in _codes("def f(x):\n    return x is None\n")


def test_eq_none_flagged() -> None:
    assert "eq-none" in _codes("def f(x):\n    return x == None\n")
    assert "eq-none" in _codes("def f(x):\n    return x != None\n")


def test_range_len_flagged() -> None:
    source = (
        "def f(xs):\n"
        "    for i in range(len(xs)):\n"
        "        print(xs[i])\n"
    )
    assert "range-len" in _codes(source)


def test_plain_for_loop_not_flagged() -> None:
    source = (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        print(x)\n"
    )
    assert "range-len" not in _codes(source)


def test_string_concat_in_loop_flagged() -> None:
    source = (
        "def f(xs):\n"
        "    s = ''\n"
        "    for x in xs:\n"
        "        s += 'a'\n"
        "    return s\n"
    )
    assert "concat-in-loop" in _codes(source)


def test_list_append_not_flagged_as_concat() -> None:
    # += on a list value is fine; heuristic must target string literals only.
    source = (
        "def f(xs):\n"
        "    acc = []\n"
        "    for x in xs:\n"
        "        acc += [x]\n"
        "    return acc\n"
    )
    assert "concat-in-loop" not in _codes(source)


def test_mutable_class_attr_list_flagged() -> None:
    source = (
        "class Bag:\n"
        "    items = []\n"
        "    def add(self, x):\n"
        "        self.items.append(x)\n"
    )
    assert "mutable-class-attr" in _codes(source)


def test_mutable_class_attr_dict_flagged() -> None:
    source = (
        "class Registry:\n"
        "    entries = {}\n"
    )
    assert "mutable-class-attr" in _codes(source)


def test_class_int_attr_not_flagged() -> None:
    source = (
        "class Counter:\n"
        "    START = 0\n"
    )
    assert "mutable-class-attr" not in _codes(source)


def test_silent_except_pass_flagged() -> None:
    source = (
        "def f():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        pass\n"
    )
    assert "silent-except" in _codes(source)


def test_except_with_handling_not_flagged() -> None:
    source = (
        "def f():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception as e:\n"
        "        log.warning('failed', error=str(e))\n"
    )
    assert "silent-except" not in _codes(source)


def test_mutate_no_return_flagged() -> None:
    source = (
        "def add_item(xs, value):\n"
        "    xs.append(value)\n"
    )
    assert "mutate-no-return" in _codes(source)


def test_mutate_with_return_not_flagged() -> None:
    source = (
        "def add_item(xs, value):\n"
        "    xs.append(value)\n"
        "    return xs\n"
    )
    assert "mutate-no-return" not in _codes(source)


def test_no_mutation_not_flagged() -> None:
    source = (
        "def double(xs):\n"
        "    return [x * 2 for x in xs]\n"
    )
    assert "mutate-no-return" not in _codes(source)


def test_syntax_error_returns_empty_report_not_raise() -> None:
    report = detect_misconceptions("def broken(:\n")
    assert report.items == []
    assert "doesn't parse" in report.summary


def test_findings_sorted_by_line() -> None:
    source = (
        "def f(x):\n"
        "    if x is 5:\n"   # line 2: is-with-literal
        "        return x == None\n"  # line 3: eq-none
        "    return x\n"
    )
    lines = [m.line for m in detect_misconceptions(source).items]
    assert lines == sorted(lines)


def test_format_overlay_empty_on_clean() -> None:
    assert format_overlay([]) == ""


def test_format_overlay_includes_each_code() -> None:
    source = 'def f(x):\n    return x is "a"\n'
    items = detect_misconceptions(source).items
    overlay = format_overlay(items)
    assert "is-with-literal" in overlay
    assert "do not quote back" in overlay
