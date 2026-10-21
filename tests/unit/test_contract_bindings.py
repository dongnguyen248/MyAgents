from __future__ import annotations

import ast
import copy
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from asf.approval.models import ApprovalFeedback
from asf.contracts.models import (
    ActivityEvent,
    AgentMetadata,
    AgentRequest,
    AgentResult,
    Artifact,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    PlatformError,
    RunMetrics,
    ValidationResult,
)
from tests.unit.contract_models import assert_contract_binding, validator_for
from tests.unit.purity import assert_pure_package

T_AWARE = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)
T_NAIVE = datetime(2026, 10, 20, 14, 0, 0)


def sample_platform_error() -> PlatformError:
    return PlatformError(
        code="VALIDATION_FAILED",
        message="Invalid request",
        category="VALIDATION",
        details={"path": "input.req"},
        retryable=False,
        timestamp=T_AWARE,
    )


def sample_run_metrics() -> RunMetrics:
    return RunMetrics(
        duration_seconds=1.23,
        revision_count=0,
        attempt=1,
    )


def sample_artifact() -> Artifact:
    return Artifact(
        id="art-1",
        type="SPEC",
        name="SPEC.md",
        version="1",
        content={"format": "markdown", "text": "# Spec"},
        created_by="agent-spec",
        created_at=T_AWARE,
        metadata={"template": "spec"},
    )


def sample_activity_event() -> ActivityEvent:
    return ActivityEvent(
        id="evt-1",
        timestamp=T_AWARE,
        project_id="proj-1",
        task_id="task-1",
        workflow_id="software-development",
        agent_id="agent-spec",
        event_type="AGENT_STARTED",
        message="Agent started",
        metadata={"requestId": "req-1"},
    )


def sample_agent_metadata() -> AgentMetadata:
    return AgentMetadata(
        id="agent-spec",
        name="Specification Agent",
        type="spec",
        version="1.0.0",
        status="IDLE",
        capabilities=["write-spec", "revise-spec"],
        configuration={},
    )


def sample_validation_result() -> ValidationResult:
    return ValidationResult(
        valid=True,
        errors=[],
    )


def sample_model_message() -> ModelMessage:
    return ModelMessage(
        role="user",
        content="Hello model",
    )


def sample_model_usage() -> ModelUsage:
    return ModelUsage(
        prompt_tokens=10,
        completion_tokens=20,
    )


def sample_model_request() -> ModelRequest:
    return ModelRequest(
        messages=[sample_model_message()],
        parameters={"temperature": 0.5},
        model="test-model",
        metadata={"requestId": "req-1"},
    )


def sample_model_response() -> ModelResponse:
    return ModelResponse(
        content="Response text",
        model="test-model",
        usage=sample_model_usage(),
        finish_reason="stop",
        metadata={},
    )


def sample_agent_request() -> AgentRequest:
    return AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="agent-spec",
        input={"requirement": "Build a widget"},
        context={"project": {"name": "sample"}},
        artifacts=[sample_artifact()],
        feedback=[],
        metadata={"attempt": 1},
    )


def sample_agent_result() -> AgentResult:
    return AgentResult(
        request_id="req-1",
        agent_id="agent-spec",
        status="SUCCESS",
        output={"summary": "Created spec"},
        artifacts=[sample_artifact()],
        events=[sample_activity_event()],
        metrics=sample_run_metrics(),
        errors=[],
    )


