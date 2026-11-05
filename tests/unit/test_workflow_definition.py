import copy
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
    WorkflowStepDef,
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

    def test_implement_consumes_spec_plan_task(self):
        workflows_dir = REPO_ROOT / "workflow-definitions"
        workflows = load_workflows(workflows_dir)
        sd = workflows["software-development"]
        implement_step = next(s for s in sd.steps if s.id == "implement")
        self.assertEqual(implement_step.consumes, ["SPEC", "PLAN", "TASK"])
        self.assertEqual(implement_step.produces, ["CODE"])

    def test_review_consumes_spec_plan_task_code(self):
        workflows_dir = REPO_ROOT / "workflow-definitions"
        workflows = load_workflows(workflows_dir)
        sd = workflows["software-development"]
        review_step = next(s for s in sd.steps if s.id == "review")
        self.assertEqual(review_step.consumes, ["SPEC", "PLAN", "TASK", "CODE"])
        self.assertEqual(review_step.produces, ["CODE_REVIEW"])

    def test_test_consumes_task_code(self):
        workflows_dir = REPO_ROOT / "workflow-definitions"
        workflows = load_workflows(workflows_dir)
        sd = workflows["software-development"]
        test_step = next(s for s in sd.steps if s.id == "test")
        self.assertEqual(test_step.consumes, ["TASK", "CODE"])
        self.assertEqual(test_step.produces, ["TEST_REPORT"])

    def test_real_workflows_load_and_validate_against_schema(self):
        workflows_dir = REPO_ROOT / "workflow-definitions"
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
        workflows_dir = REPO_ROOT / "workflow-definitions"
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
            with self.subTest(stage=reserved), tempfile.TemporaryDirectory() as tmp_dir:
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
                self.assertTrue(any("steps[0].stage" in iss.path for iss in ctx.exception.issues))
                self.assertTrue(
                    any("reserved" in iss.message.lower() for iss in ctx.exception.issues)
                )

    def test_reserved_stage_with_approval_produces_single_issue(self):
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
    stage: NEW
    agentType: test
    requiresApproval: true
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)

            stage_issues = [iss for iss in ctx.exception.issues if iss.path == "steps[0].stage"]
            self.assertEqual(
                len(stage_issues),
                1,
                f"Expected exactly 1 reserved stage error for step, got {len(stage_issues)}",
            )
            self.assertIn("reserved", stage_issues[0].message.lower())

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
                "not produced by an earlier step" in iss.message for iss in ctx.exception.issues
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
                "not produced by an earlier step" in iss.message for iss in ctx.exception.issues
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
                "not produced by an earlier step" in iss.message for iss in ctx.exception.issues
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
            with self.subTest(stage=bad), tempfile.TemporaryDirectory() as tmp_dir:
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
                self.assertTrue(any("steps[0].stage" in iss.path for iss in ctx.exception.issues))

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
                any("agentType or action" in iss.message for iss in ctx.exception.issues)
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

    def test_custom_step_type_accepted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf_file = Path(tmp_dir) / "test-wf.yaml"
            wf_file.write_text(
                """
id: test-wf
name: Test
version: "1"
steps:
  - id: step1
    name: Custom Step
    type: CUSTOM_STEP
    stage: STEP_ONE
    action: do-custom
    requiresApproval: false
""",
                encoding="utf-8",
            )
            wf = load_workflow(wf_file)
            self.assertEqual(wf.steps[0].type, "CUSTOM_STEP")
            contract_dict = wf.to_contract()
            self.workflow_validator.validate(contract_dict)
            self.assertEqual(contract_dict["steps"][0]["type"], "CUSTOM_STEP")

    def test_empty_step_type_rejected(self):
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
    type: ""
    stage: STEP_ONE
    action: do-step
    requiresApproval: false
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)
            self.assertTrue(any("steps[0].type" in iss.path for iss in ctx.exception.issues))

    def test_secret_scan_in_workflow_configuration_api_key(self):
        sentinel = "SENTINEL_WORKFLOW_SECRET_123"

        # 1. Literal secret rejected with path and sentinel masked
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
    stage: STEP_ONE
    agentType: test
    requiresApproval: false
    configuration:
      apiKey: {sentinel}
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_workflow(wf_file)

            err = ctx.exception
            self.assertTrue(any("steps[0].configuration.apiKey" in iss.path for iss in err.issues))
            self.assertNotIn(sentinel, str(err))
            for iss in err.issues:
                self.assertNotIn(sentinel, iss.message)
            self.assertNotIn(sentinel, json.dumps(err.to_platform_errors()))

        # 2. {env: NAME} accepted
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
    configuration:
      apiKey:
        env: MY_API_KEY
