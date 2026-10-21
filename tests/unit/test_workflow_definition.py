import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from asf.configuration.errors import ConfigError
from asf.configuration.loader import load_projects
from asf.workflow.definition import (
    DEFAULT_MAX_REVISIONS,
    WorkflowDefinition,
)
from asf.workflow.loader import load_workflow, load_workflows

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "contracts.schema.json"
with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
    SCHEMA = json.load(schema_file)


def validator_for(definition: str) -> Draft202012Validator:
    wrapped_schema = {
        "$schema": SCHEMA["$schema"],
        "$defs": SCHEMA["$defs"],
        "$ref": f"#/$defs/{definition}",
    }
    return Draft202012Validator(wrapped_schema, format_checker=FormatChecker())


class WorkflowDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.workflow_validator = validator_for("Workflow")

    def test_real_workflows_load_and_validate_against_schema(self):
        workflows_dir = REPO_ROOT / "workflows"
        workflows = load_workflows(workflows_dir)
        self.assertIn("software-development", workflows)

        sd = workflows["software-development"]
        self.assertIsInstance(sd, WorkflowDefinition)
        self.assertEqual(sd.id, "software-development")
        self.assertEqual(sd.name, "Software development")
        self.assertEqual(sd.version, "1")
        self.assertEqual(len(sd.steps), 8)

        contract_dict = sd.to_contract()
        # Must be valid against schema
        self.workflow_validator.validate(contract_dict)

        # Check resolved maxRevisions on steps 1-3 (approval=true)
        # and absent on 4-8 (approval=false)
        for i in range(3):
            step = sd.steps[i]
            self.assertTrue(step.requires_approval)
            self.assertEqual(step.max_revisions, DEFAULT_MAX_REVISIONS)
            self.assertEqual(contract_dict["steps"][i]["maxRevisions"], DEFAULT_MAX_REVISIONS)

        for i in range(3, 8):
            step = sd.steps[i]
            self.assertFalse(step.requires_approval)
            self.assertIsNone(step.max_revisions)
            self.assertNotIn("maxRevisions", contract_dict["steps"][i])

    def test_all_project_workflows_exist(self):
        projects_dir = REPO_ROOT / "projects"
        workflows_dir = REPO_ROOT / "workflows"
        projects = load_projects(projects_dir)
        workflows = load_workflows(workflows_dir)

        for project_id, project in projects.items():
            with self.subTest(project=project_id):
                self.assertIn(project.workflow, workflows)

    def test_unknown_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
version: "1"
unknownProperty: bad
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: STEP_ONE
    agentType: test
    requiresApproval: false
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(any("unknownProperty" in iss.path for iss in ctx.exception.issues))

    def test_duplicate_step_id_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
version: "1"
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: STEP_ONE
    agentType: test
    requiresApproval: false
  - id: step1
    name: Step 1 Duplicate
    type: AGENT
    stage: STEP_TWO
    agentType: test
    requiresApproval: false
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(any("steps[1].id" in iss.path for iss in ctx.exception.issues))
            self.assertTrue(any("Duplicate step id" in iss.message for iss in ctx.exception.issues))

    def test_duplicate_or_colliding_generated_stage_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
