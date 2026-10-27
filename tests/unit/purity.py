from __future__ import annotations

import ast
import fnmatch
import unittest
from collections.abc import Sequence
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
    "time.sleep",
    "import time",
    "import uuid",
    "uuid.",
)


def _resolve_relative_import(
    node: ast.ImportFrom,
    py_file: Path,
    src_dir: Path | None,
    package_dir: Path,
) -> tuple[str, list[str]]:
    """Resolves relative import to absolute module name and full alias names."""
    if src_dir is not None:
        root = src_dir
    else:
        src_ancestors = [p for p in py_file.parents if p.name == "src"]
        root = src_ancestors[0] if src_ancestors else package_dir.parent

    try:
        rel_parent = py_file.parent.relative_to(root)
        pkg_parts = () if rel_parent == Path(".") else rel_parent.parts
    except ValueError:
        pkg_parts = ()

    if node.level == 1:
        base_parts = pkg_parts
    elif node.level > 1:
        cutoff = node.level - 1
        base_parts = pkg_parts[:-cutoff] if cutoff <= len(pkg_parts) else ()
    else:
        base_parts = ()

    if node.module:
        target_parts = base_parts + tuple(node.module.split("."))
        target_module = ".".join(target_parts)
    else:
        target_module = ".".join(base_parts)

    alias_full_names = []
    for alias in node.names:
        if target_module:
            alias_full_names.append(f"{target_module}.{alias.name}")
        else:
            alias_full_names.append(alias.name)

    return target_module, alias_full_names


def assert_pure_package(
    test_case: unittest.TestCase,
    package_dir: Path,
    *,
    extra_forbidden_patterns: tuple[str, ...] | list[str] = (),
    forbidden_modules: tuple[str, ...] | list[str] = (),
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
    src_dir: Path | None = None,
) -> None:
    """Verifies that no file, network, subprocess, os, random, uuid, clock,
    or forbidden module access occurs.
    """
    all_py_files = sorted(package_dir.rglob("*.py"))
    test_case.assertTrue(len(all_py_files) > 0, f"No python files found in {package_dir}")

    py_files: list[Path] = []
    for f in all_py_files:
        if include is not None:
            if not (f.name in include or any(fnmatch.fnmatch(f.name, p) for p in include)):
                continue
        if exclude is not None:
            if f.name in exclude or any(fnmatch.fnmatch(f.name, p) for p in exclude):
                continue
        py_files.append(f)

    test_case.assertTrue(
        len(py_files) > 0,
        f"No python files matched include/exclude filters in {package_dir}",
    )

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
                if node.level > 0:
                    target_module, alias_full_names = _resolve_relative_import(
                        node, py_file, src_dir, package_dir
                    )
                    for forbidden in forbidden_modules:
                        if target_module and (
                            target_module == forbidden
                            or target_module.startswith(f"{forbidden}.")
                        ):
                            test_case.fail(
                                f"Forbidden relative import resolving to '{target_module}' "
                                f"found in {py_file.name}"
                            )
                        for full_alias in alias_full_names:
                            if full_alias == forbidden or full_alias.startswith(f"{forbidden}."):
                                test_case.fail(
                                    f"Forbidden relative import resolving to '{full_alias}' "
                                    f"found in {py_file.name}"
                                )
                elif node.module:
                    for forbidden in forbidden_modules:
                        if node.module == forbidden or node.module.startswith(f"{forbidden}."):
                            test_case.fail(
                                f"Forbidden import from '{node.module}' found in {py_file.name}"
                            )
                        for alias in node.names:
                            full_alias = f"{node.module}.{alias.name}"
                            if full_alias == forbidden or full_alias.startswith(f"{forbidden}."):
                                test_case.fail(
                                    f"Forbidden import '{full_alias}' found in {py_file.name}"
                                )