""",
                encoding="utf-8",
            )
            wf = load_workflow(wf_file)
            self.assertEqual(wf.steps[0].configuration["apiKey"], {"env": "MY_API_KEY"})

        # 3. null accepted
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
    configuration:
      apiKey: null
""",
                encoding="utf-8",
            )
            wf = load_workflow(wf_file)
            self.assertIsNone(wf.steps[0].configuration["apiKey"])

    def test_model_validate_leaves_input_dict_unchanged_and_resolves_max_revisions(self):
        raw_step = {
            "id": "spec",
            "name": "Spec",
            "type": "AGENT",
            "stage": "SPEC",
            "requires_approval": True,
            "agent_type": "spec",
        }
        copy_raw = copy.deepcopy(raw_step)
        step = WorkflowStepDef.model_validate(raw_step)

        self.assertEqual(raw_step, copy_raw)
        self.assertNotIn("max_revisions", raw_step)
        self.assertEqual(step.max_revisions, DEFAULT_MAX_REVISIONS)

    def test_approval_step_max_revisions_null_and_missing_defaults_to_three(self):
        cases = [
            ("maxRevisions_null", {"requiresApproval": True, "maxRevisions": None}),
            ("max_revisions_null", {"requires_approval": True, "max_revisions": None}),
            ("missing_key", {"requiresApproval": True}),
        ]
        base_step = {
            "id": "spec",
            "name": "Spec",
            "type": "AGENT",
            "stage": "SPEC",
            "agent_type": "spec",
        }
        for label, extra in cases:
            with self.subTest(case=label):
                raw = {**base_step, **extra}
                step = WorkflowStepDef.model_validate(raw)
                self.assertEqual(step.max_revisions, 3)
                contract_dict = step.to_contract()
                self.assertEqual(contract_dict.get("maxRevisions"), 3)

    def test_model_to_contract_schema_drift_guard(self):
        step_variants = [
            (
                "custom_step_type",
                {
                    "id": "s1",
                    "name": "Custom",
                    "type": "CUSTOM_STEP",
                    "stage": "STAGE_CUSTOM",
                    "action": "do-custom",
                    "requiresApproval": False,
                },
            ),
            (
                "step_without_approval",
                {
                    "id": "s2",
                    "name": "Plain",
                    "type": "SYSTEM",
                    "stage": "STAGE_PLAIN",
                    "action": "do-plain",
                    "requiresApproval": False,
                },
            ),
            (
                "step_approval_with_max_revisions",
                {
                    "id": "s3",
                    "name": "Approval Custom Revs",
                    "type": "AGENT",
                    "stage": "STAGE_REV",
                    "agentType": "agent-a",
                    "requiresApproval": True,
                    "maxRevisions": 5,
                },
            ),
            (
                "step_approval_without_max_revisions",
                {
                    "id": "s4",
                    "name": "Approval Default Revs",
                    "type": "AGENT",
                    "stage": "STAGE_DEF_REV",
                    "agentType": "agent-b",
                    "requiresApproval": True,
                },
            ),
            (
                "step_consumes_produces",
                {
                    "id": "s5",
                    "name": "Artifacts Step",
                    "type": "AGENT",
                    "stage": "STAGE_ART",
                    "agentType": "agent-c",
                    "requiresApproval": False,
                    "produces": ["art_1"],
                },
            ),
            (
                "step_timeout_retry_policy",
                {
                    "id": "s6",
                    "name": "Timeout Retry Step",
                    "type": "AGENT",
                    "stage": "STAGE_RETRY",
                    "agentType": "agent-d",
                    "requiresApproval": False,
                    "timeout": 300,
                    "retryPolicy": {
                        "maxAttempts": 3,
                        "backoffSeconds": 1.0,
                    },
                },
            ),
        ]

        for variant_name, step_data in step_variants:
            with self.subTest(variant=variant_name):
                wf_dict = {
                    "id": f"wf-{variant_name}",
                    "name": f"Workflow {variant_name}",
                    "version": "1.0.0",
                    "steps": [step_data],
                    "metadata": {"test": True},
                }
                wf = WorkflowDefinition.model_validate(wf_dict)
                contract_dict = wf.to_contract()
                self.workflow_validator.validate(contract_dict)