version: "1"
steps:
  - id: spec
    name: Specification
    type: AGENT
    stage: SPEC
    agentType: spec
    requiresApproval: true
  - id: plain-colliding
    name: Plain step colliding with SPEC_DRAFT
    type: AGENT
    stage: SPEC_DRAFT
    agentType: test
    requiresApproval: false
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(any("steps[1].stage" in iss.path for iss in ctx.exception.issues))
            self.assertTrue(any("collides" in iss.message.lower() for iss in ctx.exception.issues))

    def test_reserved_stage_name_rejected(self):
        for reserved in ["NEW", "COMPLETED", "FAILED", "CANCELLED"]:
            with self.subTest(stage=reserved):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    wf_file = Path(tmp_dir) / "test-wf.yaml"
                    wf_file.write_text(
                        f"""
id: test-wf
name: Test
version: "1"
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: {reserved}
    agentType: test
    requiresApproval: false
""",
                        encoding="utf-8",
                    )
                    with self.assertRaises(ConfigError) as ctx:
                        load_workflow(wf_file)
                    self.assertTrue(
                        any("steps[0].stage" in iss.path for iss in ctx.exception.issues)
                    )
                    self.assertTrue(
                        any("reserved" in iss.message.lower() for iss in ctx.exception.issues)
                    )

    def test_consumes_not_produced_earlier_rejected(self):
        # Case A: Never produced
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
version: "1"
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: STEP_ONE
    agentType: test
    requiresApproval: false
    consumes:
      - UNKNOWN_ARTIFACT
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(any("steps[0].consumes" in iss.path for iss in ctx.exception.issues))
            msg_match = any(
                "not produced by an earlier step" in iss.message
                for iss in ctx.exception.issues
            )
            self.assertTrue(msg_match)

        # Case B: Produced by the same step
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
version: "1"
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: STEP_ONE
    agentType: test
    requiresApproval: false
    consumes:
      - ARTIFACT_A
    produces:
      - ARTIFACT_A
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(any("steps[0].consumes" in iss.path for iss in ctx.exception.issues))
            msg_match = any(
                "not produced by an earlier step" in iss.message
                for iss in ctx.exception.issues
            )
            self.assertTrue(msg_match)

        # Case C: Produced by a later step
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
version: "1"
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: STEP_ONE
    agentType: test
    requiresApproval: false
    consumes:
      - ARTIFACT_B
  - id: step2
    name: Step 2
    type: AGENT
    stage: STEP_TWO
    agentType: test
    requiresApproval: false
    produces:
      - ARTIFACT_B
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(any("steps[0].consumes" in iss.path for iss in ctx.exception.issues))
            msg_match = any(
                "not produced by an earlier step" in iss.message
                for iss in ctx.exception.issues
            )
            self.assertTrue(msg_match)

    def test_max_revisions_on_non_approval_step_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
version: "1"
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: STEP_ONE
    agentType: test
    requiresApproval: false
    maxRevisions: 2
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(
                any("steps[0].maxRevisions" in iss.path for iss in ctx.exception.issues)
            )
            self.assertTrue(
                any("requiresApproval is true" in iss.message for iss in ctx.exception.issues)
            )

    def test_empty_steps_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
version: "1"
steps: []
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(any("steps" in iss.path for iss in ctx.exception.issues))

    def test_id_stem_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: mismatched-id
name: Test
version: "1"
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: STEP_ONE
    agentType: test
    requiresApproval: false
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(any("id" in iss.path for iss in ctx.exception.issues))
            self.assertIn("does not match file stem", str(ctx.exception))

    def test_bad_stage_pattern_rejected(self):
        bad_stages = ["step_one", "1_STEP", "_STEP", "STEP-ONE", ""]
        for bad in bad_stages:
            with self.subTest(stage=bad):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    wf_file = Path(tmp_dir) / "test-wf.yaml"
                    wf_file.write_text(
                        f"""
id: test-wf
name: Test
version: "1"
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: '{bad}'
    agentType: test
    requiresApproval: false
""",
                        encoding="utf-8",
                    )
                    with self.assertRaises(ConfigError) as ctx:
                        load_workflow(wf_file)
                    self.assertTrue(
                        any("steps[0].stage" in iss.path for iss in ctx.exception.issues)
                    )

    def test_step_with_neither_agent_type_nor_action_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
version: "1"
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: STEP_ONE
    requiresApproval: false
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(
                any(
                    "agentType or action" in iss.message
                    for iss in ctx.exception.issues
                )
            )

    def test_duplicate_keys_in_yaml_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
name: Test Duplicate
version: "1"
steps:
  - id: step1
    name: Step 1
    type: AGENT
    stage: STEP_ONE
    agentType: test
    requiresApproval: false
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertIn("duplicate key", str(ctx.exception).lower())
