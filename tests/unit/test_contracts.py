import json
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
        "metrics": metrics(),
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
        "steps": [
            {
                "id": "spec",
                "name": "Write specification",
                "type": "AGENT",
                "agentType": "spec",
                "requiresApproval": True,
                "timeout": 300,
                "retryPolicy": {"maxAttempts": 2, "backoffSeconds": 1},
                "configuration": {},
            }
        ],
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


if __name__ == "__main__":
    unittest.main()
