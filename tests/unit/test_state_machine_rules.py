import json
import unittest
from pathlib import Path

from asf.state_machine.triggers import Trigger
from tests.unit.purity import assert_pure_package

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
        """Purity guard scanning src/asf/state_machine/*.py."""
        sm_dir = REPO_ROOT / "src" / "asf" / "state_machine"
        assert_pure_package(self, sm_dir)
