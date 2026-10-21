import ast
import json
import unittest
from pathlib import Path

from asf.state_machine.triggers import Trigger

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "contracts.schema.json"
with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
    SCHEMA = json.load(schema_file)


class StateMachineRulesTests(unittest.TestCase):
    def test_triggers_equal_approval_decision_enum(self):
        decision_enum = set(
            SCHEMA["$defs"]["ApprovalDecision"]["properties"]["decision"]["enum"]
        )
        trigger_decision_values = {
            Trigger.APPROVED.value,
            Trigger.REJECTED.value,
            Trigger.REQUEST_CHANGES.value,
        }
        self.assertEqual(
            trigger_decision_values,
            decision_enum,
            "Approval decision triggers do not match ApprovalDecision.decision enum in schema",
        )

    def test_purity_guard_no_forbidden_operations(self):
        """Purity guard scanning src/asf/state_machine/*.py.

        Verifies that no file, network, subprocess, os, random, or yaml access occurs.
        The only allowed clock call is `datetime.now(timezone.utc)` inside
        `to_platform_error` in machine.py.
        """
        sm_dir = REPO_ROOT / "src" / "asf" / "state_machine"
        py_files = list(sm_dir.glob("*.py"))
        self.assertTrue(len(py_files) > 0, "No python files found in state_machine")

        strictly_forbidden = [
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
        ]

        for py_file in py_files:
            content = py_file.read_text(encoding="utf-8")
            for forbidden in strictly_forbidden:
                self.assertNotIn(
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
                            self.fail(
                                f"Forbidden clock call '{func.attr}' found in {py_file.name}"
                            )
                        if (
                            func.attr in {"time", "monotonic"}
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "time"
                        ):
                            self.fail(
                                f"Forbidden clock call 'time.{func.attr}' found in {py_file.name}"
                            )