class ContractBindingsTests(unittest.TestCase):
    def test_all_twelve_bindings_conform_to_schema(self):
        cases = [
            (PlatformError, "PlatformError", sample_platform_error(), {"category": "category"}),
            (RunMetrics, "RunMetrics", sample_run_metrics(), None),
            (Artifact, "Artifact", sample_artifact(), None),
            (ActivityEvent, "ActivityEvent", sample_activity_event(), None),
            (AgentMetadata, "AgentMetadata", sample_agent_metadata(), {"status": "AgentStatus"}),
            (ValidationResult, "ValidationResult", sample_validation_result(), None),
            (ModelMessage, "ModelMessage", sample_model_message(), {"role": "role"}),
            (ModelUsage, "ModelUsage", sample_model_usage(), None),
            (ModelRequest, "ModelRequest", sample_model_request(), None),
            (ModelResponse, "ModelResponse", sample_model_response(), None),
            (AgentRequest, "AgentRequest", sample_agent_request(), None),
            (AgentResult, "AgentResult", sample_agent_result(), {"status": "status"}),
        ]

        for model_cls, def_name, sample_inst, enum_paths in cases:
            with self.subTest(contract=def_name):
                assert_contract_binding(
                    self,
                    model_cls,
                    def_name,
                    sample_inst,
                    enum_paths=enum_paths,
                )

    def test_naive_datetimes_rejected(self):
        with self.assertRaises(ValidationError):
            PlatformError(
                code="ERR",
                message="msg",
                category="AGENT",
                retryable=False,
                timestamp=T_NAIVE,
            )

        with self.assertRaises(ValidationError):
            Artifact(
                id="a1",
                type="SPEC",
                name="SPEC.md",
                version="1",
                content={"text": "hi"},
                created_by="agent",
                created_at=T_NAIVE,
            )

        with self.assertRaises(ValidationError):
            ActivityEvent(
                id="e1",
                timestamp=T_NAIVE,
                project_id="p1",
                task_id="t1",
                workflow_id="w1",
                agent_id="a1",
                event_type="AGENT_STARTED",
                message="msg",
            )

    def test_unknown_keys_rejected(self):
        with self.assertRaises(ValidationError):
            PlatformError(
                code="ERR",
                message="msg",
                category="AGENT",
                retryable=False,
                timestamp=T_AWARE,
                extra_key="forbidden",  # type: ignore[call-arg]
            )

        with self.assertRaises(ValidationError):
            RunMetrics(
                duration_seconds=1.0,
                revision_count=0,
                attempt=1,
                extra_key="forbidden",  # type: ignore[call-arg]
            )

    def test_artifact_content_or_reference_and_drop_none_keys(self):
        # Neither content nor reference -> ValidationError
        with self.assertRaises(ValidationError):
            Artifact(
                id="a1",
                type="SPEC",
                name="SPEC.md",
                version="1",
                created_by="agent",
                created_at=T_AWARE,
            )

        # content only -> reference dropped from to_contract
        art_content = Artifact(
            id="a1",
            type="SPEC",
            name="SPEC.md",
            version="1",
            content={"text": "spec"},
            created_by="agent",
            created_at=T_AWARE,
        )
        c_dict = art_content.to_contract()
        self.assertIn("content", c_dict)
        self.assertNotIn("reference", c_dict)

        # reference only -> content dropped from to_contract
        art_ref = Artifact(
            id="a2",
            type="SPEC",
            name="SPEC.md",
            version="1",
            reference="storage://bucket/file",
            created_by="agent",
            created_at=T_AWARE,
        )
        r_dict = art_ref.to_contract()
        self.assertIn("reference", r_dict)
        self.assertNotIn("content", r_dict)

        # Both present -> both retained
        art_both = Artifact(
            id="a3",
            type="SPEC",
            name="SPEC.md",
            version="1",
            content={"text": "spec"},
            reference="storage://bucket/file",
            created_by="agent",
            created_at=T_AWARE,
        )
        b_dict = art_both.to_contract()
        self.assertIn("content", b_dict)
        self.assertIn("reference", b_dict)

    def test_model_request_drops_none_model(self):
        req_no_model = ModelRequest(
            messages=[sample_model_message()],
            model=None,
        )
        d_no_model = req_no_model.to_contract()
        self.assertNotIn("model", d_no_model)

        req_with_model = ModelRequest(
            messages=[sample_model_message()],
            model="gpt-4o",
        )
        d_with_model = req_with_model.to_contract()
        self.assertEqual(d_with_model.get("model"), "gpt-4o")

    def test_agent_request_default_feedback_and_item_validation(self):
        # Default feedback is [] and validates
        req = sample_agent_request()
        self.assertEqual(req.feedback, [])
        validator_for("AgentRequest").validate(req.to_contract())

        # Feedback item validates against $defs/ApprovalFeedback
        fb = ApprovalFeedback(
            approval_id="app-1",
            reviewer="reviewer-1",
            decision="REQUEST_CHANGES",
            comment="Fix the scope",
        )
        fb_dict = fb.model_dump(by_alias=True, mode="json")
        validator_for("ApprovalFeedback").validate(fb_dict)

        # AgentRequest with feedback validates
        req_with_fb = req.model_copy(update={"feedback": [fb]})
        validator_for("AgentRequest").validate(req_with_fb.to_contract())

    def test_agent_result_output_none_stays_present(self):
        res = sample_agent_result().model_copy(update={"output": None})
        res_dict = res.to_contract()
        self.assertIn("output", res_dict)
        self.assertIsNone(res_dict["output"])
        validator_for("AgentResult").validate(res_dict)

    def test_agent_metadata_duplicate_capabilities_rejected(self):
        with self.assertRaises(ValidationError):
            AgentMetadata(
                id="agent-spec",
                name="Specification Agent",
                type="spec",
                version="1.0.0",
                status="IDLE",
                capabilities=["write-spec", "write-spec"],
            )

        with self.assertRaises(ValidationError):
            AgentMetadata(
                id="agent-spec",
                name="Specification Agent",
                type="spec",
                version="1.0.0",
                status="IDLE",
                capabilities=[""],
            )

    def test_models_do_not_mutate_input_dicts(self):
        input_dict = {
            "requestId": "req-1",
            "taskId": "task-1",
            "projectId": "proj-1",
            "workflowId": "software-development",
            "agentId": "agent-spec",
            "input": {"nested": {"key": "value"}},
            "context": {"env": "test"},
            "artifacts": [],
            "metadata": {"tags": ["a", "b"]},
        }
        copied = copy.deepcopy(input_dict)
        AgentRequest.model_validate(input_dict)
        self.assertEqual(input_dict, copied)

    def test_contracts_boundary_and_purity(self):
        contracts_dir = Path(__file__).resolve().parents[2] / "src" / "asf" / "contracts"

        # Purity check: no clock, random, uuid, open, os, network, etc.
        assert_pure_package(self, contracts_dir)

        # Import boundary check: asf.contracts may import only asf.configuration.platform
        # and asf.approval.models.
        allowed_asf_modules = {
            "asf.configuration.platform",
            "asf.approval.models",
            "asf.contracts",
            "asf.contracts.models",
        }

        for py_file in contracts_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("asf."):
                            self.assertIn(
                                alias.name,
                                allowed_asf_modules,
                                f"Forbidden import '{alias.name}' in {py_file.name}",
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module and node.module.startswith("asf."):
                        self.assertIn(
                            node.module,
                            allowed_asf_modules,
                            f"Forbidden import from '{node.module}' in {py_file.name}",
                        )
