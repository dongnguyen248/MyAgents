from __future__ import annotations

import ast
import unittest
from pathlib import Path

FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "open(",
    "import yaml",
    "import os",
    "import socket",
    "import subprocess",
    "import requests",
    "import random",
    "datetime.now",
    "datetime.utcnow",
    "time.time",
    "time.monotonic",
    "import uuid",
    "uuid.",
)


def assert_pure_package(
    test_case: unittest.TestCase,
    package_dir: Path,
    *,
    extra_forbidden_patterns: tuple[str, ...] | list[str] = (),
    forbidden_modules: tuple[str, ...] | list[str] = (),
) -> None:
    """Verifies that no file, network, subprocess, os, random, uuid, clock,
    or forbidden module access occurs.
    """
    py_files = list(package_dir.glob("*.py"))
    test_case.assertTrue(len(py_files) > 0, f"No python files found in {package_dir}")

    all_forbidden = FORBIDDEN_PATTERNS + tuple(extra_forbidden_patterns)

    for py_file in py_files:
        content = py_file.read_text(encoding="utf-8")
        for forbidden in all_forbidden:
            test_case.assertNotIn(
                forbidden,
                content,
                f"Forbidden pattern '{forbidden}' found in {py_file.name}",
            )

        tree = ast.parse(content, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    if func.attr in {"now", "utcnow"}:
                        test_case.fail(
                            f"Forbidden clock call '{func.attr}' found in {py_file.name}"
                        )
                    if (
                        func.attr in {"time", "monotonic"}
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "time"
                    ):
                        test_case.fail(
                            f"Forbidden clock call 'time.{func.attr}' found in {py_file.name}"
                        )

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_modules:
                        if alias.name == forbidden or alias.name.startswith(f"{forbidden}."):
                            test_case.fail(
                                f"Forbidden import '{alias.name}' found in {py_file.name}"
                            )

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in forbidden_modules:
                        if node.module == forbidden or node.module.startswith(f"{forbidden}."):
                            test_case.fail(
                                f"Forbidden import from '{node.module}' found in {py_file.name}"
                            )
