import json
import unittest
from pathlib import Path

from asf.state_machine.graph import build_graph
from asf.state_machine.status import run_status, task_status
from asf.workflow.loader import load_workflow

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "contracts.schema.json"
with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
    SCHEMA = json.load(schema_file)


class StateMachineStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wf_path = REPO_ROOT / "workflow-definitions" / "software-development.yaml"
        cls.workflow_def = load_workflow(wf_path)
        cls.graph = build_graph(cls.workflow_def)
        cls.task_status_enum = set(SCHEMA["$defs"]["Task"]["properties"]["status"]["enum"])
        cls.run_status_enum = set(SCHEMA["$defs"]["WorkflowRun"]["properties"]["status"]["enum"])

    def test_every_stage_maps_to_valid_task_and_run_status(self):
        for stage in self.graph.stages:
            with self.subTest(stage=stage.name):
                t_stat = task_status(self.graph, stage.name)
                r_stat = run_status(self.graph, stage.name)

                self.assertIn(
                    t_stat,
                    self.task_status_enum,
                    f"Stage '{stage.name}' mapped to invalid Task.status '{t_stat}'",
                )
                self.assertIn(
                    r_stat,
                    self.run_status_enum,
                    f"Stage '{stage.name}' mapped to invalid WorkflowRun.status '{r_stat}'",
                )

    def test_spot_checks(self):
        spot_checks = [
            ("NEW", "NEW", "PENDING"),
            ("SPEC_DRAFT", "IN_PROGRESS", "RUNNING"),
            ("SPEC_REVIEW", "WAITING", "WAITING"),
            ("SPEC_ESCALATED", "WAITING", "WAITING"),
            ("READY_TO_MERGE", "IN_PROGRESS", "RUNNING"),
            ("COMPLETED", "COMPLETED", "COMPLETED"),
            ("FAILED", "FAILED", "FAILED"),
            ("CANCELLED", "CANCELLED", "CANCELLED"),
        ]

        for stage_name, expected_task_status, expected_run_status in spot_checks:
            with self.subTest(stage=stage_name):
                self.assertEqual(task_status(self.graph, stage_name), expected_task_status)
                self.assertEqual(run_status(self.graph, stage_name), expected_run_status)
