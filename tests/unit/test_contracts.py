import copy
import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "contracts.schema.json"
)
with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
    SCHEMA = json.load(schema_file)

TIMESTAMP = "2026-10-20T14:00:00+07:00"


def metrics():
    return {
        "totalTasks": 0,
        "completedTasks": 0,
        "failedTasks": 0,
        "runningTasks": 0,
        "cancelledTasks": 0,
        "successRate": 0,
        "averageExecutionTime": 0,
        "averageRevisionCount": 0,
        "approvalRate": 0,
        "rejectionRate": 0,
        "testPassRate": 0,
        "ciPassRate": 0,
    }


def run_metrics():
    return {
        "durationSeconds": 1.5,
        "revisionCount": 0,
        "attempt": 1,
    }


def artifact():
    return {
        "id": "artifact-1",
        "type": "SPEC",
        "name": "Requirements",
        "version": "1",
        "content": {"summary": "Example"},
        "createdBy": "agent-spec",
        "createdAt": TIMESTAMP,
        "metadata": {},
    }


def activity_event():
    return {
        "id": "event-1",
        "timestamp": TIMESTAMP,
        "projectId": "sample",
        "taskId": "task-1",
        "workflowId": "software-development",
        "agentId": "agent-spec",
        "eventType": "AGENT_COMPLETED",
        "message": "Agent completed the request",
        "metadata": {},
    }


def retry_policy():
    return {
        "maxAttempts": 2,
        "backoffSeconds": 1,
        "retryOn": ["TIMEOUT"],
    }


def workflow_step():
    return {
        "id": "spec",
        "name": "Write specification",
        "type": "AGENT",
        "agentType": "spec",
        "requiresApproval": True,
        "timeout": 300,
        "retryPolicy": retry_policy(),
        "configuration": {},
    }


VALID_INSTANCES = {
    "AgentMetadata": {
        "id": "agent-spec",
        "name": "Specification Agent",
        "type": "spec",
        "version": "1.0.0",
        "status": "IDLE",
        "capabilities": ["write-spec"],
        "configuration": {},
    },
    "ValidationResult": {"valid": True, "errors": []},
    "AgentRequest": {
        "requestId": "request-1",
        "taskId": "task-1",
        "projectId": "sample",
        "workflowId": "software-development",
        "agentId": "agent-spec",
        "input": {"requirement": "Example"},
        "context": {},
        "artifacts": [artifact()],
        "metadata": {},
    },
    "AgentResult": {
        "requestId": "request-1",
        "agentId": "agent-spec",
        "status": "SUCCESS",
        "output": {"summary": "Example"},
        "artifacts": [artifact()],
        "events": [activity_event()],
        "metrics": run_metrics(),
        "errors": [],
    },
    "Artifact": artifact(),
    "Task": {
        "id": "task-1",
        "projectId": "sample",
        "workflowId": "software-development",
        "title": "Example task",
        "description": "Do useful work",
        "status": "NEW",
        "priority": "NORMAL",
        "assignedAgent": None,
        "stage": None,
        "artifacts": [artifact()],
        "createdAt": TIMESTAMP,
        "updatedAt": TIMESTAMP,
        "metadata": {},
    },
    "Workflow": {
        "id": "software-development",
        "name": "Software development",
        "version": "1",
        "projectId": "sample",
        "steps": [workflow_step()],
        "status": "ACTIVE",
        "currentStep": "spec",
        "metadata": {},
    },
    "ApprovalRequest": {
        "id": "approval-1",
        "taskId": "task-1",
        "workflowId": "software-development",
        "projectId": "sample",
        "artifactId": "artifact-1",
        "type": "SPEC",
        "status": "PENDING",
        "requestedBy": "orchestrator",
        "requestedAt": TIMESTAMP,
        "expiresAt": None,
        "metadata": {},
    },
    "ApprovalDecision": {
        "approvalId": "approval-1",
        "decision": "REQUEST_CHANGES",
        "reviewer": "reviewer-1",
        "comment": "Please clarify the requirements.",
        "createdAt": TIMESTAMP,
    },
    "ActivityEvent": activity_event(),
    "RunMetrics": run_metrics(),
    "AgentMetrics": metrics(),
    "Project": {
        "id": "sample",
        "name": "Sample project",
        "description": "A generic project",
        "repository": {"provider": "git"},
        "technology": {"backend": ["java"]},
        "enabledAgents": ["spec"],
        "enabledSkills": ["testing"],
        "workflow": "software-development",
        "configuration": {},
        "status": "ACTIVE",
    },
    "PlatformError": {
        "code": "AGENT_EXECUTION_FAILED",
        "message": "Execution failed",
        "category": "AGENT",
        "details": {},
        "retryable": True,
        "timestamp": TIMESTAMP,
    },
    "RetryPolicy": retry_policy(),
    "WorkflowStep": workflow_step(),
    "ModelRequest": {
        "messages": [{"role": "user", "content": "Hello"}],
        "parameters": {"temperature": 0.7},
        "model": "dummy-model",
        "metadata": {},
    },
    "ModelResponse": {
        "content": "Hello world",
        "model": "dummy-model",
        "usage": {"promptTokens": 10, "completionTokens": 5},
        "finishReason": "stop",
        "metadata": {},
    },
    "CodeChangeRequest": {
        "id": "cr-1",
        "projectId": "sample",
        "sourceBranch": "feature-1",
        "targetBranch": "main",
        "title": "Feature 1",
        "description": "Add feature",
        "status": "OPEN",
        "url": "https://git.example/cr-1",
        "metadata": {},
    },
    "PipelineRun": {
        "id": "run-1",
        "projectId": "sample",
        "ref": "main",
        "status": "RUNNING",
        "url": "https://ci.example/run-1",
        "startedAt": TIMESTAMP,
        "finishedAt": None,
        "metadata": {},
    },
}


