"""Unit tests for scripts/check_code_structure.py (loaded by path —
scripts/ is not a package)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_code_structure.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_code_structure", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = load_checker()


def violations_for(tmp_path: Path, source: str, name: str = "sample.py"):
    target = tmp_path / name
    target.write_text(source, encoding="utf-8")
    return checker.check_file(target)


def test_long_function_is_flagged_with_code_lines_only(tmp_path):
    body = "\n".join(f"    value_{i} = {i}" for i in range(31))
    source = (
        'def big():\n    """Docstring lines do not count."""\n\n'
        "    # neither do comments\n" + body + "\n    return value_0\n"
    )
    found = violations_for(tmp_path, source)
    lines = [v for v in found if v.rule == "function-lines"]
    assert len(lines) == 1
    assert lines[0].measured == 33  # def line + 31 assignments + return


def test_params_exclude_self_but_count_varargs(tmp_path):
    source = "class C:\n    def m(self, a, b, c, d, *rest):\n        return a\n"
    found = violations_for(tmp_path, source)
    params = [v for v in found if v.rule == "function-params"]
    assert len(params) == 1
    assert params[0].measured == 5


def test_nesting_and_complexity_are_measured(tmp_path):
    source = (
        "def deep(items):\n"
        "    for item in items:\n"
        "        if item:\n"
        "            while item:\n"
        "                try:\n"
        "                    return item\n"
        "                except ValueError:\n"
        "                    return None\n"
        "    return None\n"
    )
    found = violations_for(tmp_path, source)
    rules = {v.rule for v in found}
    assert "function-nesting" in rules


def test_protocol_stub_is_exempt(tmp_path):
    source = (
        "from typing import Protocol\n\n\n"
        "class Port(Protocol):\n"
        "    def call(self, a, b, c, d, e, f):\n"
        "        ...\n"
    )
    found = violations_for(tmp_path, source)
    assert [v for v in found if v.rule == "function-params"] == []


def test_banner_and_numbered_comments_are_flagged(tmp_path):
    source = "# ---------- section ----------\n# 1. first step\nvalue = 1\n"
    found = violations_for(tmp_path, source)
    rules = {v.rule for v in found}
    assert "banner-comment" in rules
    assert "numbered-comment" in rules


def test_class_limits_are_flagged(tmp_path):
    methods = "\n".join(f"    def m{i}(self):\n        return {i}" for i in range(11))
    source = f"class Wide:\n{methods}\n"
    found = violations_for(tmp_path, source)
    methods_hit = [v for v in found if v.rule == "class-methods"]
    assert methods_hit and methods_hit[0].measured == 11


def test_baseline_ratchet_accepts_equal_and_rejects_worse():
    violation = checker.Violation("a.py", "f", "function-lines", 40, 30)
    baseline = {violation.key(): 40}
    assert checker.new_or_worse([violation], baseline) == []
    worse = checker.Violation("a.py", "f", "function-lines", 41, 30)
    assert checker.new_or_worse([worse], baseline) == [worse]
    fresh = checker.Violation("a.py", "g", "function-lines", 31, 30)
    assert checker.new_or_worse([fresh], baseline) == [fresh]


def test_baseline_round_trip(tmp_path):
    violations = [checker.Violation("a.py", "f", "function-lines", 40, 30)]
    target = tmp_path / "baseline.json"
    target.write_text(
        __import__("json").dumps({"violations": checker.baseline_entries(violations)}),
        encoding="utf-8",
    )
    assert checker.load_baseline(target) == {("a.py", "f", "function-lines"): 40}


@pytest.mark.parametrize("measured", [30])
def test_function_at_the_limit_passes(tmp_path, measured):
    body = "\n".join(f"    value_{i} = {i}" for i in range(measured - 2))
    source = f"def ok():\n{body}\n    return value_0\n"
    found = violations_for(tmp_path, source)
    assert [v for v in found if v.rule == "function-lines"] == []
