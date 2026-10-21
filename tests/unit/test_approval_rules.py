from __future__ import annotations

import json
import unittest
from pathlib import Path

from asf.state_machine.triggers import Trigger
from tests.unit.purity import assert_pure_package

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "contracts.schema.json"
with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
    SCHEMA = json.load(schema_file)

STATUS_TO_TRIGGER_MAPPING: dict[str, str] = {
    "APPROVED": "APPROVED",
    "REJECTED": "REJECTED",
    "CHANGES_REQUESTED": "REQUEST_CHANGES",
}


class ApprovalRulesTests(unittest.TestCase):
    def test_purity_guard_no_forbidden_operations_and_imports(self):
        """Purity guard scanning src/asf/approval/*.py.

        Verifies that no file, network, subprocess, os, random, uuid, clock,
        or forbidden module access (asf.state_machine, asf.workflow, asf.storage) occurs.
        """
        approval_dir = REPO_ROOT / "src" / "asf" / "approval"
        assert_pure_package(
            self,
            approval_dir,
            forbidden_modules=[
                "asf.state_machine",
                "asf.workflow",
                "asf.storage",
            ],
        )

    def test_status_to_trigger_mapping_consistency(self):
        """The documented status -> trigger mapping of A10 is consistent with Trigger and schema."""
        trigger_values = {t.value for t in Trigger}
        decision_enum = set(
            SCHEMA["$defs"]["ApprovalDecision"]["properties"]["decision"]["enum"]
        )

        for status, trigger_name in STATUS_TO_TRIGGER_MAPPING.items():
            with self.subTest(status=status, trigger=trigger_name):
                # Each mapped trigger value exists in Trigger
                self.assertIn(
                    trigger_name,
                    trigger_values,
                    f"Trigger '{trigger_name}' mapped from status '{status}' "
                    "does not exist in Trigger",
                )

        mapped_decisions = set(STATUS_TO_TRIGGER_MAPPING.values())
        self.assertEqual(
            mapped_decisions,
            decision_enum,
            "Mapped decision triggers do not equal ApprovalDecision.decision enum in schema",
        )
