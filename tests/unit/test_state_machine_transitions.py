import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from asf.state_machine.graph import build_graph
from asf.state_machine.machine import InvalidTransition, RunState, apply
from asf.state_machine.triggers import Trigger
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
from asf.workflow.loader import load_workflow

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


class StateMachineTransitionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wf_path = REPO_ROOT / "workflows" / "software-development.yaml"
        cls.workflow_def = load_workflow(wf_path)
        cls.graph = build_graph(cls.workflow_def)
        cls.error_validator = validator_for("PlatformError")

    def test_full_happy_path_new_to_completed(self):
        transitions = [
            (Trigger.START, "SPEC_DRAFT"),
            (Trigger.COMPLETE, "SPEC_REVIEW"),
            (Trigger.APPROVED, "SPEC_APPROVED"),
            (Trigger.ADVANCE, "PLAN_DRAFT"),
            (Trigger.COMPLETE, "PLAN_REVIEW"),
            (Trigger.APPROVED, "PLAN_APPROVED"),
            (Trigger.ADVANCE, "TASK_DRAFT"),
            (Trigger.COMPLETE, "TASK_REVIEW"),
            (Trigger.APPROVED, "TASK_APPROVED"),
            (Trigger.ADVANCE, "IMPLEMENTING"),
            (Trigger.COMPLETE, "CODE_REVIEW"),
            (Trigger.COMPLETE, "TESTING"),
            (Trigger.COMPLETE, "CI"),
            (Trigger.COMPLETE, "READY_TO_MERGE"),
            (Trigger.COMPLETE, "COMPLETED"),
        ]

        state = RunState.initial()
        self.assertEqual(state.stage, "NEW")
        self.assertEqual(dict(state.revisions), {})

        for trigger, expected_stage in transitions:
            state = apply(self.graph, state, trigger)
            self.assertEqual(state.stage, expected_stage)

    def test_rejection_loops_and_escalation(self):
        state = RunState.initial()
        state = apply(self.graph, state, Trigger.START)  # SPEC_DRAFT
        state = apply(self.graph, state, Trigger.COMPLETE)  # SPEC_REVIEW

        # 1. Rejection via REJECTED -> SPEC_REJECTED -> SPEC_DRAFT (count 1)
        state = apply(self.graph, state, Trigger.REJECTED)
        self.assertEqual(state.stage, "SPEC_REJECTED")
        state = apply(self.graph, state, Trigger.REVISE)
        self.assertEqual(state.stage, "SPEC_DRAFT")
        self.assertEqual(state.revisions.get("spec"), 1)

        # 2. Rejection via REQUEST_CHANGES -> SPEC_REJECTED -> SPEC_DRAFT (count 2)
        state = apply(self.graph, state, Trigger.COMPLETE)  # SPEC_REVIEW
        state = apply(self.graph, state, Trigger.REQUEST_CHANGES)
        self.assertEqual(state.stage, "SPEC_REJECTED")
        state = apply(self.graph, state, Trigger.REVISE)
        self.assertEqual(state.stage, "SPEC_DRAFT")
        self.assertEqual(state.revisions.get("spec"), 2)

        # 3. 3rd REVISE -> count becomes 3 (still within limit of 3)
        state = apply(self.graph, state, Trigger.COMPLETE)  # SPEC_REVIEW
        state = apply(self.graph, state, Trigger.REJECTED)
        state = apply(self.graph, state, Trigger.REVISE)
        self.assertEqual(state.stage, "SPEC_DRAFT")
        self.assertEqual(state.revisions.get("spec"), 3)

        # 4. 4th REVISE -> limit reached! Escalates to SPEC_ESCALATED, count stays 3
        state = apply(self.graph, state, Trigger.COMPLETE)  # SPEC_REVIEW
        state = apply(self.graph, state, Trigger.REJECTED)
        state = apply(self.graph, state, Trigger.REVISE)
        self.assertEqual(state.stage, "SPEC_ESCALATED")
        self.assertEqual(state.revisions.get("spec"), 3)

        # 5. RESUME from SPEC_ESCALATED resets count to 0 and goes to SPEC_DRAFT
        state = apply(self.graph, state, Trigger.RESUME)
        self.assertEqual(state.stage, "SPEC_DRAFT")
        self.assertEqual(state.revisions.get("spec"), 0)

    def test_fail_and_cancel_from_every_non_terminal_stage(self):
        non_terminal_stages = [
            s.name
            for s in self.graph.stages
            if s.name not in {"COMPLETED", "FAILED", "CANCELLED"}
        ]

        for stage_name in non_terminal_stages:
            with self.subTest(stage=stage_name, trigger="FAIL"):
                st = RunState(stage=stage_name, revisions={})
                next_st = apply(self.graph, st, Trigger.FAIL)
                self.assertEqual(next_st.stage, "FAILED")

            with self.subTest(stage=stage_name, trigger="CANCEL"):
                st = RunState(stage=stage_name, revisions={})
                next_st = apply(self.graph, st, Trigger.CANCEL)
                self.assertEqual(next_st.stage, "CANCELLED")

    def test_invalid_transitions_raise_and_validate_platform_error(self):
        invalid_cases = [
            (RunState(stage="SPEC_DRAFT"), Trigger.APPROVED),
            (RunState(stage="COMPLETED"), Trigger.START),
            (RunState(stage="COMPLETED"), Trigger.COMPLETE),
            (RunState(stage="UNKNOWN_STAGE"), Trigger.START),
            (RunState(stage="SPEC_DRAFT"), "NON_EXISTENT_TRIGGER"),
            (RunState(stage="SPEC_REVIEW"), Trigger.REVISE),
        ]

        for st, trig in invalid_cases:
            with self.subTest(stage=st.stage, trigger=trig):
                with self.assertRaises(InvalidTransition) as ctx:
                    apply(self.graph, st, trig)

                exc = ctx.exception
                self.assertEqual(exc.stage, st.stage)
                self.assertEqual(exc.trigger, str(trig))

                err_dict = exc.to_platform_error()
                self.error_validator.validate(err_dict)
                self.assertEqual(err_dict["code"], "WORKFLOW_INVALID_TRANSITION")
                self.assertEqual(err_dict["category"], "WORKFLOW")
                self.assertFalse(err_dict["retryable"])
                self.assertEqual(err_dict["details"]["stage"], st.stage)
                self.assertEqual(err_dict["details"]["trigger"], str(trig))

    def test_to_platform_error_with_explicit_datetime(self):
        exc = InvalidTransition(
            stage="NEW", trigger="APPROVED", allowed=("START", "FAIL", "CANCEL")
        )
        fixed_dt = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)
        err_dict = exc.to_platform_error(now=fixed_dt)
        self.error_validator.validate(err_dict)
        self.assertEqual(err_dict["timestamp"], "2026-10-20T14:00:00+00:00")

    def test_purity_inputs_and_revisions_never_mutated(self):
        initial_revisions = {"spec": 1}
        original_state = RunState(stage="SPEC_REJECTED", revisions=initial_revisions)

        new_state = apply(self.graph, original_state, Trigger.REVISE)

        self.assertIsNot(original_state, new_state)
        self.assertEqual(original_state.stage, "SPEC_REJECTED")
        self.assertEqual(original_state.revisions["spec"], 1)
        self.assertEqual(new_state.stage, "SPEC_DRAFT")
        self.assertEqual(new_state.revisions["spec"], 2)

    def test_custom_workflow_max_revisions_zero_escalates_on_first_revise(self):
        custom_wf = WorkflowDefinition(
            id="custom",
            name="Custom Workflow",
            version="1",
            steps=[
                WorkflowStepDef(
                    id="step-1",
                    name="Approval Step",
                    type="AGENT",
                    stage="STAGE_A",
                    agent_type="test-agent",
                    requires_approval=True,
                    max_revisions=0,
                    produces=["DOC"],
                ),
                WorkflowStepDef(
                    id="step-2",
                    name="Plain Step",
                    type="SYSTEM",
                    stage="STAGE_B",
                    action="do-something",
                    requires_approval=False,
                    consumes=["DOC"],
                ),
            ],
        )
        custom_graph = build_graph(custom_wf)

        state = RunState.initial()
        state = apply(custom_graph, state, Trigger.START)  # STAGE_A_DRAFT
        state = apply(custom_graph, state, Trigger.COMPLETE)  # STAGE_A_REVIEW
        state = apply(custom_graph, state, Trigger.REJECTED)  # STAGE_A_REJECTED

        # First REVISE on max_revisions=0 should immediately go to STAGE_A_ESCALATED
        state = apply(custom_graph, state, Trigger.REVISE)
        self.assertEqual(state.stage, "STAGE_A_ESCALATED")
        self.assertEqual(state.revisions.get("step-1", 0), 0)