def validator_for(definition):
    wrapped_schema = {
        "$schema": SCHEMA["$schema"],
        "$defs": SCHEMA["$defs"],
        "$ref": f"#/$defs/{definition}",
    }
    return Draft202012Validator(wrapped_schema, format_checker=FormatChecker())


class ContractSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Draft202012Validator.check_schema(SCHEMA)

    def test_valid_instances_for_every_contract(self):
        for definition, instance in VALID_INSTANCES.items():
            with self.subTest(contract=definition):
                validator_for(definition).validate(instance)

    def test_empty_objects_are_rejected_for_every_contract(self):
        for definition in VALID_INSTANCES:
            with self.subTest(contract=definition):
                self.assertFalse(validator_for(definition).is_valid({}))

    def test_agent_request_requires_identifiers_and_structured_input(self):
        instance = dict(VALID_INSTANCES["AgentRequest"], requestId="")
        self.assertFalse(validator_for("AgentRequest").is_valid(instance))
        instance = dict(VALID_INSTANCES["AgentRequest"], input="not-an-object")
        self.assertFalse(validator_for("AgentRequest").is_valid(instance))

    def test_agent_result_rejects_unknown_status(self):
        instance = dict(VALID_INSTANCES["AgentResult"], status="DONE")
        self.assertFalse(validator_for("AgentResult").is_valid(instance))

    def test_task_rejects_unknown_priority(self):
        instance = dict(VALID_INSTANCES["Task"], priority="URGENT")
        self.assertFalse(validator_for("Task").is_valid(instance))

    def test_artifact_requires_inline_content_or_reference(self):
        instance = dict(VALID_INSTANCES["Artifact"])
        instance.pop("content")
        self.assertFalse(validator_for("Artifact").is_valid(instance))
        instance["reference"] = "opaque://artifact-store/artifact-1"
        self.assertTrue(validator_for("Artifact").is_valid(instance))

    def test_workflow_rejects_step_without_agent_or_action(self):
        step = {
            "id": "step-1",
            "name": "Invalid step",
            "type": "SYSTEM",
            "requiresApproval": False,
            "configuration": {},
        }
        workflow = dict(VALID_INSTANCES["Workflow"], steps=[step])
        self.assertFalse(validator_for("Workflow").is_valid(workflow))

    def test_approval_rejects_unknown_status_and_decision(self):
        request = dict(VALID_INSTANCES["ApprovalRequest"], status="WAITING")
        decision = dict(VALID_INSTANCES["ApprovalDecision"], decision="MAYBE")
        self.assertFalse(validator_for("ApprovalRequest").is_valid(request))
        self.assertFalse(validator_for("ApprovalDecision").is_valid(decision))

    def test_activity_event_rejects_invalid_timestamp(self):
        event = dict(VALID_INSTANCES["ActivityEvent"], timestamp="not-a-date")
        self.assertFalse(validator_for("ActivityEvent").is_valid(event))

    def test_project_requires_project_independent_contract_fields(self):
        project = dict(VALID_INSTANCES["Project"])
        project.pop("enabledSkills")
        self.assertFalse(validator_for("Project").is_valid(project))

    def test_metrics_reject_out_of_range_rates_and_negative_counts(self):
        invalid_rate = dict(metrics(), successRate=1.1)
        invalid_count = dict(metrics(), totalTasks=-1)
        self.assertFalse(validator_for("AgentMetrics").is_valid(invalid_rate))
        self.assertFalse(validator_for("AgentMetrics").is_valid(invalid_count))

    def test_extensible_type_names_are_accepted(self):
        custom_artifact = dict(VALID_INSTANCES["Artifact"], type="CUSTOM_REPORT")
        custom_event = dict(VALID_INSTANCES["ActivityEvent"], eventType="CUSTOM_EVENT")
        custom_step = dict(VALID_INSTANCES["Workflow"]["steps"][0], type="CUSTOM_STEP")
        self.assertTrue(validator_for("Artifact").is_valid(custom_artifact))
        self.assertTrue(validator_for("ActivityEvent").is_valid(custom_event))
        workflow_instance = dict(VALID_INSTANCES["Workflow"], steps=[custom_step])
        self.assertTrue(validator_for("Workflow").is_valid(workflow_instance))

    def test_schema_coverage_guard(self):
        expected_defs = set(SCHEMA["$defs"].keys()) - {"Metadata", "AgentStatus", "MetricRate"}
        self.assertEqual(set(VALID_INSTANCES.keys()), expected_defs)

    def test_agent_status_and_metric_rate(self):
        self.assertTrue(validator_for("AgentStatus").is_valid("IDLE"))
        self.assertFalse(validator_for("AgentStatus").is_valid("NOT_A_STATUS"))
        self.assertTrue(validator_for("MetricRate").is_valid(0.5))
        self.assertTrue(validator_for("MetricRate").is_valid(0))
        self.assertTrue(validator_for("MetricRate").is_valid(1))
        self.assertFalse(validator_for("MetricRate").is_valid(1.5))
        self.assertFalse(validator_for("MetricRate").is_valid(-0.1))
        self.assertFalse(validator_for("MetricRate").is_valid("high"))

    def test_additional_properties_rejected_for_closed_objects(self):
        for def_name, def_schema in SCHEMA["$defs"].items():
            if (
                def_schema.get("type") == "object"
                and def_schema.get("additionalProperties") is False
            ):
                with self.subTest(contract=def_name):
                    instance = copy.deepcopy(VALID_INSTANCES[def_name])
                    instance["unexpectedField"] = "unexpected"
                    self.assertFalse(validator_for(def_name).is_valid(instance))

    def test_nullable_fields_accept_null(self):
        task = dict(VALID_INSTANCES["Task"], assignedAgent=None)
        self.assertTrue(validator_for("Task").is_valid(task))

        approval = dict(VALID_INSTANCES["ApprovalRequest"], expiresAt=None)
        self.assertTrue(validator_for("ApprovalRequest").is_valid(approval))

        workflow = dict(VALID_INSTANCES["Workflow"], currentStep=None)
        self.assertTrue(validator_for("Workflow").is_valid(workflow))

        event_null_task = dict(VALID_INSTANCES["ActivityEvent"], taskId=None)
        self.assertTrue(validator_for("ActivityEvent").is_valid(event_null_task))

        event_null_wf = dict(VALID_INSTANCES["ActivityEvent"], workflowId=None)
        self.assertTrue(validator_for("ActivityEvent").is_valid(event_null_wf))

        event_null_agent = dict(VALID_INSTANCES["ActivityEvent"], agentId=None)
        self.assertTrue(validator_for("ActivityEvent").is_valid(event_null_agent))

        event_all_null = dict(
            VALID_INSTANCES["ActivityEvent"],
            taskId=None,
            workflowId=None,
            agentId=None,
        )
        self.assertTrue(validator_for("ActivityEvent").is_valid(event_all_null))

    def test_closed_enums(self):
        enums_to_test = [
            (
                "AgentStatus",
                validator_for("AgentStatus"),
                ["IDLE", "RUNNING", "WAITING", "ERROR", "DISABLED", "OFFLINE"],
                "INVALID_STATUS",
                lambda val: val,
            ),
            (
                "AgentResult.status",
                validator_for("AgentResult"),
                ["SUCCESS", "FAILED", "REJECTED", "WAITING", "CANCELLED"],
                "INVALID_STATUS",
                lambda val: dict(VALID_INSTANCES["AgentResult"], status=val),
            ),
            (
                "Task.status",
                validator_for("Task"),
                ["NEW", "IN_PROGRESS", "WAITING", "COMPLETED", "FAILED", "CANCELLED"],
                "INVALID_STATUS",
                lambda val: dict(VALID_INSTANCES["Task"], status=val),
            ),
            (
                "Task.priority",
                validator_for("Task"),
                ["LOW", "NORMAL", "HIGH", "CRITICAL"],
                "INVALID_PRIORITY",
                lambda val: dict(VALID_INSTANCES["Task"], priority=val),
            ),
            (
                "Workflow.status",
                validator_for("Workflow"),
                ["DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "FAILED", "CANCELLED"],
                "INVALID_STATUS",
                lambda val: dict(VALID_INSTANCES["Workflow"], status=val),
            ),
            (
                "ApprovalRequest.status",
                validator_for("ApprovalRequest"),
                ["PENDING", "APPROVED", "REJECTED", "CHANGES_REQUESTED", "CANCELLED", "EXPIRED"],
                "INVALID_STATUS",
                lambda val: dict(VALID_INSTANCES["ApprovalRequest"], status=val),
            ),
            (
                "ApprovalDecision.decision",
                validator_for("ApprovalDecision"),
                ["APPROVED", "REJECTED", "REQUEST_CHANGES"],
                "INVALID_DECISION",
                lambda val: dict(VALID_INSTANCES["ApprovalDecision"], decision=val),
            ),
            (
                "PlatformError.category",
                validator_for("PlatformError"),
                [
                    "VALIDATION",
                    "AGENT",
                    "WORKFLOW",
                    "APPROVAL",
                    "INTEGRATION",
                    "LLM",
                    "GIT",
                    "CI",
                    "SYSTEM",
                ],
                "INVALID_CATEGORY",
                lambda val: dict(VALID_INSTANCES["PlatformError"], category=val),
            ),
            (
                "Project.status",
                validator_for("Project"),
                ["ACTIVE", "INACTIVE", "ARCHIVED"],
                "INVALID_STATUS",
                lambda val: dict(VALID_INSTANCES["Project"], status=val),
            ),
        ]
        for enum_name, validator, valid_values, invalid_value, instance_builder in enums_to_test:
            for val in valid_values:
                with self.subTest(enum=enum_name, value=val):
                    self.assertTrue(validator.is_valid(instance_builder(val)))
            with self.subTest(enum=enum_name, invalid=invalid_value):
                self.assertFalse(validator.is_valid(instance_builder(invalid_value)))

    def test_validation_result_platform_error_category(self):
        valid_error = dict(VALID_INSTANCES["PlatformError"])
        valid_result = {"valid": False, "errors": [valid_error]}
        self.assertTrue(validator_for("ValidationResult").is_valid(valid_result))

        invalid_error = dict(VALID_INSTANCES["PlatformError"], category="BAD")
        invalid_result = {"valid": False, "errors": [invalid_error]}
        self.assertFalse(validator_for("ValidationResult").is_valid(invalid_result))

    def test_artifact_content_and_reference_combinations(self):
        content_only = dict(VALID_INSTANCES["Artifact"])
        content_only.pop("reference", None)
        self.assertTrue(validator_for("Artifact").is_valid(content_only))

        ref_only = dict(VALID_INSTANCES["Artifact"])
        ref_only.pop("content", None)
        ref_only["reference"] = "opaque://artifact-store/artifact-1"
        self.assertTrue(validator_for("Artifact").is_valid(ref_only))

        both = dict(VALID_INSTANCES["Artifact"])
        both["content"] = {"summary": "Example"}
        both["reference"] = "opaque://artifact-store/artifact-1"
        self.assertTrue(validator_for("Artifact").is_valid(both))

        neither = dict(VALID_INSTANCES["Artifact"])
        neither.pop("content", None)
        neither.pop("reference", None)
        self.assertFalse(validator_for("Artifact").is_valid(neither))

    def test_workflow_step_action_or_agent_type(self):
        agent_only = dict(VALID_INSTANCES["WorkflowStep"])
        agent_only.pop("action", None)
        agent_only["agentType"] = "spec"
        self.assertTrue(validator_for("WorkflowStep").is_valid(agent_only))

        action_only = dict(VALID_INSTANCES["WorkflowStep"])
        action_only.pop("agentType", None)
        action_only["action"] = "build-image"
        self.assertTrue(validator_for("WorkflowStep").is_valid(action_only))

        neither = dict(VALID_INSTANCES["WorkflowStep"])
        neither.pop("agentType", None)
        neither.pop("action", None)
        self.assertFalse(validator_for("WorkflowStep").is_valid(neither))

    def test_metadata_typed_fields_accept_arbitrary_nested_json(self):
        nested_meta = {
            "str": "value",
            "num": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, "two", None, {"sub": "obj"}],
            "nested": {"a": {"b": [1, 2, 3]}},
        }
        artifact_instance = dict(VALID_INSTANCES["Artifact"], metadata=nested_meta)
        self.assertTrue(validator_for("Artifact").is_valid(artifact_instance))

        project_instance = dict(VALID_INSTANCES["Project"], configuration=nested_meta)
        self.assertTrue(validator_for("Project").is_valid(project_instance))

        step_instance = dict(VALID_INSTANCES["WorkflowStep"], configuration=nested_meta)
        self.assertTrue(validator_for("WorkflowStep").is_valid(step_instance))

    # Commit 2: Tests for schema additions and modifications
    def test_task_stage_property(self):
        missing_stage = dict(VALID_INSTANCES["Task"])
        missing_stage.pop("stage")
        self.assertFalse(validator_for("Task").is_valid(missing_stage))

        string_stage = dict(VALID_INSTANCES["Task"], stage="DEVELOPMENT")
        self.assertTrue(validator_for("Task").is_valid(string_stage))

        null_stage = dict(VALID_INSTANCES["Task"], stage=None)
        self.assertTrue(validator_for("Task").is_valid(null_stage))

    def test_agent_result_run_metrics_validation(self):
        # Rejects aggregate AgentMetrics object (no durationSeconds, revisionCount, attempt)
        aggregate_metrics_instance = dict(VALID_INSTANCES["AgentResult"], metrics=metrics())
        self.assertFalse(validator_for("AgentResult").is_valid(aggregate_metrics_instance))

        # Rejects negative durationSeconds
        negative_duration = dict(
            VALID_INSTANCES["AgentResult"],
            metrics=dict(run_metrics(), durationSeconds=-1.0),
        )
        self.assertFalse(validator_for("AgentResult").is_valid(negative_duration))

        # Rejects attempt 0 (minimum is 1)
        zero_attempt = dict(
            VALID_INSTANCES["AgentResult"],
            metrics=dict(run_metrics(), attempt=0),
        )
        self.assertFalse(validator_for("AgentResult").is_valid(zero_attempt))

        # Rejects negative revisionCount
        negative_revision = dict(
            VALID_INSTANCES["AgentResult"],
            metrics=dict(run_metrics(), revisionCount=-1),
        )
        self.assertFalse(validator_for("AgentResult").is_valid(negative_revision))

    def test_approval_request_status_split(self):
        valid_request = dict(VALID_INSTANCES["ApprovalRequest"], status="CHANGES_REQUESTED")
        self.assertTrue(validator_for("ApprovalRequest").is_valid(valid_request))

        # REQUEST_CHANGES is a decision, not an ApprovalRequest status
        invalid_request = dict(VALID_INSTANCES["ApprovalRequest"], status="REQUEST_CHANGES")
        self.assertFalse(validator_for("ApprovalRequest").is_valid(invalid_request))

    def test_approval_request_type_open(self):
        custom_type_request = dict(VALID_INSTANCES["ApprovalRequest"], type="CUSTOM_REVIEW")
        self.assertTrue(validator_for("ApprovalRequest").is_valid(custom_type_request))

        empty_type_request = dict(VALID_INSTANCES["ApprovalRequest"], type="")
        self.assertFalse(validator_for("ApprovalRequest").is_valid(empty_type_request))

    def test_model_request_validation(self):
        empty_messages = dict(VALID_INSTANCES["ModelRequest"], messages=[])
        self.assertFalse(validator_for("ModelRequest").is_valid(empty_messages))

        unknown_role = dict(
            VALID_INSTANCES["ModelRequest"],
            messages=[{"role": "unknown", "content": "hi"}],
        )
        self.assertFalse(validator_for("ModelRequest").is_valid(unknown_role))

        valid_request = dict(
            VALID_INSTANCES["ModelRequest"],
            messages=[{"role": "user", "content": "hi"}],
        )
        self.assertTrue(validator_for("ModelRequest").is_valid(valid_request))

    def test_model_response_validation(self):
        negative_prompt_tokens = dict(
            VALID_INSTANCES["ModelResponse"],
            usage={"promptTokens": -1, "completionTokens": 5},
        )
        self.assertFalse(validator_for("ModelResponse").is_valid(negative_prompt_tokens))

        negative_completion_tokens = dict(
            VALID_INSTANCES["ModelResponse"],
            usage={"promptTokens": 10, "completionTokens": -1},
        )
        self.assertFalse(validator_for("ModelResponse").is_valid(negative_completion_tokens))

    def test_code_change_request_and_pipeline_run_validation(self):
        invalid_cr_status = dict(VALID_INSTANCES["CodeChangeRequest"], status="UNKNOWN")
        self.assertFalse(validator_for("CodeChangeRequest").is_valid(invalid_cr_status))

        null_cr_url = dict(VALID_INSTANCES["CodeChangeRequest"], url=None)
        self.assertTrue(validator_for("CodeChangeRequest").is_valid(null_cr_url))

        invalid_run_status = dict(VALID_INSTANCES["PipelineRun"], status="UNKNOWN")
        self.assertFalse(validator_for("PipelineRun").is_valid(invalid_run_status))

        null_run_url = dict(VALID_INSTANCES["PipelineRun"], url=None)
        self.assertTrue(validator_for("PipelineRun").is_valid(null_run_url))

    def test_pipeline_run_finished_at(self):
        invalid_finished_at = dict(VALID_INSTANCES["PipelineRun"], finishedAt="not-a-date")
        self.assertFalse(validator_for("PipelineRun").is_valid(invalid_finished_at))

        null_finished_at = dict(VALID_INSTANCES["PipelineRun"], finishedAt=None)
        self.assertTrue(validator_for("PipelineRun").is_valid(null_finished_at))

        valid_finished_at = dict(VALID_INSTANCES["PipelineRun"], finishedAt=TIMESTAMP)
        self.assertTrue(validator_for("PipelineRun").is_valid(valid_finished_at))

    def test_ports_contract_references(self):
        ports_path = Path(__file__).resolve().parents[2] / "contracts" / "ports.md"
        with ports_path.open(encoding="utf-8") as f:
            ports_content = f.read()

        port_names = {
            "Agent",
            "AgentRegistry",
            "ArtifactRepository",
            "TaskRepository",
            "WorkflowRepository",
            "ApprovalService",
            "EventPublisher",
            "MetricsService",
            "ProjectRepository",
            "ModelGateway",
            "SourceControl",
            "CiProvider",
        }

        # Signature types (parameter types and return types)
        sig_types = set(re.findall(r"(?::\s*|->\s*)([A-Z][a-zA-Z0-9]+)", ports_content))
        contract_sig_types = sig_types - port_names

        # Every contract name used in signatures must exist in $defs
        for type_name in contract_sig_types:
            with self.subTest(signature_type=type_name):
                self.assertIn(type_name, SCHEMA["$defs"])

        # All expected contract types are present in port signatures
        expected_contracts = {
            "AgentMetadata",
            "AgentRequest",
            "ValidationResult",
            "AgentResult",
            "Artifact",
            "Task",
            "Workflow",
            "ApprovalRequest",
            "ApprovalDecision",
            "ActivityEvent",
            "AgentMetrics",
            "Project",
            "ModelRequest",
            "ModelResponse",
            "CodeChangeRequest",
            "PipelineRun",
        }
        self.assertTrue(expected_contracts.issubset(contract_sig_types))


if __name__ == "__main__":
    unittest.main()
