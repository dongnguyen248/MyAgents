from __future__ import annotations

import copy
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asf.agents.base import AgentRuntime
from asf.agents.loading import load_task_prompts, load_task_template
from asf.agents.task.agent import (
    MAX_TASK_CHARS,
    MAX_TASKS,
    TaskAgent,
    TaskItem,
    render_task_markdown,
)
from asf.contracts.models import (
    AgentRequest,
    ApprovalFeedback,
    Artifact,
)
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from tests.unit.contract_models import validator_for

REPO_ROOT = Path(__file__).resolve().parents[2]
T_AWARE = datetime(2026, 10, 20, 14, 0, 0, tzinfo=UTC)


def counter_id(prefix: str = "id-"):
    count = 0

    def _next() -> str:
        nonlocal count
        count += 1
        return f"{prefix}{count}"

    return _next


def make_valid_task_reply(
    *,
    spec_id: str = "spec-123",
    spec_version: str = "1",
    plan_id: str = "plan-123",
    plan_version: str = "1",
    task_count: int = 3,
    milestones: list[tuple[str, str]] | None = None,
) -> str:
    """Creates a valid TASK reply JSON with sequential task IDs and valid structure."""
    if milestones is None:
        milestones = [("M1", "Setup"), ("M2", "Core"), ("M3", "Integration")]

    tasks = []
    task_num = 1
    for milestone_id, milestone_name in milestones:
        # Distribute tasks across milestones
        tasks_per_milestone = max(1, task_count // len(milestones))
        for i in range(tasks_per_milestone):
            if task_num > task_count:
                break
            depends_on = []
            if task_num > 1:
                depends_on.append(f"T{task_num - 1}")
            tasks.append(
                {
                    "id": f"T{task_num}",
                    "title": f"Task {task_num}: {milestone_name} part {i + 1}",
                    "milestoneRef": milestone_id,
                    "description": f"Implement {milestone_name} part {i + 1}",
                    "acceptanceCriteria": [f"Criterion {task_num}.1", f"Criterion {task_num}.2"],
                    "dependsOn": depends_on,
                    "expectedFiles": [f"src/{milestone_id.lower()}/task{task_num}.py"],
                    "verificationHint": f"Run tests for {milestone_id} task {task_num}",
                }
            )
            task_num += 1

    reply = {"tasks": tasks}
    return json.dumps(reply, indent=2)


class TaskAgentTests(unittest.TestCase):
    def setUp(self):
        self.prompts = load_task_prompts()
        self.template = load_task_template(REPO_ROOT / "templates")
        self.valid_reply = make_valid_task_reply(
            spec_id="spec-123",
            spec_version="1",
            plan_id="plan-123",
            plan_version="1",
            task_count=3,
            milestones=[("M1", "Setup"), ("M2", "Core")],
        )

    def _make_agent(
        self,
        script: list[Any],
        *,
        model: str | None = "test-model",
        parameters: dict[str, Any] | None = None,
        clock=None,
        new_id=None,
    ) -> tuple[TaskAgent, ScriptedModelGateway]:
        gateway = ScriptedModelGateway(script)
        clk = clock or (lambda: T_AWARE)
        nid = new_id or counter_id("gen-")
        runtime = AgentRuntime(models=gateway, clock=clk, new_id=nid)
        agent = TaskAgent(
            runtime,
            prompts=self.prompts,
            template=self.template,
            model=model,
            parameters=parameters or {"temperature": 0.3},
        )
        return agent, gateway

    def _make_spec_artifact(
        self,
        *,
        artifact_id: str = "spec-123",
        version: str = "1",
        text: str = "# SPEC: Test Spec\n## Background / Goal\nTest spec content.",
    ) -> Artifact:
        return Artifact(
            id=artifact_id,
            type="SPEC",
            name="SPEC.md",
            version=version,
            content={"format": "markdown", "text": text},
            created_by="agent-spec",
            created_at=T_AWARE,
            metadata={"template": "spec"},
        )

    def _make_plan_artifact(
        self,
        *,
        artifact_id: str = "plan-123",
        version: str = "1",
        text: str = (
            "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n"
            "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
            "### M2: Core\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M1"
        ),
    ) -> Artifact:
        return Artifact(
            id=artifact_id,
            type="PLAN",
            name="PLAN.md",
            version=version,
            content={"format": "markdown", "text": text},
            created_by="agent-plan",
            created_at=T_AWARE,
            metadata={
                "template": "plan",
                "specArtifactId": "spec-123",
                "specVersion": "1",
            },
        )

    def _make_task_artifact(
        self,
        *,
        artifact_id: str = "task-123",
        version: str = "1",
        text: str = '{"tasks": []}',
    ) -> Artifact:
        return Artifact(
            id=artifact_id,
            type="TASK",
            name="TASK.md",
            version=version,
            content={"format": "json", "text": text},
            created_by="agent-task",
            created_at=T_AWARE,
            metadata={"template": "task"},
        )

    def _make_request(
        self,
        *,
        spec_artifact: Artifact | None = None,
        plan_artifact: Artifact | None = None,
        task_artifact: Artifact | None = None,
        feedback: list[ApprovalFeedback] | None = None,
        agent_id: str = "agent-task",
        metadata: dict[str, Any] | None = None,
        project_context: dict[str, Any] | None = None,
        language: str | None = None,
    ) -> AgentRequest:
        spec_art = spec_artifact or self._make_spec_artifact()
        plan_art = plan_artifact or self._make_plan_artifact()

        artifacts = [spec_art, plan_art]
        if task_artifact:
            artifacts.append(task_artifact)

        inp: dict[str, Any] = {}
        if language is not None:
            inp["language"] = language

        ctx: dict[str, Any] = {}
        if project_context is not None:
            ctx["project"] = project_context
        else:
            ctx["project"] = {
                "name": "AuthService",
                "description": "Handles authentication",
                "technology": ["python", "fastapi"],
            }

        return AgentRequest(
            request_id="req-123",
            task_id="task-456",
            project_id="proj-789",
            workflow_id="software-development",
            agent_id=agent_id,
            input=inp,
            context=ctx,
            artifacts=artifacts,
            feedback=feedback or [],
            metadata=metadata if metadata is not None else {"attempt": 1},
        )

    def test_happy_path_task_creation(self):
        agent, gateway = self._make_agent(
            [self.valid_reply], model="custom-task-llm", parameters={"temp": 0.1}
        )
        req = self._make_request(language="en")

        val_res = agent.validate(req)
        self.assertTrue(val_res.valid)
        self.assertEqual(val_res.errors, [])

        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.errors, [])
        self.assertEqual(len(res.artifacts), 1)

        # Artifact checks
        art = res.artifacts[0]
        self.assertEqual(art.type, "TASK")
        self.assertEqual(art.name, "TASK.md")
        self.assertEqual(art.version, "1")
        self.assertEqual(art.created_by, "agent-task")
        self.assertEqual(art.created_at, T_AWARE)
        self.assertEqual(art.metadata["template"], "task")
        self.assertEqual(art.metadata["model"], "custom-task-llm")
        self.assertIn("promptTokens", art.metadata["usage"])
        self.assertIn("completionTokens", art.metadata["usage"])
        self.assertEqual(art.metadata["language"], "en")
        self.assertNotIn("revisionOf", art.metadata)
        # Traceability fields
        self.assertEqual(art.metadata["specArtifactId"], "spec-123")
        self.assertEqual(art.metadata["specVersion"], "1")
        self.assertEqual(art.metadata["planArtifactId"], "plan-123")
        self.assertEqual(art.metadata["planVersion"], "1")

        # Content should have format: json, tasks array, and rendered text
        content = art.content
        self.assertEqual(content["format"], "json")
        self.assertIn("tasks", content)
        self.assertIn("text", content)
        self.assertIsInstance(content["tasks"], list)
        self.assertIsInstance(content["text"], str)

        # Output checks
        self.assertEqual(
            res.output,
            {
                "summary": "Task breakdown created",
                "artifactId": art.id,
                "version": "1",
            },
        )

        # Event checks
        event_types = [e.event_type for e in res.events]
        self.assertEqual(
            event_types,
            ["AGENT_STARTED", "ARTIFACT_CREATED", "AGENT_COMPLETED"],
        )

        # Whole result schema validation
        validator_for("AgentResult").validate(res.to_contract())

        # Gateway call checks
        self.assertEqual(len(gateway.requests), 1)
        gw_req = gateway.requests[0]
        self.assertEqual(gw_req.model, "custom-task-llm")
        self.assertEqual(gw_req.parameters, {"temp": 0.1})
        self.assertEqual(gw_req.metadata["agentId"], "agent-task")
        self.assertEqual(gw_req.metadata["requestId"], "req-123")
        self.assertEqual(gw_req.metadata["cachePrefixMessages"], 1)
        self.assertEqual(len(gw_req.messages), 2)
        self.assertEqual(gw_req.messages[0].role, "system")
        self.assertEqual(gw_req.messages[1].role, "user")

        # User message fixed sections in order
        user_body = gw_req.messages[1].content
        self.assertIn("## Linked SPEC", user_body)
        self.assertIn("ID: spec-123", user_body)
        self.assertIn("Version: 1", user_body)
        self.assertIn("## Linked PLAN", user_body)
        self.assertIn("ID: plan-123", user_body)
        self.assertIn("Version: 1", user_body)
        self.assertIn("## Output language\nen", user_body)
        self.assertIn("## Project context\n", user_body)
        self.assertIn("## Template\n", user_body)
        pos_spec = user_body.find("## Linked SPEC")
        pos_plan = user_body.find("## Linked PLAN")
        pos_lang = user_body.find("## Output language")
        pos_proj = user_body.find("## Project context")
        pos_tpl = user_body.find("## Template")
        self.assertTrue(pos_spec < pos_plan < pos_lang < pos_proj < pos_tpl)

    def test_revision_mode_flow(self):
        agent, gateway = self._make_agent([self.valid_reply])

        prev_task = self._make_task_artifact(
            artifact_id="task-v1",
            version="1",
            text=(
                '{"tasks": [{"id": "T1", "title": "Old", "milestoneRef": "M1", '
                '"description": "Old", "acceptanceCriteria": ["AC1"], '
                '"dependsOn": [], "expectedFiles": [], "verificationHint": "hint"}]}'
            ),
        )
        fb1 = ApprovalFeedback(
            approval_id="app-1",
            reviewer="alice",
            decision="REQUEST_CHANGES",
            comment="Add more tasks",
        )
        fb2 = ApprovalFeedback(
            approval_id="app-1",
            reviewer="bob",
            decision="REJECTED",
            comment="Tasks too granular",
        )

        req = self._make_request(
            task_artifact=prev_task,
            feedback=[fb1, fb2],
            metadata={"attempt": 2},
        )

        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(len(res.artifacts), 1)
        art = res.artifacts[0]
        self.assertEqual(art.version, "2")
        self.assertEqual(art.metadata["revisionOf"], "task-v1")
        self.assertEqual(art.metadata["specArtifactId"], "spec-123")
        self.assertEqual(art.metadata["specVersion"], "1")
        self.assertEqual(art.metadata["planArtifactId"], "plan-123")
        self.assertEqual(art.metadata["planVersion"], "1")
        self.assertEqual(res.metrics.revision_count, 1)
        self.assertEqual(res.metrics.attempt, 2)
        self.assertEqual(
            res.output,
            {
                "summary": "Task breakdown revised",
                "artifactId": art.id,
                "version": "2",
            },
        )

        # Gateway request contains previous task and reviewer comments
        gw_req = gateway.requests[0]
        user_msg = gw_req.messages[1].content
        self.assertIn("## Previous task (version 1)", user_msg)
        self.assertIn("- [REQUEST_CHANGES] alice: Add more tasks", user_msg)
        self.assertIn("- [REJECTED] bob: Tasks too granular", user_msg)

        # System message contains revision prompt
        sys_msg = gw_req.messages[0].content
        self.assertIn("reviewer feedback", sys_msg.lower())

    def test_validate_zero_spec_artifacts(self):
        agent, gateway = self._make_agent([])
        valid_plan = self._make_plan_artifact()
        req = AgentRequest(
            request_id="req-1",
            task_id="task-1",
            project_id="proj-1",
            workflow_id="software-development",
            agent_id="agent-task",
            input={},
            context={
                "project": {
                    "name": "Test",
                    "description": "Test",
                    "technology": ["python"],
                }
            },
            artifacts=[valid_plan],  # No SPEC
            feedback=[],
            metadata={"attempt": 1},
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_two_spec_artifacts(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = AgentRequest(
            request_id="req-2",
            task_id="task-2",
            project_id="proj-2",
            workflow_id="software-development",
            agent_id="agent-task",
            input={},
            context={
                "project": {
                    "name": "Test",
                    "description": "Test",
                    "technology": ["python"],
                }
            },
            artifacts=[valid_spec, valid_spec, valid_plan],
            feedback=[],
            metadata={"attempt": 1},
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_spec_artifact_without_text_content(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            spec_artifact=Artifact(
                id="spec-1",
                type="SPEC",
                name="SPEC.md",
                version="1",
                content={"summary": "no text"},
                created_by="agent-spec",
                created_at=T_AWARE,
            )
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[0].content.text", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_spec_artifact_bad_version_zero(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            spec_artifact=Artifact(
                id="spec-1",
                type="SPEC",
                name="SPEC.md",
                version="0",
                content={"text": "text"},
                created_by="agent-spec",
                created_at=T_AWARE,
            )
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[0].version", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_spec_artifact_bad_version_v1(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            spec_artifact=Artifact(
                id="spec-1",
                type="SPEC",
                name="SPEC.md",
                version="v1",
                content={"text": "text"},
                created_by="agent-spec",
                created_at=T_AWARE,
            )
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[0].version", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_spec_artifact_bad_version_1_2(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            spec_artifact=Artifact(
                id="spec-1",
                type="SPEC",
                name="SPEC.md",
                version="1.2",
                content={"text": "text"},
                created_by="agent-spec",
                created_at=T_AWARE,
            )
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[0].version", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_zero_plan_artifacts(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        req = AgentRequest(
            request_id="req-7",
            task_id="task-7",
            project_id="proj-7",
            workflow_id="software-development",
            agent_id="agent-task",
            input={},
            context={
                "project": {
                    "name": "Test",
                    "description": "Test",
                    "technology": ["python"],
                }
            },
            artifacts=[valid_spec],
            feedback=[],
            metadata={"attempt": 1},
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_two_plan_artifacts(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = AgentRequest(
            request_id="req-8",
            task_id="task-8",
            project_id="proj-8",
            workflow_id="software-development",
            agent_id="agent-task",
            input={},
            context={
                "project": {
                    "name": "Test",
                    "description": "Test",
                    "technology": ["python"],
                }
            },
            artifacts=[valid_spec, valid_plan, valid_plan],
            feedback=[],
            metadata={"attempt": 1},
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_plan_artifact_without_text_content(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            plan_artifact=Artifact(
                id="plan-1",
                type="PLAN",
                name="PLAN.md",
                version="1",
                content={"summary": "no text"},
                created_by="agent-plan",
                created_at=T_AWARE,
            )
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[1].content.text", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_plan_artifact_bad_version_zero(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            plan_artifact=Artifact(
                id="plan-1",
                type="PLAN",
                name="PLAN.md",
                version="0",
                content={"text": "text"},
                created_by="agent-plan",
                created_at=T_AWARE,
            )
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[1].version", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_plan_artifact_bad_version_v1(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            plan_artifact=Artifact(
                id="plan-1",
                type="PLAN",
                name="PLAN.md",
                version="v1",
                content={"text": "text"},
                created_by="agent-plan",
                created_at=T_AWARE,
            )
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[1].version", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_plan_artifact_unparseable_no_milestones(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            plan_artifact=Artifact(
                id="plan-1",
                type="PLAN",
                name="PLAN.md",
                version="1",
                content={
                    "text": (
                        "# PLAN: No Milestones\n## Linked SPEC\n...\n"
                        "## Description\nNo milestones here"
                    )
                },
                created_by="agent-plan",
                created_at=T_AWARE,
            )
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[1].content.text", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_more_than_one_task_artifact(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = AgentRequest(
            request_id="req-13",
            task_id="task-13",
            project_id="proj-13",
            workflow_id="software-development",
            agent_id="agent-task",
            input={},
            context={
                "project": {
                    "name": "Test",
                    "description": "Test",
                    "technology": ["python"],
                }
            },
            artifacts=[
                valid_spec,
                valid_plan,
                self._make_task_artifact(artifact_id="task-1", version="1"),
                self._make_task_artifact(artifact_id="task-2", version="2"),
            ],
            feedback=[],
            metadata={"attempt": 1},
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_task_artifact_without_feedback(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            task_artifact=self._make_task_artifact(artifact_id="task-1", version="1"),
            feedback=[],
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("feedback", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_feedback_without_task_artifact(self):
        agent, gateway = self._make_agent([])
        valid_feedback = [
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="rev-1",
                decision="REQUEST_CHANGES",
                comment="Fix it",
            )
        ]
        req = self._make_request(feedback=valid_feedback)
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_task_artifact_without_text_content(self):
        agent, gateway = self._make_agent([])
        valid_feedback = [
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="rev-1",
                decision="REQUEST_CHANGES",
                comment="Fix it",
            )
        ]
        req = self._make_request(
            task_artifact=Artifact(
                id="task-1",
                type="TASK",
                name="TASK.md",
                version="1",
                content={"summary": "no text"},
                created_by="agent-task",
                created_at=T_AWARE,
            ),
            feedback=valid_feedback,
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[2].content.text", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_task_artifact_bad_version_zero(self):
        agent, gateway = self._make_agent([])
        valid_feedback = [
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="rev-1",
                decision="REQUEST_CHANGES",
                comment="Fix it",
            )
        ]
        req = self._make_request(
            task_artifact=Artifact(
                id="task-1",
                type="TASK",
                name="TASK.md",
                version="0",
                content={"text": "text"},
                created_by="agent-task",
                created_at=T_AWARE,
            ),
            feedback=valid_feedback,
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[2].version", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_task_artifact_bad_version_v1(self):
        agent, gateway = self._make_agent([])
        valid_feedback = [
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="rev-1",
                decision="REQUEST_CHANGES",
                comment="Fix it",
            )
        ]
        req = self._make_request(
            task_artifact=Artifact(
                id="task-1",
                type="TASK",
                name="TASK.md",
                version="v1",
                content={"text": "text"},
                created_by="agent-task",
                created_at=T_AWARE,
            ),
            feedback=valid_feedback,
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[2].version", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_unknown_artifact_type(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = AgentRequest(
            request_id="req-19",
            task_id="task-19",
            project_id="proj-19",
            workflow_id="software-development",
            agent_id="agent-task",
            input={},
            context={
                "project": {
                    "name": "Test",
                    "description": "Test",
                    "technology": ["python"],
                }
            },
            artifacts=[
                valid_spec,
                valid_plan,
                Artifact(
                    id="unknown-1",
                    type="UNKNOWN",
                    name="UNKNOWN.md",
                    version="1",
                    content={"text": "text"},
                    created_by="agent-other",
                    created_at=T_AWARE,
                ),
            ],
            feedback=[],
            metadata={"attempt": 1},
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts[2].type", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_disallowed_input_key(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = AgentRequest(
            request_id="req-20",
            task_id="task-20",
            project_id="proj-20",
            workflow_id="software-development",
            agent_id="agent-task",
            input={"requirement": "test"},
            context={
                "project": {
                    "name": "Test",
                    "description": "Test",
                    "technology": ["python"],
                }
            },
            artifacts=[valid_spec, valid_plan],
            feedback=[],
            metadata={"attempt": 1},
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("input.requirement", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_bad_language_empty_string(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = self._make_request(spec_artifact=valid_spec, plan_artifact=valid_plan, language="")
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("input.language", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_bad_language_whitespace_only(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = self._make_request(spec_artifact=valid_spec, plan_artifact=valid_plan, language="   ")
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("input.language", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_bad_attempt_zero(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = self._make_request(
            spec_artifact=valid_spec, plan_artifact=valid_plan, metadata={"attempt": 0}
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("metadata.attempt", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_bad_attempt_bool_true(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = self._make_request(
            spec_artifact=valid_spec,
            plan_artifact=valid_plan,
            metadata={"attempt": True},
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("metadata.attempt", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_bad_attempt_string(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = self._make_request(
            spec_artifact=valid_spec,
            plan_artifact=valid_plan,
            metadata={"attempt": "1"},
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("metadata.attempt", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_wrong_agent_id(self):
        agent, gateway = self._make_agent([])
        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        req = self._make_request(
            spec_artifact=valid_spec, plan_artifact=valid_plan, agent_id="other-agent"
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("agentId", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_plan_traceability_mismatch_spec_artifact_id(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            spec_artifact=self._make_spec_artifact(artifact_id="spec-A", version="1"),
            plan_artifact=Artifact(
                id="plan-1",
                type="PLAN",
                name="PLAN.md",
                version="1",
                content={"text": "plan text"},
                created_by="agent-plan",
                created_at=T_AWARE,
                metadata={
                    "template": "plan",
                    "specArtifactId": "spec-B",
                    "specVersion": "1",
                },
            ),
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_validate_plan_traceability_mismatch_spec_version(self):
        agent, gateway = self._make_agent([])
        req = self._make_request(
            spec_artifact=self._make_spec_artifact(artifact_id="spec-1", version="1"),
            plan_artifact=Artifact(
                id="plan-1",
                type="PLAN",
                name="PLAN.md",
                version="1",
                content={"text": "plan text"},
                created_by="agent-plan",
                created_at=T_AWARE,
                metadata={
                    "template": "plan",
                    "specArtifactId": "spec-1",
                    "specVersion": "99",
                },
            ),
        )
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts", paths)
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    def test_gateway_failure_timeout(self):
        gw_err = ModelGatewayError("LLM_TIMEOUT", "Failed with LLM_TIMEOUT")
        agent, gateway = self._make_agent([gw_err])
        req = self._make_request()
        res = agent.execute(req)
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.artifacts, [])
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(res.errors[0].code, "LLM_TIMEOUT")
        self.assertTrue(res.errors[0].retryable)
        event_types = [e.event_type for e in res.events]
        self.assertEqual(event_types, ["AGENT_STARTED", "AGENT_FAILED"])

    def test_gateway_failure_rate_limited(self):
        gw_err = ModelGatewayError("LLM_RATE_LIMITED", "Failed with LLM_RATE_LIMITED")
        agent, gateway = self._make_agent([gw_err])
        req = self._make_request()
        res = agent.execute(req)
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.artifacts, [])
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(res.errors[0].code, "LLM_RATE_LIMITED")
        self.assertTrue(res.errors[0].retryable)
        event_types = [e.event_type for e in res.events]
        self.assertEqual(event_types, ["AGENT_STARTED", "AGENT_FAILED"])

    def test_gateway_failure_invalid_response(self):
        gw_err = ModelGatewayError("LLM_INVALID_RESPONSE", "Failed with LLM_INVALID_RESPONSE")
        agent, gateway = self._make_agent([gw_err])
        req = self._make_request()
        res = agent.execute(req)
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.artifacts, [])
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertTrue(res.errors[0].retryable)
        event_types = [e.event_type for e in res.events]
        self.assertEqual(event_types, ["AGENT_STARTED", "AGENT_FAILED"])

    def test_gateway_failure_integration_unavailable(self):
        gw_err = ModelGatewayError("INTEGRATION_UNAVAILABLE", "Failed with INTEGRATION_UNAVAILABLE")
        agent, gateway = self._make_agent([gw_err])
        req = self._make_request()
        res = agent.execute(req)
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.artifacts, [])
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(res.errors[0].code, "INTEGRATION_UNAVAILABLE")
        self.assertTrue(res.errors[0].retryable)
        event_types = [e.event_type for e in res.events]
        self.assertEqual(event_types, ["AGENT_STARTED", "AGENT_FAILED"])

    def test_reply_empty_returns_llm_invalid_response(self):
        agent_empty, _ = self._make_agent(["   \n  "])
        res_empty = agent_empty.execute(self._make_request())
        self.assertEqual(res_empty.status, "FAILED")
        self.assertEqual(res_empty.errors[0].code, "LLM_INVALID_RESPONSE")

    def test_reply_invalid_json_returns_parse_error(self):
        agent_invalid_json, _ = self._make_agent(["{not valid json}"])
        res_invalid = agent_invalid_json.execute(self._make_request())
        self.assertEqual(res_invalid.status, "FAILED")
        self.assertEqual(res_invalid.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res_invalid.errors[0].details)

    def test_reply_missing_tasks_key_returns_parse_error(self):
        agent_missing_tasks, _ = self._make_agent(['{"not_tasks": []}'])
        res_missing = agent_missing_tasks.execute(self._make_request())
        self.assertEqual(res_missing.status, "FAILED")
        self.assertEqual(res_missing.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res_missing.errors[0].details)
        self.assertTrue(
            any("tasks" in str(res_missing.errors[0].details["parseError"]) for _ in [0])
        )

    def test_reply_tasks_not_a_list_returns_parse_error(self):
        agent_not_list, _ = self._make_agent(['{"tasks": "not a list"}'])
        res_not_list = agent_not_list.execute(self._make_request())
        self.assertEqual(res_not_list.status, "FAILED")
        self.assertEqual(res_not_list.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res_not_list.errors[0].details)
        self.assertTrue(
            any("tasks" in str(res_not_list.errors[0].details["parseError"]) for _ in [0])
        )

    def test_reply_wrapped_in_code_fence_unwrapped_and_accepted(self):
        wrapped_reply = f"```json\n{self.valid_reply}\n```"
        agent_wrapped, _ = self._make_agent([wrapped_reply])
        res_wrapped = agent_wrapped.execute(self._make_request())
        self.assertEqual(res_wrapped.status, "SUCCESS")

    def test_reply_invalid_task_id_format_returns_parse_error(self):
        bad_id_reply = make_valid_task_reply(task_count=1, milestones=[("M1", "Setup")])
        # Corrupt the task ID
        bad_id_reply = bad_id_reply.replace('"id": "T1"', '"id": "X1"')
        agent_bad_id, _ = self._make_agent([bad_id_reply])
        res_bad_id = agent_bad_id.execute(self._make_request())
        self.assertEqual(res_bad_id.status, "FAILED")
        self.assertEqual(res_bad_id.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res_bad_id.errors[0].details)
        self.assertTrue(
            any("Task ID" in str(res_bad_id.errors[0].details["parseError"]) for _ in [0])
        )

    # === Batch 2: Strict parsing tests ===

    def test_strict_duplicate_acceptance_criteria(self):
        """Duplicate entries in acceptanceCriteria should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].acceptanceCriteria[1]": "Criterion 1.1"})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_duplicate_depends_on(self):
        """Duplicate entries in dependsOn should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][1]["dependsOn"] = ["T1", "T1"]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_duplicate_expected_files(self):
        """Duplicate entries in expectedFiles should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["expectedFiles"] = ["src/M1/task1.py", "src/M1/task1.py"]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_empty_string_id(self):
        """Empty string in id field should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].id": ""})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_whitespace_string_id(self):
        """Whitespace-only string in id field should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].id": "   "})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_empty_string_title(self):
        """Empty string in title field should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].title": ""})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_whitespace_string_title(self):
        """Whitespace-only string in title field should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].title": "   "})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_empty_string_milestone_ref(self):
        """Empty string in milestoneRef field should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].milestoneRef": ""})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_whitespace_string_milestone_ref(self):
        """Whitespace-only string in milestoneRef field should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].milestoneRef": "   "})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_empty_string_description(self):
        """Empty string in description field should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].description": ""})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_whitespace_string_description(self):
        """Whitespace-only string in description field should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].description": "   "})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_empty_string_verification_hint(self):
        """Empty string in verificationHint field should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].verificationHint": ""})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_whitespace_string_verification_hint(self):
        """Whitespace-only string in verificationHint field should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].verificationHint": "   "})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_empty_string_in_acceptance_criteria(self):
        """Empty string in acceptanceCriteria list should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].acceptanceCriteria[0]": ""})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_whitespace_string_in_acceptance_criteria(self):
        """Whitespace-only string in acceptanceCriteria list should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].acceptanceCriteria[0]": "   "})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_empty_string_in_depends_on(self):
        """Empty string in dependsOn list should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][1]["dependsOn"] = [""]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_whitespace_string_in_depends_on(self):
        """Whitespace-only string in dependsOn list should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][1]["dependsOn"] = ["   "]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_empty_string_in_expected_files(self):
        """Empty string in expectedFiles list should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].expectedFiles[0]": ""})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_whitespace_string_in_expected_files(self):
        """Whitespace-only string in expectedFiles list should be rejected."""
        bad_reply = self._make_bad_reply({"tasks[0].expectedFiles[0]": "   "})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_wrong_type_id_number(self):
        """Number type for id field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["id"] = 123
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_wrong_type_id_bool(self):
        """Boolean type for id field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["id"] = True
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_wrong_type_id_null(self):
        """Null type for id field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["id"] = None
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_wrong_type_title_number(self):
        """Number type for title field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["title"] = 123
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_wrong_type_milestone_ref_number(self):
        """Number type for milestoneRef field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["milestoneRef"] = 123
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_wrong_type_description_number(self):
        """Number type for description field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["description"] = 123
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_wrong_type_verification_hint_number(self):
        """Number type for verificationHint field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["verificationHint"] = 123
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_wrong_type_acceptance_criteria_not_list(self):
        """Non-list type for acceptanceCriteria should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["acceptanceCriteria"] = "not a list"
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_wrong_type_depends_on_not_list(self):
        """Non-list type for dependsOn should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["dependsOn"] = "not a list"
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_wrong_type_expected_files_not_list(self):
        """Non-list type for expectedFiles should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["expectedFiles"] = "not a list"
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_extra_field_in_task(self):
        """Extra field in task object should be rejected (extra='forbid')."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["tasks"][0]["extraField"] = "not allowed"
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_missing_id_field(self):
        """Missing id field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        del data["tasks"][0]["id"]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_missing_title_field(self):
        """Missing title field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        del data["tasks"][0]["title"]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_missing_milestone_ref_field(self):
        """Missing milestoneRef field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        del data["tasks"][0]["milestoneRef"]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_missing_description_field(self):
        """Missing description field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        del data["tasks"][0]["description"]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_missing_acceptance_criteria_field(self):
        """Missing acceptanceCriteria field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        del data["tasks"][0]["acceptanceCriteria"]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_missing_depends_on_field(self):
        """Missing dependsOn field should be accepted (has default_factory=list)."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        del data["tasks"][0]["dependsOn"]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "SUCCESS")

    def test_strict_missing_expected_files_field(self):
        """Missing expectedFiles field should be accepted (has default_factory=list)."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        del data["tasks"][0]["expectedFiles"]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "SUCCESS")

    def test_strict_missing_verification_hint_field(self):
        """Missing verificationHint field should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        del data["tasks"][0]["verificationHint"]
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_envelope_top_level_list(self):
        """Top-level array instead of object should be rejected."""
        agent, _ = self._make_agent(["[]"])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_envelope_tasks_not_a_list(self):
        """'tasks' as non-list should be rejected."""
        agent, _ = self._make_agent(['{"tasks": "not a list"}'])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_strict_envelope_extra_top_level_key(self):
        """Extra top-level key should be rejected."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        data["extraKey"] = "not allowed"
        bad_reply = json_lib.dumps(data, indent=2)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)

    def test_unexpected_gateway_exception_redacted(self):
        agent, _ = self._make_agent([RuntimeError("DATABASE_PASSWORD_SECRET_987")])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "AGENT_EXECUTION_FAILED")
        self.assertEqual(res.errors[0].details, {"exceptionType": "RuntimeError"})
        dumped = json.dumps(res.to_contract())
        self.assertNotIn("DATABASE_PASSWORD_SECRET_987", dumped)

    def test_project_context_whitelisting(self):
        agent, gateway = self._make_agent([self.valid_reply])
        req = self._make_request(
            project_context={
                "name": "PublicProject",
                "description": "Public description",
                "technology": ["python"],
                "api_secret": "TOP_SECRET_API_KEY",
                "internal_token": "SHOULD_NOT_LEAK",
            }
        )
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        user_content = gateway.requests[0].messages[1].content
        self.assertIn("PublicProject", user_content)
        self.assertIn("Public description", user_content)
        self.assertNotIn("TOP_SECRET_API_KEY", user_content)
        self.assertNotIn("SHOULD_NOT_LEAK", user_content)

    def test_determinism_and_immutability(self):
        script = [self.valid_reply]
        agent1, _ = self._make_agent(list(script))
        agent2, _ = self._make_agent(list(script))

        req = self._make_request()
        req_copy = copy.deepcopy(req)

        res1 = agent1.execute(req)
        res2 = agent2.execute(req)

        self.assertEqual(req, req_copy)
        self.assertEqual(res1.to_contract(), res2.to_contract())

    def test_task_id_sequential_validation(self):
        """Test that non-sequential task IDs are rejected."""
        # Task IDs must be T1, T2, T3...
        bad_reply = make_valid_task_reply(task_count=3, milestones=[("M1", "Setup")])
        bad_reply = bad_reply.replace('"id": "T2"', '"id": "T4"')  # Skip T2, T3
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(any("sequential" in issue for issue in res.errors[0].details["taskIssues"]))

    def test_task_id_duplicate_rejected(self):
        """Test that duplicate task IDs are rejected."""
        bad_reply = make_valid_task_reply(task_count=2, milestones=[("M1", "Setup")])
        bad_reply = bad_reply.replace('"id": "T2"', '"id": "T1"')  # Duplicate T1
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("Duplicate task ID" in issue for issue in res.errors[0].details["taskIssues"])
        )

    def test_milestone_ref_exists_in_plan(self):
        """Test that milestoneRef must exist in PLAN."""
        bad_reply = make_valid_task_reply(task_count=1, milestones=[("M1", "Setup")])
        bad_reply = bad_reply.replace('"milestoneRef": "M1"', '"milestoneRef": "M99"')
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("not found in PLAN" in issue for issue in res.errors[0].details["taskIssues"])
        )

    def test_milestone_ref_non_decreasing(self):
        """Test that milestoneRef must be non-decreasing in task order."""
        # T1 in M2, T2 in M1 -> decreasing
        bad_reply = make_valid_task_reply(
            task_count=2, milestones=[("M2", "Core"), ("M1", "Setup")]
        )
        # The reply has T1 in M2 and T2 in M1 (decreasing)
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("non-decreasing" in issue for issue in res.errors[0].details["taskIssues"])
        )

    def test_depends_on_only_lower_numbered_tasks(self):
        """Test that dependsOn only references lower-numbered tasks."""
        # T1 depends on T2 (later task)
        bad_reply = make_valid_task_reply(task_count=2, milestones=[("M1", "Setup")])
        bad_reply = bad_reply.replace('"dependsOn": []', '"dependsOn": ["T2"]', 1)  # First task
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "depends on later or non-existent task" in issue
                for issue in res.errors[0].details["taskIssues"]
            )
        )

    def test_depends_on_no_self_dependency(self):
        """Test that self-dependency is rejected."""
        bad_reply = make_valid_task_reply(task_count=1, milestones=[("M1", "Setup")])
        bad_reply = bad_reply.replace('"dependsOn": []', '"dependsOn": ["T1"]')
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "self-dependency is not allowed" in issue
                for issue in res.errors[0].details["taskIssues"]
            )
        )

    def test_cross_milestone_dependency_ancestor_rule(self):
        """Test cross-milestone dependency only allowed to ancestor milestones."""
        # Create a plan with M1 -> M2 -> M3 (linear)
        plan_text = (
            "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n"
            "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
            "### M2: Core\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M1\n"
            "### M3: Integration\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M2"
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        # Task in M3 depending on task in M1 (valid - M1 is ancestor of M3)
        reply_valid = make_valid_task_reply(
            task_count=3,
            milestones=[("M1", "Setup"), ("M2", "Core"), ("M3", "Integration")],
        )
        # Modify: T3 (in M3) depends on T1 (in M1) - should be valid since M1 is ancestor of M3
        import json as json_lib

        data = json_lib.loads(reply_valid)
        data["tasks"][2]["dependsOn"] = ["T1"]
        reply_valid = json_lib.dumps(data, indent=2)

        agent, _ = self._make_agent([reply_valid])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "SUCCESS")

        # Task in M2 depending on task in M3 (invalid - M3 is not ancestor of M2)
        reply_invalid = make_valid_task_reply(
            task_count=3,
            milestones=[("M1", "Setup"), ("M2", "Core"), ("M3", "Integration")],
        )
        data = json_lib.loads(reply_invalid)
        data["tasks"][1]["dependsOn"] = ["T3"]  # T2 depends on T3 (M2 depends on M3)
        reply_invalid = json_lib.dumps(data, indent=2)

        agent2, _ = self._make_agent([reply_invalid])
        res2 = agent2.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res2.status, "FAILED")
        self.assertEqual(res2.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res2.errors[0].details)
        self.assertTrue(
            any("not an ancestor" in issue for issue in res2.errors[0].details["taskIssues"])
        )

    # === Batch 3: Ordering and dependencies tests ===

    def test_task_ordering_numeric_not_lexical_t10_after_t9(self):
        """Task IDs must be ordered numerically (T10 after T9), not lexically."""
        # Create a plan with many milestones
        plan_text = "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n" + "\n".join(
            [
                (
                    f"### M{i}: Milestone {i}\n- Deliverables: X\n"
                    f"- Acceptance criteria: Y\n- Depends on: {f'M{i - 1}' if i > 1 else 'none'}"
                )
                for i in range(1, 13)
            ]
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        # Create 12 tasks, one per milestone
        reply = make_valid_task_reply(
            task_count=12,
            milestones=[(f"M{i}", f"Milestone {i}") for i in range(1, 13)],
        )

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "SUCCESS")

        # Verify task IDs are T1 through T12 (numeric order)
        art = res.artifacts[0]
        tasks = art.content["tasks"]
        for i, task in enumerate(tasks, 1):
            self.assertEqual(task["id"], f"T{i}")

    def test_milestone_ordering_numeric_not_lexical_m10_after_m9(self):
        """Milestone refs must be ordered numerically (M10 after M9), not lexically."""
        # Same plan with 12 milestones
        plan_text = "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n" + "\n".join(
            [
                (
                    f"### M{i}: Milestone {i}\n- Deliverables: X\n"
                    f"- Acceptance criteria: Y\n- Depends on: {f'M{i - 1}' if i > 1 else 'none'}"
                )
                for i in range(1, 13)
            ]
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        # Create 12 tasks, one per milestone, ensuring milestoneRef order is numeric
        reply = make_valid_task_reply(
            task_count=12,
            milestones=[(f"M{i}", f"Milestone {i}") for i in range(1, 13)],
        )

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "SUCCESS")

        # Verify milestoneRefs are in numeric order
        art = res.artifacts[0]
        tasks = art.content["tasks"]
        prev_m_num = 0
        for task in tasks:
            m_num = int(task["milestoneRef"][1:])  # Extract number from "M1", "M2", etc.
            msg = "MilestoneRef must be non-decreasing numerically"
            self.assertGreaterEqual(m_num, prev_m_num, msg)
            prev_m_num = m_num

    def test_forbidden_dependency_unrelated_milestones(self):
        """Cross-milestone dependency forbidden when milestones are unrelated
        (no ancestor relationship)."""
        # Plan with M1 and M2 as independent (no dependency between them)
        plan_text = (
            "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n"
            "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
            "### M2: Core\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
            "### M3: Integration\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M1, M2"
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        # Task in M2 depending on task in M1 - INVALID since M1 is not ancestor
        # of M2 (they're independent)
        import json as json_lib

        reply_invalid = json_lib.dumps(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Task 1: Setup",
                        "milestoneRef": "M1",
                        "description": "Setup task",
                        "acceptanceCriteria": ["AC1"],
                        "dependsOn": [],
                        "expectedFiles": ["src/m1/task1.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T2",
                        "title": "Task 2: Core",
                        "milestoneRef": "M2",
                        "description": "Core task",
                        "acceptanceCriteria": ["AC2"],
                        "dependsOn": ["T1"],  # T2 (in M2) depends on T1 (in M1) - INVALID
                        "expectedFiles": ["src/m2/task2.py"],
                        "verificationHint": "Run tests for M2",
                    },
                ]
            },
            indent=2,
        )

        agent, _ = self._make_agent([reply_invalid])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("not an ancestor" in issue for issue in res.errors[0].details["taskIssues"])
        )

        # Valid: Task in M3 depending on task in M1 - M1 is ancestor of M3
        reply_valid = json_lib.dumps(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Task 1: Setup",
                        "milestoneRef": "M1",
                        "description": "Setup task",
                        "acceptanceCriteria": ["AC1"],
                        "dependsOn": [],
                        "expectedFiles": ["src/m1/task1.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T2",
                        "title": "Task 2: Core",
                        "milestoneRef": "M2",
                        "description": "Core task",
                        "acceptanceCriteria": ["AC2"],
                        "dependsOn": [],
                        "expectedFiles": ["src/m2/task2.py"],
                        "verificationHint": "Run tests for M2",
                    },
                    {
                        "id": "T3",
                        "title": "Task 3: Integration",
                        "milestoneRef": "M3",
                        "description": "Integration task",
                        "acceptanceCriteria": ["AC3"],
                        "dependsOn": ["T1"],  # T3 (in M3) depends on T1 (in M1) - VALID
                        "expectedFiles": ["src/m3/task3.py"],
                        "verificationHint": "Run tests for M3",
                    },
                ]
            },
            indent=2,
        )

        agent2, _ = self._make_agent([reply_valid])
        res2 = agent2.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res2.status, "SUCCESS")

    def test_transitive_dependency_m3_m2_m1(self):
        """Transitive dependency allowed: M3 -> M2 -> M1 (M1 ancestor of M2, M2 ancestor of M3)."""
        # Plan with linear chain M1 -> M2 -> M3
        plan_text = (
            "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n"
            "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
            "### M2: Core\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M1\n"
            "### M3: Integration\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M2"
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        # T3 in M3 depends on T2 in M2 (valid - direct ancestor)
        # T2 in M2 depends on T1 in M1 (valid - direct ancestor)
        reply = make_valid_task_reply(
            task_count=3,
            milestones=[("M1", "Setup"), ("M2", "Core"), ("M3", "Integration")],
        )
        import json as json_lib

        data = json_lib.loads(reply)
        data["tasks"][1]["dependsOn"] = ["T1"]
        data["tasks"][2]["dependsOn"] = ["T2"]
        reply = json_lib.dumps(data, indent=2)

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "SUCCESS")

        # Also valid: T3 in M3 depends on T1 in M1 (transitive ancestor)
        reply2 = make_valid_task_reply(
            task_count=3,
            milestones=[("M1", "Setup"), ("M2", "Core"), ("M3", "Integration")],
        )
        data = json_lib.loads(reply2)
        data["tasks"][2]["dependsOn"] = ["T1"]
        reply2 = json_lib.dumps(data, indent=2)

        agent2, _ = self._make_agent([reply2])
        res2 = agent2.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res2.status, "SUCCESS")

    def test_cross_milestone_dependency_direct_ancestor_allowed(self):
        """Cross-milestone dependency allowed when dependency milestone is direct ancestor."""
        # Plan with M1 -> M2 -> M3
        plan_text = (
            "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n"
            "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
            "### M2: Core\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M1\n"
            "### M3: Integration\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M2"
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        # Task in M2 depending on task in M1 (same or ancestor milestone) - VALID
        # Need tasks for all 3 milestones (M1, M2, M3)
        import json as json_lib

        reply = json_lib.dumps(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Task 1: Setup",
                        "milestoneRef": "M1",
                        "description": "Setup task",
                        "acceptanceCriteria": ["AC1"],
                        "dependsOn": [],
                        "expectedFiles": ["src/m1/task1.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T2",
                        "title": "Task 2: Core",
                        "milestoneRef": "M2",
                        "description": "Core task",
                        "acceptanceCriteria": ["AC2"],
                        # T2 (in M2) depends on T1 (in M1) - VALID (M1 is ancestor of M2)
                        "dependsOn": ["T1"],
                        "expectedFiles": ["src/m2/task2.py"],
                        "verificationHint": "Run tests for M2",
                    },
                    {
                        "id": "T3",
                        "title": "Task 3: Integration",
                        "milestoneRef": "M3",
                        "description": "Integration task",
                        "acceptanceCriteria": ["AC3"],
                        "dependsOn": ["T2"],
                        "expectedFiles": ["src/m3/task3.py"],
                        "verificationHint": "Run tests for M3",
                    },
                ]
            },
            indent=2,
        )

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "SUCCESS")

    def test_cross_milestone_dependency_transitive_ancestor_allowed(self):
        """Transitive ancestor: M3 -> M2 -> M1, task in M3 depends on task in M1 (allowed)."""
        # Plan with M1 -> M2 -> M3
        plan_text = (
            "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n"
            "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
            "### M2: Core\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M1\n"
            "### M3: Integration\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M2"
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        import json as json_lib

        reply = json_lib.dumps(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Task 1: Setup",
                        "milestoneRef": "M1",
                        "description": "Setup task",
                        "acceptanceCriteria": ["AC1"],
                        "dependsOn": [],
                        "expectedFiles": ["src/m1/task1.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T2",
                        "title": "Task 2: Core",
                        "milestoneRef": "M2",
                        "description": "Core task",
                        "acceptanceCriteria": ["AC2"],
                        "dependsOn": ["T1"],
                        "expectedFiles": ["src/m2/task2.py"],
                        "verificationHint": "Run tests for M2",
                    },
                    {
                        "id": "T3",
                        "title": "Task 3: Integration",
                        "milestoneRef": "M3",
                        "description": "Integration task",
                        "acceptanceCriteria": ["AC3"],
                        "dependsOn": ["T1"],  # T3 in M3 depends on T1 in M1 (transitive ancestor)
                        "expectedFiles": ["src/m3/task3.py"],
                        "verificationHint": "Run tests for M3",
                    },
                ]
            },
            indent=2,
        )

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "SUCCESS")

    def test_cross_milestone_dependency_unrelated_rejected(self):
        """Cross-milestone dependency rejected when milestones are unrelated."""
        # Plan with M1 and M2 as independent (no dependency between them)
        plan_text = (
            "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
            "### M2: Core\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none"
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        import json as json_lib

        reply = json_lib.dumps(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Task 1: Setup",
                        "milestoneRef": "M1",
                        "description": "Setup task",
                        "acceptanceCriteria": ["AC1"],
                        "dependsOn": [],
                        "expectedFiles": ["src/m1/task1.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T2",
                        "title": "Task 2: Core",
                        "milestoneRef": "M2",
                        "description": "Core task",
                        "acceptanceCriteria": ["AC2"],
                        "dependsOn": ["T1"],  # T2 in M2 depends on T1 in M1 - INVALID (unrelated)
                        "expectedFiles": ["src/m2/task2.py"],
                        "verificationHint": "Run tests for M2",
                    },
                ]
            },
            indent=2,
        )

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)

    def test_cross_milestone_dependency_later_milestone_rejected(self):
        """Cross-milestone dependency rejected when depending on later milestone."""
        # Plan with M1 -> M2
        plan_text = (
            "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
            "### M2: Core\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M1"
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        import json as json_lib

        reply = json_lib.dumps(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Task 1: Setup",
                        "milestoneRef": "M1",
                        "description": "Setup task",
                        "acceptanceCriteria": ["AC1"],
                        "dependsOn": [],
                        "expectedFiles": ["src/m1/task1.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T2",
                        "title": "Task 2: Core",
                        "milestoneRef": "M2",
                        "description": "Core task",
                        "acceptanceCriteria": ["AC2"],
                        "dependsOn": ["T1"],  # Valid - M1 is ancestor of M2
                        "expectedFiles": ["src/m2/task2.py"],
                        "verificationHint": "Run tests for M2",
                    },
                    {
                        "id": "T3",
                        "title": "Task 3: Integration",
                        "milestoneRef": "M1",  # Back to M1
                        "description": "Integration task",
                        "acceptanceCriteria": ["AC3"],
                        "dependsOn": ["T2"],  # T3 in M1 depends on T2 in M2 - INVALID (M2 is later)
                        "expectedFiles": ["src/m1/task3.py"],
                        "verificationHint": "Run tests for M1",
                    },
                ]
            },
            indent=2,
        )

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)

    def test_depends_on_later_task_same_milestone_rejected(self):
        """Dependency on later task number in same milestone rejected."""
        # Plan with M1
        plan_text = "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none"
        plan_art = self._make_plan_artifact(text=plan_text)

        import json as json_lib

        reply = json_lib.dumps(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Task 1",
                        "milestoneRef": "M1",
                        "description": "Task 1",
                        "acceptanceCriteria": ["AC1"],
                        "dependsOn": [],
                        "expectedFiles": ["src/m1/task1.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T2",
                        "title": "Task 2",
                        "milestoneRef": "M1",
                        "description": "Task 2",
                        "acceptanceCriteria": ["AC2"],
                        "dependsOn": ["T1"],
                        "expectedFiles": ["src/m1/task2.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T3",
                        "title": "Task 3",
                        "milestoneRef": "M1",
                        "description": "Task 3",
                        "acceptanceCriteria": ["AC3"],
                        "dependsOn": ["T2"],  # Valid - T2 is earlier
                        "expectedFiles": ["src/m1/task3.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T4",
                        "title": "Task 4",
                        "milestoneRef": "M1",
                        "description": "Task 4",
                        "acceptanceCriteria": ["AC4"],
                        "dependsOn": ["T3"],  # Valid - T3 is earlier
                        "expectedFiles": ["src/m1/task4.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T5",
                        "title": "Task 5",
                        "milestoneRef": "M1",
                        "description": "Task 5",
                        "acceptanceCriteria": ["AC5"],
                        "dependsOn": ["T4"],  # Valid - T4 is earlier
                        "expectedFiles": ["src/m1/task5.py"],
                        "verificationHint": "Run tests for M1",
                    },
                    {
                        "id": "T6",
                        "title": "Task 6",
                        "milestoneRef": "M1",
                        "description": "Task 6",
                        "acceptanceCriteria": ["AC6"],
                        "dependsOn": ["T5"],  # Valid - T5 is earlier
                        "expectedFiles": ["src/m1/task6.py"],
                        "verificationHint": "Run tests for M1",
                    },
                ]
            },
            indent=2,
        )

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "SUCCESS")

    def test_every_milestone_has_task_12_milestones(self):
        """Every PLAN milestone must have at least one task - test with 12 milestones."""
        # Plan with 12 milestones
        plan_text = "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n" + "\n".join(
            [
                (
                    f"### M{i}: Milestone {i}\n- Deliverables: X\n"
                    f"- Acceptance criteria: Y\n- Depends on: {f'M{i - 1}' if i > 1 else 'none'}"
                )
                for i in range(1, 13)
            ]
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        # Only 11 tasks, missing one milestone
        reply = make_valid_task_reply(
            task_count=11,
            milestones=[(f"M{i}", f"Milestone {i}") for i in range(1, 12)],  # Missing M12
        )

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("has no tasks assigned" in issue for issue in res.errors[0].details["taskIssues"])
        )

    def test_every_milestone_has_task_all_12_covered(self):
        """All 12 milestones covered by at least one task - should succeed."""
        plan_text = "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n" + "\n".join(
            [
                (
                    f"### M{i}: Milestone {i}\n- Deliverables: X\n"
                    f"- Acceptance criteria: Y\n- Depends on: {f'M{i - 1}' if i > 1 else 'none'}"
                )
                for i in range(1, 13)
            ]
        )
        plan_art = self._make_plan_artifact(text=plan_text)

        # 12 tasks, one per milestone
        reply = make_valid_task_reply(
            task_count=12,
            milestones=[(f"M{i}", f"Milestone {i}") for i in range(1, 13)],
        )

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request(plan_artifact=plan_art))
        self.assertEqual(res.status, "SUCCESS")

    def test_every_plan_milestone_has_at_least_one_task(self):
        """Test that every PLAN milestone must have at least one task assigned."""
        # Plan has M1, M2 but tasks only reference M1
        bad_reply = make_valid_task_reply(
            task_count=2, milestones=[("M1", "Setup"), ("M1", "Setup")]
        )
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("has no tasks assigned" in issue for issue in res.errors[0].details["taskIssues"])
        )

    def test_max_tasks_limit(self):
        """Test that exceeding MAX_TASKS is rejected."""
        # Create a reply with MAX_TASKS + 1 tasks
        bad_reply = make_valid_task_reply(task_count=MAX_TASKS + 1, milestones=[("M1", "Setup")])
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("Too many tasks" in issue for issue in res.errors[0].details["taskIssues"])
        )

    def test_output_size_limit_max_task_text_chars(self):
        """Test that rendered output exceeding MAX_TASK_TEXT_CHARS is rejected."""
        # Create a reply with many tasks with large unique content to exceed MAX_TASK_TEXT_CHARS
        tasks = []
        for i in range(1, 80):  # Enough tasks with large content
            tasks.append(
                {
                    "id": f"T{i}",
                    "title": f"Task {i}",
                    "milestoneRef": "M1",
                    "description": "x" * 3000,  # Each task ~3KB description
                    "acceptanceCriteria": [
                        f"AC{i}.1",
                        f"AC{i}.2",
                        f"AC{i}.3",
                        f"AC{i}.4",
                        f"AC{i}.5",
                    ],  # Unique per task
                    "dependsOn": [f"T{i - 1}"] if i > 1 else [],
                    "expectedFiles": [f"src/task{i}.py"],
                    "verificationHint": "z" * 2000,
                }
            )
        bad_reply = json.dumps({"tasks": tasks}, indent=2)

        # Use a PLAN with only M1 to avoid "milestone has no tasks" error
        spec_art = self._make_spec_artifact()
        plan_art = self._make_plan_artifact(
            text=(
                "# PLAN: Test Plan\n## Linked SPEC\nID: spec-123\nVersion: 1\n## Milestones\n"
                "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none"
            )
        )
        req = self._make_request(spec_artifact=spec_art, plan_artifact=plan_art)

        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(req)
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("exceeds", res.errors[0].message.lower())

    def _make_bad_reply(self, modifications: dict) -> str:
        """Create a bad reply by modifying the valid reply JSON."""
        import json as json_lib

        data = json_lib.loads(self.valid_reply)
        for path, value in modifications.items():
            # path is like "tasks[0].expectedFiles" or "tasks[0].acceptanceCriteria[0]"
            parts = path.split(".")
            obj = data
            for part in parts[:-1]:
                if "[" in part:
                    key, idx = part.split("[")
                    idx = int(idx.rstrip("]"))
                    obj = obj[key][idx]
                else:
                    obj = obj[part]
            last = parts[-1]
            if "[" in last:
                key, idx = last.split("[")
                idx = int(idx.rstrip("]"))
                obj[key][idx] = value
            else:
                obj[last] = value
        return json_lib.dumps(data, indent=2)

    def test_expected_files_validation_relative_only(self):
        """Test that expectedFiles must be relative paths."""
        bad_reply = self._make_bad_reply({"tasks[0].expectedFiles": ["/absolute/path.py"]})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("must be relative" in issue for issue in res.errors[0].details["taskIssues"])
        )

    def test_expected_files_no_drive_letter(self):
        """Test that expectedFiles must not contain drive letters."""
        bad_reply = self._make_bad_reply(
            {"tasks[0].expectedFiles": ["C:\\\\path\\\\to\\\\file.py"]}
        )
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("must be relative" in issue for issue in res.errors[0].details["taskIssues"])
        )

    def test_expected_files_no_backslashes(self):
        """Test that expectedFiles must not contain backslashes."""
        bad_reply = self._make_bad_reply({"tasks[0].expectedFiles": ["src\\\\M1\\\\task1.py"]})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "must not contain backslashes" in issue
                for issue in res.errors[0].details["taskIssues"]
            )
        )

    def test_expected_files_no_dotdot_segments(self):
        """Test that expectedFiles must not contain '..' segments."""
        bad_reply = self._make_bad_reply({"tasks[0].expectedFiles": ["src/../other.py"]})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "must not contain '..' segments" in issue
                for issue in res.errors[0].details["taskIssues"]
            )
        )

    def test_expected_files_no_empty_segments(self):
        """Test that expectedFiles must not have empty segments."""
        bad_reply = self._make_bad_reply({"tasks[0].expectedFiles": ["src//M1/task1.py"]})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("empty path segments" in issue for issue in res.errors[0].details["taskIssues"])
        )

    def test_expected_files_no_control_characters(self):
        """Test that expectedFiles must not contain control characters."""
        bad_reply = self._make_bad_reply({"tasks[0].expectedFiles": ["src/\x00M1/task1.py"]})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        self.assertTrue(
            any("control characters" in issue for issue in res.errors[0].details["taskIssues"])
        )

    def test_acceptance_criteria_non_empty_strings(self):
        """Test that acceptanceCriteria must be non-empty strings."""
        bad_reply = self._make_bad_reply({"tasks[0].acceptanceCriteria[0]": ""})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)
        self.assertTrue(
            any("non-empty strings" in str(res.errors[0].details["parseError"]) for _ in [0])
        )

    def test_traceability_in_output_artifact(self):
        """Test that output artifact contains traceability to SPEC and PLAN."""
        custom_spec = self._make_spec_artifact(artifact_id="custom-spec-456", version="3")
        # Create a plan with only M1 milestone to match the custom_reply
        custom_plan = self._make_plan_artifact(
            artifact_id="custom-plan-789",
            version="2",
            text=(
                "# PLAN: Custom Plan\n## Linked SPEC\n...\n## Milestones\n"
                "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none"
            ),
        )
        custom_plan.metadata["specArtifactId"] = "custom-spec-456"
        custom_plan.metadata["specVersion"] = "3"

        custom_reply = make_valid_task_reply(
            spec_id="custom-spec-456",
            spec_version="3",
            plan_id="custom-plan-789",
            plan_version="2",
            task_count=2,
            milestones=[("M1", "Setup")],
        )

        agent, gateway = self._make_agent([custom_reply])
        req = self._make_request(spec_artifact=custom_spec, plan_artifact=custom_plan)
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")
        art = res.artifacts[0]
        self.assertEqual(art.metadata["specArtifactId"], "custom-spec-456")
        self.assertEqual(art.metadata["specVersion"], "3")
        self.assertEqual(art.metadata["planArtifactId"], "custom-plan-789")
        self.assertEqual(art.metadata["planVersion"], "2")

    # === Batch 4: Output shape tests ===

    def test_output_task_dict_camelcase_keys_only(self):
        """Test that serialized task dict uses camelCase keys only (no snake_case)."""
        custom_spec = self._make_spec_artifact(artifact_id="spec-1", version="1")
        custom_plan = self._make_plan_artifact(
            artifact_id="plan-1",
            version="1",
            text=(
                "# PLAN: Custom Plan\n## Linked SPEC\n...\n## Milestones\n"
                "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none"
            ),
        )
        custom_plan.metadata["specArtifactId"] = "spec-1"
        custom_plan.metadata["specVersion"] = "1"

        reply = make_valid_task_reply(
            spec_id="spec-1",
            spec_version="1",
            plan_id="plan-1",
            plan_version="1",
            task_count=1,
            milestones=[("M1", "Setup")],
        )

        agent, _ = self._make_agent([reply])
        req = self._make_request(spec_artifact=custom_spec, plan_artifact=custom_plan)
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        art = res.artifacts[0]
        tasks = art.content["tasks"]
        self.assertEqual(len(tasks), 1)
        task = tasks[0]

        # Check all keys are camelCase (no snake_case)
        expected_keys = {
            "id",
            "title",
            "milestoneRef",
            "description",
            "acceptanceCriteria",
            "dependsOn",
            "expectedFiles",
            "verificationHint",
        }
        self.assertEqual(set(task.keys()), expected_keys)
        # Ensure no snake_case keys
        for key in task:
            self.assertNotIn("_", key, f"Key '{key}' should not contain underscore (snake_case)")

    def test_output_metadata_language_stored(self):
        """Test that metadata.language is stored in output artifact."""
        custom_spec = self._make_spec_artifact(artifact_id="spec-1", version="1")
        custom_plan = self._make_plan_artifact(
            artifact_id="plan-1",
            version="1",
            text=(
                "# PLAN: Custom Plan\n## Linked SPEC\n...\n## Milestones\n"
                "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none"
            ),
        )
        custom_plan.metadata["specArtifactId"] = "spec-1"
        custom_plan.metadata["specVersion"] = "1"

        reply = make_valid_task_reply(
            spec_id="spec-1",
            spec_version="1",
            plan_id="plan-1",
            plan_version="1",
            task_count=1,
            milestones=[("M1", "Setup")],
        )

        agent, _ = self._make_agent([reply])
        req = self._make_request(
            spec_artifact=custom_spec, plan_artifact=custom_plan, language="fr"
        )
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        art = res.artifacts[0]
        self.assertEqual(art.metadata["language"], "fr")

    def test_output_metadata_traceability_from_request_plan(self):
        """Test that metadata contains specArtifactId, specVersion, planArtifactId,
        planVersion from THIS request's PLAN."""
        custom_spec = self._make_spec_artifact(artifact_id="spec-A", version="5")
        custom_plan = self._make_plan_artifact(
            artifact_id="plan-B",
            version="7",
            text=(
                "# PLAN: Custom Plan\n## Linked SPEC\n...\n## Milestones\n"
                "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none"
            ),
        )
        custom_plan.metadata["specArtifactId"] = "spec-A"
        custom_plan.metadata["specVersion"] = "5"

        reply = make_valid_task_reply(
            spec_id="spec-A",
            spec_version="5",
            plan_id="plan-B",
            plan_version="7",
            task_count=1,
            milestones=[("M1", "Setup")],
        )

        agent, _ = self._make_agent([reply])
        req = self._make_request(spec_artifact=custom_spec, plan_artifact=custom_plan)
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        art = res.artifacts[0]
        # These should come from the PLAN artifact in THIS request
        self.assertEqual(art.metadata["specArtifactId"], "spec-A")
        self.assertEqual(art.metadata["specVersion"], "5")
        self.assertEqual(art.metadata["planArtifactId"], "plan-B")
        self.assertEqual(art.metadata["planVersion"], "7")

    def test_output_metadata_revision_of_in_revision_mode(self):
        """Test that revisionOf is present in metadata when in revision mode."""
        custom_spec = self._make_spec_artifact(artifact_id="spec-1", version="1")
        custom_plan = self._make_plan_artifact(
            artifact_id="plan-1",
            version="1",
            text=(
                "# PLAN: Custom Plan\n## Linked SPEC\n...\n## Milestones\n"
                "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none"
            ),
        )
        custom_plan.metadata["specArtifactId"] = "spec-1"
        custom_plan.metadata["specVersion"] = "1"

        prev_task = self._make_task_artifact(
            artifact_id="task-v1",
            version="1",
            text=(
                '{"tasks": [{"id": "T1", "title": "Old", "milestoneRef": "M1", '
                '"description": "Old", "acceptanceCriteria": ["AC1"], "dependsOn": [], '
                '"expectedFiles": [], "verificationHint": "hint"}]}'
            ),
        )

        reply = make_valid_task_reply(
            spec_id="spec-1",
            spec_version="1",
            plan_id="plan-1",
            plan_version="1",
            task_count=1,
            milestones=[("M1", "Setup")],
        )

        agent, _ = self._make_agent([reply])
        req = self._make_request(
            spec_artifact=custom_spec,
            plan_artifact=custom_plan,
            task_artifact=prev_task,
            feedback=[
                ApprovalFeedback(
                    approval_id="app-1",
                    reviewer="alice",
                    decision="REQUEST_CHANGES",
                    comment="Fix it",
                )
            ],
            metadata={"attempt": 2},
        )
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        art = res.artifacts[0]
        self.assertEqual(art.metadata["revisionOf"], "task-v1")
        self.assertEqual(art.version, "2")

    def test_size_limit_exceeded(self):
        """Test that SPEC+PLAN content exceeding MAX_TASK_CHARS is rejected."""
        large_text = "x" * (MAX_TASK_CHARS + 1)
        spec_art = Artifact(
            id="spec-large",
            type="SPEC",
            name="SPEC.md",
            version="1",
            content={"format": "markdown", "text": large_text},
            created_by="agent-spec",
            created_at=T_AWARE,
            metadata={"template": "spec"},
        )
        req = self._make_request(spec_artifact=spec_art)
        agent, _ = self._make_agent([self.valid_reply])
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts", paths)
        self.assertTrue(any("exceeds" in err.message for err in val_res.errors))

        # Execute should also be REJECTED
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")

    def test_rendered_markdown_deterministic(self):
        """Test that rendered markdown is deterministic and well-formed."""
        agent, _ = self._make_agent([self.valid_reply])
        req = self._make_request()
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        art = res.artifacts[0]
        rendered_text = art.content["text"]
        self.assertIsInstance(rendered_text, str)
        self.assertIn("# TASK: Breakdown", rendered_text)
        self.assertIn("## Linked SPEC", rendered_text)
        self.assertIn("ID: spec-123", rendered_text)
        self.assertIn("Version: 1", rendered_text)
        self.assertIn("## Milestone M1: Setup", rendered_text)
        self.assertIn("### T1:", rendered_text)
        self.assertIn("**Description:**", rendered_text)
        self.assertIn("**Acceptance Criteria:**", rendered_text)
        self.assertIn("**Verification Hint:**", rendered_text)

    def test_verification_hint_required(self):
        """Test that verificationHint is required and non-empty."""
        bad_reply = self._make_bad_reply({"tasks[0].verificationHint": ""})
        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("parseError", res.errors[0].details)
        self.assertTrue(
            any("verificationHint" in str(res.errors[0].details["parseError"]) for _ in [0])
        )

    # === Batch 5: Revision prompts tests ===

    def test_revision_mode_user_message_contains_previous_task_json(self):
        """Test that user message in revision mode contains the previous TASK JSON."""
        agent, gateway = self._make_agent([self.valid_reply])

        prev_task = self._make_task_artifact(
            artifact_id="task-v1",
            version="1",
            text=(
                '{"tasks": [{"id": "T1", "title": "Old Task", '
                '"milestoneRef": "M1", "description": "Old description", '
                '"acceptanceCriteria": ["Old AC"], "dependsOn": [], '
                '"expectedFiles": ["old.py"], "verificationHint": "old hint"}]}'
            ),
        )
        feedback = [
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="alice",
                decision="REQUEST_CHANGES",
                comment="Add more tasks",
            )
        ]

        req = self._make_request(
            task_artifact=prev_task,
            feedback=feedback,
            metadata={"attempt": 2},
        )

        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        # Check user message contains previous task
        gw_req = gateway.requests[0]
        user_msg = gw_req.messages[1].content
        self.assertIn("## Previous task (version 1)", user_msg)
        self.assertIn("Old Task", user_msg)
        self.assertIn("Old description", user_msg)
        self.assertIn("Old AC", user_msg)
        self.assertIn("old.py", user_msg)
        self.assertIn("old hint", user_msg)

    def test_revision_mode_user_message_contains_all_feedback_items(self):
        """Test that user message in revision mode contains every feedback item."""
        agent, gateway = self._make_agent([self.valid_reply])

        prev_task = self._make_task_artifact(
            artifact_id="task-v1",
            version="1",
            text=(
                '{"tasks": [{"id": "T1", "title": "Old", "milestoneRef": "M1", '
                '"description": "Old", "acceptanceCriteria": ["AC1"], "dependsOn": [], '
                '"expectedFiles": [], "verificationHint": "hint"}]}'
            ),
        )
        feedback = [
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="alice",
                decision="REQUEST_CHANGES",
                comment="Add more tasks for M2",
            ),
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="bob",
                decision="REJECTED",
                comment="Tasks too granular",
            ),
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="carol",
                decision="REQUEST_CHANGES",
                comment="Looks good but needs integration tests",
            ),
        ]

        req = self._make_request(
            task_artifact=prev_task,
            feedback=feedback,
            metadata={"attempt": 2},
        )

        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        # Check user message contains all feedback items
        gw_req = gateway.requests[0]
        user_msg = gw_req.messages[1].content
        self.assertIn("## Reviewer feedback", user_msg)
        self.assertIn("- [REQUEST_CHANGES] alice: Add more tasks for M2", user_msg)
        self.assertIn("- [REJECTED] bob: Tasks too granular", user_msg)
        self.assertIn("- [REQUEST_CHANGES] carol: Looks good but needs integration tests", user_msg)

    def test_revision_mode_system_message_contains_revision_prompt(self):
        """Test that system message in revision mode contains the revision prompt text."""
        agent, gateway = self._make_agent([self.valid_reply])

        prev_task = self._make_task_artifact(
            artifact_id="task-v1",
            version="1",
            text=(
                '{"tasks": [{"id": "T1", "title": "Old", "milestoneRef": "M1", '
                '"description": "Old", "acceptanceCriteria": ["AC1"], "dependsOn": [], '
                '"expectedFiles": [], "verificationHint": "hint"}]}'
            ),
        )
        feedback = [
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="alice",
                decision="REQUEST_CHANGES",
                comment="Add more tasks",
            )
        ]

        req = self._make_request(
            task_artifact=prev_task,
            feedback=feedback,
            metadata={"attempt": 2},
        )

        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        # Check system message contains revision prompt
        gw_req = gateway.requests[0]
        sys_msg = gw_req.messages[0].content
        # Revision prompt should be appended to system prompt
        self.assertIn("reviewer feedback", sys_msg.lower())
        self.assertIn("revising", sys_msg.lower())
        # Should contain the original system prompt too
        self.assertIn("senior software engineer", sys_msg.lower())
        self.assertIn("breaking down implementation plans", sys_msg.lower())

    def test_revision_mode_first_attempt_no_revision_sections(self):
        """Test that first attempt (no previous task) does not include revision sections."""
        agent, gateway = self._make_agent([self.valid_reply])

        req = self._make_request(metadata={"attempt": 1})
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        gw_req = gateway.requests[0]
        user_msg = gw_req.messages[1].content
        sys_msg = gw_req.messages[0].content

        # Should NOT have revision sections
        self.assertNotIn("## Previous task", user_msg)
        self.assertNotIn("## Reviewer feedback", user_msg)
        # System message should not have revision prompt
        self.assertNotIn("reviewer feedback", sys_msg.lower())
        self.assertNotIn("revise", sys_msg.lower())

    def test_revision_mode_feedback_order_preserved(self):
        """Test that feedback items appear in the same order as provided."""
        agent, gateway = self._make_agent([self.valid_reply])

        prev_task = self._make_task_artifact(
            artifact_id="task-v1",
            version="1",
            text=(
                '{"tasks": [{"id": "T1", "title": "Old", "milestoneRef": "M1", '
                '"description": "Old", "acceptanceCriteria": ["AC1"], "dependsOn": [], '
                '"expectedFiles": [], "verificationHint": "hint"}]}'
            ),
        )
        feedback = [
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="first",
                decision="REQUEST_CHANGES",
                comment="First feedback",
            ),
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="second",
                decision="REJECTED",
                comment="Second feedback",
            ),
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="third",
                decision="REQUEST_CHANGES",
                comment="Third feedback",
            ),
        ]

        req = self._make_request(
            task_artifact=prev_task,
            feedback=feedback,
            metadata={"attempt": 2},
        )

        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        gw_req = gateway.requests[0]
        user_msg = gw_req.messages[1].content

        # Find positions of feedback items
        pos_first = user_msg.find("- [REQUEST_CHANGES] first: First feedback")
        pos_second = user_msg.find("- [REJECTED] second: Second feedback")
        pos_third = user_msg.find("- [REQUEST_CHANGES] third: Third feedback")

        self.assertNotEqual(pos_first, -1)
        self.assertNotEqual(pos_second, -1)
        self.assertNotEqual(pos_third, -1)
        self.assertTrue(pos_first < pos_second < pos_third)

    def test_revision_mode_empty_feedback_list_rejected(self):
        """Test that revision mode with empty feedback list is rejected at validation."""
        agent, gateway = self._make_agent([self.valid_reply])

        prev_task = self._make_task_artifact(
            artifact_id="task-v1",
            version="1",
            text=(
                '{"tasks": [{"id": "T1", "title": "Old", "milestoneRef": "M1", '
                '"description": "Old", "acceptanceCriteria": ["AC1"], "dependsOn": [], '
                '"expectedFiles": [], "verificationHint": "hint"}]}'
            ),
        )

        req = self._make_request(
            task_artifact=prev_task,
            feedback=[],  # Empty feedback - should fail validation
            metadata={"attempt": 2},
        )

        # Validation should fail
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("feedback", paths)

        # Execute should also be REJECTED
        res = agent.execute(req)
        self.assertEqual(res.status, "REJECTED")
        self.assertEqual(len(gateway.requests), 0)

    # === Batch 6: Rendering, limits, template tests ===

    def test_render_task_markdown_deterministic(self):
        """Test that _render_task_markdown produces deterministic output."""
        from asf.agents.plan.milestones import Milestone

        agent, _ = self._make_agent([self.valid_reply])

        # Create test tasks
        tasks = [
            TaskItem(
                id="T1",
                title="Create project scaffold",
                milestoneRef="M1",
                description="Initialize repository structure",
                acceptanceCriteria=["Repository builds", "CI passes"],
                dependsOn=[],
                expectedFiles=["pyproject.toml", "src/__init__.py"],
                verificationHint="Run pip install && pytest",
            ),
            TaskItem(
                id="T2",
                title="Implement core module",
                milestoneRef="M1",
                description="Write core business logic",
                acceptanceCriteria=["Unit tests pass", "Coverage >= 80%"],
                dependsOn=["T1"],
                expectedFiles=["src/core/logic.py"],
                verificationHint="Run pytest tests/unit/test_core.py",
            ),
            TaskItem(
                id="T3",
                title="Integrate with API",
                milestoneRef="M2",
                description="Wire core into FastAPI",
                acceptanceCriteria=["API endpoints work", "Integration tests pass"],
                dependsOn=["T2"],
                expectedFiles=["src/api/routes.py"],
                verificationHint="Run pytest tests/integration/test_api.py",
            ),
        ]

        plan_milestones = [
            Milestone(
                id="M1", name="Setup", deliverables="X", acceptance_criteria="Y", depends_on=()
            ),
            Milestone(
                id="M2", name="Core", deliverables="X", acceptance_criteria="Y", depends_on=("M1",)
            ),
        ]

        # Render twice
        rendered1 = render_task_markdown(tasks, plan_milestones, "spec-123", "1")
        rendered2 = render_task_markdown(tasks, plan_milestones, "spec-123", "1")

        self.assertEqual(rendered1, rendered2)

        # Check structure
        self.assertIn("# TASK: Breakdown", rendered1)
        self.assertIn("## Linked SPEC", rendered1)
        self.assertIn("ID: spec-123", rendered1)
        self.assertIn("Version: 1", rendered1)
        self.assertIn("## Milestone M1: Setup", rendered1)
        self.assertIn("## Milestone M2: Core", rendered1)
        self.assertIn("### T1: Create project scaffold", rendered1)
        self.assertIn("### T2: Implement core module", rendered1)
        self.assertIn("### T3: Integrate with API", rendered1)
        self.assertIn("**Description:** Initialize repository structure", rendered1)
        self.assertIn("**Acceptance Criteria:**", rendered1)
        self.assertIn("- Repository builds", rendered1)
        self.assertIn("- CI passes", rendered1)
        self.assertIn("**Verification Hint:** Run pip install && pytest", rendered1)
        self.assertIn("**Depends On:** T1", rendered1)
        self.assertIn("**Expected Files:**", rendered1)
        self.assertIn("- pyproject.toml", rendered1)
        self.assertIn("- src/__init__.py", rendered1)

    def test_render_task_markdown_milestone_numeric_sort(self):
        """Test that milestones are sorted numerically (M10 after M9)."""
        from asf.agents.plan.milestones import Milestone

        agent, _ = self._make_agent([self.valid_reply])

        tasks = [
            TaskItem(
                id="T1",
                title="Task M10",
                milestoneRef="M10",
                description="Task in M10",
                acceptanceCriteria=["AC1"],
                dependsOn=[],
                expectedFiles=[],
                verificationHint="hint",
            ),
            TaskItem(
                id="T2",
                title="Task M2",
                milestoneRef="M2",
                description="Task in M2",
                acceptanceCriteria=["AC2"],
                dependsOn=[],
                expectedFiles=[],
                verificationHint="hint",
            ),
        ]

        plan_milestones = [
            Milestone(
                id="M2",
                name="Milestone 2",
                deliverables="X",
                acceptance_criteria="Y",
                depends_on=("M1",),
            ),
            Milestone(
                id="M10",
                name="Milestone 10",
                deliverables="X",
                acceptance_criteria="Y",
                depends_on=("M9",),
            ),
        ]

        rendered = render_task_markdown(tasks, plan_milestones, "spec-123", "1")

        # M2 should appear before M10
        pos_m2 = rendered.find("## Milestone M2: Milestone 2")
        pos_m10 = rendered.find("## Milestone M10: Milestone 10")
        self.assertNotEqual(pos_m2, -1)
        self.assertNotEqual(pos_m10, -1)
        self.assertTrue(pos_m2 < pos_m10)

    def test_render_task_markdown_empty_milestone_skipped(self):
        """Test that milestones with no tasks are skipped in rendering."""
        from asf.agents.plan.milestones import Milestone

        agent, _ = self._make_agent([self.valid_reply])

        tasks = [
            TaskItem(
                id="T1",
                title="Task M1",
                milestoneRef="M1",
                description="Task in M1",
                acceptanceCriteria=["AC1"],
                dependsOn=[],
                expectedFiles=[],
                verificationHint="hint",
            ),
            TaskItem(
                id="T2",
                title="Task M3",
                milestoneRef="M3",
                description="Task in M3",
                acceptanceCriteria=["AC2"],
                dependsOn=[],
                expectedFiles=[],
                verificationHint="hint",
            ),
        ]

        plan_milestones = [
            Milestone(
                id="M1", name="Setup", deliverables="X", acceptance_criteria="Y", depends_on=()
            ),
            Milestone(
                id="M2", name="Core", deliverables="X", acceptance_criteria="Y", depends_on=("M1",)
            ),
            Milestone(
                id="M3",
                name="Integration",
                deliverables="X",
                acceptance_criteria="Y",
                depends_on=("M2",),
            ),
        ]

        rendered = render_task_markdown(tasks, plan_milestones, "spec-123", "1")

        # M1 and M3 should appear, M2 should be skipped (no tasks)
        self.assertIn("## Milestone M1: Setup", rendered)
        self.assertNotIn("## Milestone M2: Core", rendered)
        self.assertIn("## Milestone M3: Integration", rendered)

    def test_max_task_chars_limit_validation(self):
        """Test MAX_TASK_CHARS limit validation in _check."""

        # Create SPEC + PLAN that exceeds MAX_TASK_CHARS
        large_text = "x" * (MAX_TASK_CHARS + 1)
        spec_art = self._make_spec_artifact(text=large_text)
        plan_art = self._make_plan_artifact()

        req = self._make_request(spec_artifact=spec_art, plan_artifact=plan_art)
        agent, _ = self._make_agent([self.valid_reply])

        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        self.assertTrue(
            any("exceeds" in err.message and "characters" in err.message for err in val_res.errors)
        )

    def test_max_task_chars_at_limit_passes(self):
        """Test that SPEC + PLAN at exactly MAX_TASK_CHARS passes validation."""

        # Create SPEC + PLAN that is exactly at MAX_TASK_CHARS
        # Need valid PLAN format with milestones
        spec_text = "x" * (MAX_TASK_CHARS // 2)

        # Build a valid PLAN with milestones that totals the remaining chars
        plan_header = "# PLAN: Test Plan\n## Linked SPEC\nID: spec-123\nVersion: 1\n## Milestones\n"
        remaining = MAX_TASK_CHARS - len(spec_text) - len(plan_header)
        # Each milestone needs some content - use one milestone with large content
        milestone_content = (
            "### M1: Setup\n- Deliverables: "
            + "d" * max(0, remaining - 100)
            + "\n- Acceptance criteria: OK\n- Depends on: none"
        )
        plan_text = plan_header + milestone_content

        spec_art = self._make_spec_artifact(text=spec_text)
        plan_art = self._make_plan_artifact(text=plan_text)

        req = self._make_request(spec_artifact=spec_art, plan_artifact=plan_art)
        agent, _ = self._make_agent([self.valid_reply])

        val_res = agent.validate(req)
        self.assertTrue(val_res.valid)

    def test_task_template_contains_required_sections(self):
        """Test that TASK.md template contains all required sections."""
        template_text = self.template.text

        # Required sections from template
        self.assertIn("## Output Format", template_text)
        self.assertIn("## Task Object Fields", template_text)
        self.assertIn("## Validation Rules", template_text)
        self.assertIn("## Worked Example", template_text)

        # Check worked example has valid JSON structure
        self.assertIn('"id"', template_text)
        self.assertIn('"title"', template_text)
        self.assertIn('"milestoneRef"', template_text)
        self.assertIn('"description"', template_text)
        self.assertIn('"acceptanceCriteria"', template_text)
        self.assertIn('"dependsOn"', template_text)
        self.assertIn('"expectedFiles"', template_text)
        self.assertIn('"verificationHint"', template_text)

    def test_task_template_worked_example_valid_json(self):
        """Test that the worked example in TASK.md is valid JSON with correct structure."""
        import json
        import re

        template_text = self.template.text

        # Extract the JSON from the worked example (there are two ```json blocks:
        # 1. A placeholder with { ...task object... }
        # 2. The actual worked example)
        matches = re.findall(r"```json\n(.*?)\n```", template_text, re.DOTALL)
        self.assertGreaterEqual(len(matches), 2, "Expected at least two JSON blocks in template")

        # The second block should be the actual worked example
        example_json = matches[1]
        data = json.loads(example_json)

        self.assertIn("tasks", data)
        self.assertIsInstance(data["tasks"], list)
        self.assertEqual(len(data["tasks"]), 3)

        # Check first task
        t1 = data["tasks"][0]
        self.assertEqual(t1["id"], "T1")
        self.assertEqual(t1["title"], "Create project scaffold")
        self.assertEqual(t1["milestoneRef"], "M1")
        self.assertIn("Repository builds successfully", t1["acceptanceCriteria"])
        self.assertIn("CI pipeline passes on main branch", t1["acceptanceCriteria"])
        self.assertEqual(t1["dependsOn"], [])
        self.assertIn("pyproject.toml", t1["expectedFiles"])
        self.assertIn("src/__init__.py", t1["expectedFiles"])
        self.assertIn(".gitlab-ci.yml", t1["expectedFiles"])
        self.assertIn("pip install -e . && pytest", t1["verificationHint"])

        # Check second task
        t2 = data["tasks"][1]
        self.assertEqual(t2["id"], "T2")
        self.assertEqual(t2["milestoneRef"], "M1")
        self.assertIn("T1", t2["dependsOn"])

        # Check third task
        t3 = data["tasks"][2]
        self.assertEqual(t3["id"], "T3")
        self.assertEqual(t3["milestoneRef"], "M2")
        self.assertIn("T2", t3["dependsOn"])

    def test_task_template_required_sections_property(self):
        """Test that TaskTemplate has required_sections property or method."""
        # TaskTemplate is a simple dataclass with text field
        # Check that we can access the template text
        self.assertIsInstance(self.template.text, str)
        self.assertGreater(len(self.template.text), 0)

        # The template should contain key structural elements
        template = self.template.text
        self.assertIn("# TASK Breakdown Specification", template)
        self.assertIn("## Output Format", template)
        self.assertIn("## Task Object Fields", template)
        self.assertIn("## Validation Rules", template)
        self.assertIn("## Worked Example", template)

    def test_rendered_output_includes_all_task_fields(self):
        """Test that rendered markdown includes all task fields."""
        agent, _ = self._make_agent([self.valid_reply])

        # Create a task with all fields populated
        tasks = [
            TaskItem(
                id="T1",
                title="Full Task",
                milestoneRef="M1",
                description="Complete description",
                acceptanceCriteria=["AC1", "AC2"],
                dependsOn=[],
                expectedFiles=["src/file1.py", "src/file2.py"],
                verificationHint="Run tests",
            ),
        ]

        from asf.agents.plan.milestones import Milestone

        plan_milestones = [
            Milestone(
                id="M1",
                name="Setup",
                deliverables="X",
                acceptance_criteria="Y",
                depends_on=(),
            ),
        ]

        rendered = render_task_markdown(tasks, plan_milestones, "spec-123", "1")

        # Verify all fields appear in output
        self.assertIn("### T1: Full Task", rendered)
        self.assertIn("**Description:** Complete description", rendered)
        self.assertIn("- AC1", rendered)
        self.assertIn("- AC2", rendered)
        self.assertIn("**Expected Files:**", rendered)
        self.assertIn("- src/file1.py", rendered)
        self.assertIn("- src/file2.py", rendered)
        self.assertIn("**Verification Hint:** Run tests", rendered)

    # === Batch 7: Factory tests ===

    def test_build_task_agent_default_config(self):
        """Test build_task_agent with default (no model profile) configuration."""

        from asf.agents.base import AgentRuntime
        from asf.agents.task.factory import build_task_agent
        from asf.configuration.platform import PlatformConfig

        runtime = AgentRuntime(
            models=ScriptedModelGateway([self.valid_reply]),
            clock=lambda: T_AWARE,
            new_id=counter_id("gen-"),
        )
        platform = PlatformConfig()  # No agents config
        templates_dir = REPO_ROOT / "templates"

        agent = build_task_agent(runtime, platform, templates_dir)

        self.assertIsInstance(agent, TaskAgent)
        self.assertIsNone(agent._model)
        self.assertEqual(agent._parameters, {})

    def test_build_task_agent_with_model_profile(self):
        """Test build_task_agent with a model profile in platform config."""

        from asf.agents.base import AgentRuntime
        from asf.agents.task.factory import build_task_agent
        from asf.configuration.platform import (
            AgentSettings,
            ModelProfile,
            ModelsConfig,
            PlatformConfig,
        )

        runtime = AgentRuntime(
            models=ScriptedModelGateway([self.valid_reply]),
            clock=lambda: T_AWARE,
            new_id=counter_id("gen-"),
        )
        platform = PlatformConfig(
            models=ModelsConfig(
                profiles={
                    "test-profile": ModelProfile(
                        provider="test",
                        model="test-model-v2",
                        parameters={"temperature": 0.5, "top_p": 0.9},
                    )
                }
            ),
            agents={"task": AgentSettings(model_profile="test-profile")},
        )
        templates_dir = REPO_ROOT / "templates"

        agent = build_task_agent(runtime, platform, templates_dir)

        self.assertIsInstance(agent, TaskAgent)
        self.assertEqual(agent._model, "test-model-v2")
        self.assertEqual(agent._parameters, {"temperature": 0.5, "top_p": 0.9})

    def test_build_task_agent_unknown_model_profile_raises(self):
        """Test build_task_agent raises when model profile doesn't exist."""

        from asf.agents.base import AgentRuntime
        from asf.agents.task.factory import build_task_agent
        from asf.configuration.platform import (
            AgentSettings,
            ModelProfile,
            ModelsConfig,
            PlatformConfig,
        )

        runtime = AgentRuntime(
            models=ScriptedModelGateway([self.valid_reply]),
            clock=lambda: T_AWARE,
            new_id=counter_id("gen-"),
        )
        # PlatformConfig validates agent model_profile references at creation time
        with self.assertRaises(Exception) as cm:
            platform = PlatformConfig(
                models=ModelsConfig(
                    profiles={
                        "existing-profile": ModelProfile(
                            provider="test",
                            model="test-model",
                            parameters={},
                        )
                    }
                ),
                agents={"task": AgentSettings(model_profile="non-existent-profile")},
            )
            build_task_agent(runtime, platform, REPO_ROOT / "templates")
        self.assertIn("unknown modelProfile", str(cm.exception))

    def test_build_task_agent_loads_correct_prompts_and_template(self):
        """Test that build_task_agent loads the correct prompts and template."""

        from asf.agents.base import AgentRuntime
        from asf.agents.loading import load_task_prompts, load_task_template
        from asf.agents.task.factory import build_task_agent
        from asf.configuration.platform import PlatformConfig

        runtime = AgentRuntime(
            models=ScriptedModelGateway([self.valid_reply]),
            clock=lambda: T_AWARE,
            new_id=counter_id("gen-"),
        )
        platform = PlatformConfig()
        templates_dir = REPO_ROOT / "templates"

        agent = build_task_agent(runtime, platform, templates_dir)

        # Verify prompts are loaded correctly
        expected_prompts = load_task_prompts()
        self.assertEqual(agent._prompts.system, expected_prompts.system)
        self.assertEqual(agent._prompts.revision, expected_prompts.revision)

        # Verify template is loaded correctly
        expected_template = load_task_template(templates_dir)
        self.assertEqual(agent._template.text, expected_template.text)

    def test_build_plan_agent_default_config(self):
        """Test build_plan_agent with default (no model profile) configuration."""

        from asf.agents.base import AgentRuntime
        from asf.agents.plan.agent import PlanAgent
        from asf.agents.plan.factory import build_plan_agent
        from asf.configuration.platform import PlatformConfig

        runtime = AgentRuntime(
            models=ScriptedModelGateway([]),
            clock=lambda: T_AWARE,
            new_id=counter_id("gen-"),
        )
        platform = PlatformConfig()
        templates_dir = REPO_ROOT / "templates"

        agent = build_plan_agent(runtime, platform, templates_dir)

        self.assertIsInstance(agent, PlanAgent)
        self.assertIsNone(agent._model)
        self.assertEqual(agent._parameters, {})

    def test_build_plan_agent_with_model_profile(self):
        """Test build_plan_agent with a model profile in platform config."""

        from asf.agents.base import AgentRuntime
        from asf.agents.plan.agent import PlanAgent
        from asf.agents.plan.factory import build_plan_agent
        from asf.configuration.platform import (
            AgentSettings,
            ModelProfile,
            ModelsConfig,
            PlatformConfig,
        )

        runtime = AgentRuntime(
            models=ScriptedModelGateway([]),
            clock=lambda: T_AWARE,
            new_id=counter_id("gen-"),
        )
        platform = PlatformConfig(
            models=ModelsConfig(
                profiles={
                    "plan-profile": ModelProfile(
                        provider="test",
                        model="plan-model-v3",
                        parameters={"temperature": 0.2},
                    )
                }
            ),
            agents={"plan": AgentSettings(model_profile="plan-profile")},
        )
        templates_dir = REPO_ROOT / "templates"

        agent = build_plan_agent(runtime, platform, templates_dir)

        self.assertIsInstance(agent, PlanAgent)
        self.assertEqual(agent._model, "plan-model-v3")
        self.assertEqual(agent._parameters, {"temperature": 0.2})

    def test_build_plan_agent_loads_correct_prompts_and_template(self):
        """Test that build_plan_agent loads the correct prompts and template."""

        from asf.agents.base import AgentRuntime
        from asf.agents.loading import load_plan_prompts, load_plan_template
        from asf.agents.plan.factory import build_plan_agent
        from asf.configuration.platform import PlatformConfig

        runtime = AgentRuntime(
            models=ScriptedModelGateway([]),
            clock=lambda: T_AWARE,
            new_id=counter_id("gen-"),
        )
        platform = PlatformConfig()
        templates_dir = REPO_ROOT / "templates"

        agent = build_plan_agent(runtime, platform, templates_dir)

        # Verify prompts are loaded correctly
        expected_prompts = load_plan_prompts()
        self.assertEqual(agent._prompts.system, expected_prompts.system)
        self.assertEqual(agent._prompts.revision, expected_prompts.revision)

        # Verify template is loaded correctly
        expected_template = load_plan_template(templates_dir)
        self.assertEqual(agent._template.text, expected_template.text)

    # === Batch 8: milestone_number tests ===

    def test_milestone_number_milestone_ids(self):
        """Test milestone_number extracts numeric part from milestone IDs."""
        from asf.agents.plan.milestones import milestone_number

        self.assertEqual(milestone_number("M1"), 1)
        self.assertEqual(milestone_number("M2"), 2)
        self.assertEqual(milestone_number("M9"), 9)
        self.assertEqual(milestone_number("M10"), 10)
        self.assertEqual(milestone_number("M11"), 11)
        self.assertEqual(milestone_number("M20"), 20)
        self.assertEqual(milestone_number("M99"), 99)
        self.assertEqual(milestone_number("M100"), 100)

    def test_milestone_number_task_ids(self):
        """Test milestone_number extracts numeric part from task IDs."""
        from asf.agents.plan.milestones import milestone_number

        self.assertEqual(milestone_number("T1"), 1)
        self.assertEqual(milestone_number("T2"), 2)
        self.assertEqual(milestone_number("T9"), 9)
        self.assertEqual(milestone_number("T10"), 10)
        self.assertEqual(milestone_number("T11"), 11)
        self.assertEqual(milestone_number("T100"), 100)

    def test_milestone_number_preserves_numeric_order(self):
        """Test that milestone_number preserves numeric order (not lexical)."""
        from asf.agents.plan.milestones import milestone_number

        # Numeric order: M1, M2, M3, ..., M9, M10, M11
        # Lexical order would be: M1, M10, M11, M2, M3, ...
        ids = ["M1", "M2", "M3", "M9", "M10", "M11", "M20"]
        numbers = [milestone_number(mid) for mid in ids]
        self.assertEqual(numbers, [1, 2, 3, 9, 10, 11, 20])
        self.assertEqual(numbers, sorted(numbers))

    def test_milestone_number_case_insensitive(self):
        """Test milestone_number works with lowercase IDs."""
        from asf.agents.plan.milestones import milestone_number

        self.assertEqual(milestone_number("m1"), 1)
        self.assertEqual(milestone_number("m10"), 10)
        self.assertEqual(milestone_number("t5"), 5)

    # === Batch 9: Cover remaining uncovered lines ===

    def test_validate_plan_artifact_no_milestones_triggers_exception(self):
        """Test that PLAN with no milestones triggers exception handler (agent.py:229-234)."""
        agent, gateway = self._make_agent([self.valid_reply])

        # PLAN with no milestones - should fail validation with parse error
        plan_art = self._make_plan_artifact(
            text=("# PLAN: No Milestones\n## Linked SPEC\n...\n## Description\nNo milestones here")
        )

        req = self._make_request(plan_artifact=plan_art)
        val_res = agent.validate(req)

        self.assertFalse(val_res.valid)
        # The exception handler catches the MilestoneValidationError
        self.assertTrue(any("failed to parse milestones" in err.message for err in val_res.errors))

        # Execute should also be REJECTED
        res = agent.execute(req)
        self.assertEqual(res.status, "REJECTED")

    def test_depends_on_numeric_order(self):
        """Test that dependsOn numeric ordering triggers agent.py:479.

        This requires a task depending on an already-seen task with a higher number.
        E.g., task list order: T1, T3, T2 where T2 depends on T3.
        """
        import json as json_lib

        # T1, T3, T2 - T2 is last but depends on T3 (already seen, higher number)
        bad_reply = json_lib.dumps(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Task 1",
                        "milestoneRef": "M1",
                        "description": "Task 1 desc",
                        "acceptanceCriteria": ["AC1"],
                        "dependsOn": [],
                        "expectedFiles": [],
                        "verificationHint": "hint1",
                    },
                    {
                        "id": "T3",
                        "title": "Task 3",
                        "milestoneRef": "M1",
                        "description": "Task 3 desc",
                        "acceptanceCriteria": ["AC3"],
                        "dependsOn": [],
                        "expectedFiles": [],
                        "verificationHint": "hint3",
                    },
                    {
                        "id": "T2",
                        "title": "Task 2",
                        "milestoneRef": "M1",
                        "description": "Task 2 desc",
                        "acceptanceCriteria": ["AC2"],
                        "dependsOn": ["T3"],  # Depends on T3 which is already seen, but T3 > T2
                        "expectedFiles": [],
                        "verificationHint": "hint2",
                    },
                ]
            },
            indent=2,
        )

        agent, _ = self._make_agent([bad_reply])
        res = agent.execute(self._make_request())

        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("taskIssues", res.errors[0].details)
        expected_msg = "depends on 'T3' which is not a lower-numbered task"
        self.assertTrue(any(expected_msg in issue for issue in res.errors[0].details["taskIssues"]))

    def test_validate_task_output_invalid_json(self):
        """Test validate_task_output handles invalid JSON (prompts.py:53)."""
        from asf.agents.task.prompts import validate_task_output

        issues = validate_task_output("not valid json")
        self.assertTrue(any("Invalid JSON" in issue for issue in issues))

    def test_validate_task_output_not_object(self):
        """Test validate_task_output handles non-object JSON (prompts.py:56)."""
        from asf.agents.task.prompts import validate_task_output

        issues = validate_task_output('["not", "an", "object"]')
        self.assertTrue(any("must be a JSON object" in issue for issue in issues))

    def test_validate_task_output_missing_tasks_key(self):
        """Test validate_task_output handles missing tasks key (prompts.py:60)."""
        from asf.agents.task.prompts import validate_task_output

        issues = validate_task_output('{"other": "value"}')
        expected = "Missing 'tasks' key"
        self.assertTrue(any(expected in issue for issue in issues))

    def test_validate_task_output_tasks_not_list(self):
        """Test validate_task_output handles tasks not a list (prompts.py:65)."""
        from asf.agents.task.prompts import validate_task_output

        issues = validate_task_output('{"tasks": "not a list"}')
        self.assertTrue(any("'tasks' must be a list" in issue for issue in issues))

    def test_validate_task_output_valid(self):
        """Test validate_task_output returns empty for valid input (prompts.py:68)."""
        from asf.agents.task.prompts import validate_task_output

        issues = validate_task_output(
            '{"tasks": [{"id": "T1", "title": "Test", "milestoneRef": "M1", '
            '"description": "Desc", "acceptanceCriteria": ["AC"], "dependsOn": [], '
            '"expectedFiles": [], "verificationHint": "hint"}]}'
        )
        self.assertEqual(issues, [])

    def test_build_user_message_spec_content_string(self):
        """Test build_user_message handles spec_artifact content as string (prompts.py:89-90)."""
        from asf.agents.task.prompts import build_user_message

        spec_artifact = {
            "id": "spec-123",
            "version": "1",
            "content": "SPEC content as string directly",  # String content, not dict
        }
        plan_artifact = {
            "id": "plan-123",
            "version": "1",
            "content": {"text": "PLAN content"},
        }

        result = build_user_message(spec_artifact, plan_artifact, "en", None, "template")
        self.assertIn("SPEC content as string directly", result)

    def test_build_user_message_plan_content_string(self):
        """Test build_user_message handles plan_artifact content as string (prompts.py:100-101)."""
        from asf.agents.task.prompts import build_user_message

        spec_artifact = {
            "id": "spec-123",
            "version": "1",
            "content": {"text": "SPEC content"},
        }
        plan_artifact = {
            "id": "plan-123",
            "version": "1",
            "content": "PLAN content as string directly",  # String content, not dict
        }

        result = build_user_message(spec_artifact, plan_artifact, "en", None, "template")
        self.assertIn("PLAN content as string directly", result)

    def test_build_user_message_empty_project_context(self):
        """Test build_user_message with empty project_context (prompts.py:119-121)."""
        from asf.agents.task.prompts import build_user_message

        spec_artifact = {"id": "spec-1", "version": "1", "content": {"text": "SPEC"}}
        plan_artifact = {"id": "plan-1", "version": "1", "content": {"text": "PLAN"}}

        # Empty project_context
        result = build_user_message(spec_artifact, plan_artifact, "en", {}, "template")
        self.assertIn("## Project context\nnone", result)

        # Project context with no whitelisted keys
        project_ctx = {"other_key": "value"}
        result = build_user_message(spec_artifact, plan_artifact, "en", project_ctx, "template")
        self.assertIn("## Project context\nnone", result)


if __name__ == "__main__":
    unittest.main()
