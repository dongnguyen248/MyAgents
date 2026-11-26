from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asf.agents._shared.map_emit import (
    TASK_STRUCTURE_REJECTED_LABEL,
    emit_output_rejected,
    sections_rejected_label,
)
from asf.agents.base import AgentRuntime
from asf.agents.loading import (
    load_plan_prompts,
    load_plan_template,
    load_spec_prompts,
    load_spec_template,
    load_task_prompts,
    load_task_template,
)
from asf.agents.plan.agent import PlanAgent, PlanSettings
from asf.agents.spec.agent import SpecAgent, SpecSettings
from asf.agents.task.agent import TaskAgent, TaskSettings
from asf.contracts.map_events import MapEvent
from asf.contracts.models import AgentRequest, Artifact
from asf.models.fake import ScriptedModelGateway
from asf.models.map_tap import map_call_context, set_default_map_clock, set_default_map_tap

REPO_ROOT = Path(__file__).resolve().parents[2]
T_START = datetime(2026, 11, 23, 9, 0, 0, tzinfo=UTC)
RUN_METADATA = {"attempt": 1, "runId": "run-1"}
PROJECT = {
    "name": "AuthService",
    "description": "Handles authentication",
    "technology": ["python", "fastapi"],
}


class RecordingTap:
    def __init__(self) -> None:
        self.events: list[MapEvent] = []

    def emit(self, event: MapEvent) -> None:
        self.events.append(event)


def counter_id(prefix: str = "gen-"):
    count = 0

    def _next() -> str:
        nonlocal count
        count += 1
        return f"{prefix}{count}"

    return _next


def make_request(agent_id: str, artifacts: list[Artifact], inp: dict[str, Any]) -> AgentRequest:
    return AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id=agent_id,
        input=inp,
        context={"project": PROJECT},
        artifacts=artifacts,
        feedback=[],
        metadata=dict(RUN_METADATA),
    )


def spec_artifact() -> Artifact:
    return Artifact(
        id="spec-123",
        type="SPEC",
        name="SPEC.md",
        version="1",
        content={"format": "markdown", "text": "# SPEC: Test Spec\n## Background / Goal\nBody."},
        created_by="agent-spec",
        created_at=T_START,
        metadata={"template": "spec"},
    )


def plan_artifact() -> Artifact:
    text = (
        "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n"
        "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
        "### M2: Core\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M1"
    )
    return Artifact(
        id="plan-123",
        type="PLAN",
        name="PLAN.md",
        version="1",
        content={"format": "markdown", "text": text},
        created_by="agent-plan",
        created_at=T_START,
        metadata={"template": "plan", "specArtifactId": "spec-123", "specVersion": "1"},
    )


def sections_reply(title: str, sections: list[str]) -> str:
    lines = [title]
    for section in sections:
        lines.append(section)
        lines.append("Section details content.")
    return "\n\n".join(lines)


class RejectedPulseBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tap = RecordingTap()
        set_default_map_tap(self.tap)
        set_default_map_clock(None)

    def tearDown(self) -> None:
        set_default_map_tap(None)

    def rejected(self) -> list[MapEvent]:
        return [e for e in self.tap.events if e.type == "agent" and e.phase == "moment"]

    def execute(self, agent: Any, request: AgentRequest) -> Any:
        with map_call_context(request, T_START):
            return agent.execute(request)


class SpecRejectedPulseTests(RejectedPulseBase):
    def setUp(self) -> None:
        super().setUp()
        self.template = load_spec_template(REPO_ROOT / "templates")
        self.valid = sections_reply("# SPEC: Test", self.template.required_sections)
        self.partial = sections_reply("# SPEC: Test", self.template.required_sections[:1])

    def _agent(self, script: list[Any]) -> SpecAgent:
        runtime = AgentRuntime(
            models=ScriptedModelGateway(script), clock=lambda: T_START, new_id=counter_id()
        )
        settings = SpecSettings(
            prompts=load_spec_prompts(), template=self.template, model="test-model"
        )
        return SpecAgent(runtime, settings)

    def _request(self) -> AgentRequest:
        return make_request("agent-spec", [], {"requirement": "Build auth"})

    def test_retry_then_success_emits_one_counts_only_pulse(self) -> None:
        result = self.execute(self._agent([self.partial, self.valid]), self._request())
        self.assertEqual(result.status, "SUCCESS")
        pulses = self.rejected()
        self.assertEqual(len(pulses), 1)
        pulse = pulses[0]
        total = len(self.template.required_sections)
        self.assertEqual(pulse.label, f"rejected: missing {total - 1}/{total} sections, retrying")
        self.assertEqual(pulse.status, "error")
        self.assertEqual(pulse.station, "agents")
        self.assertEqual(pulse.error_code, "LLM_INVALID_RESPONSE")
        self.assertEqual(pulse.attempt, 1)
        for section in self.template.required_sections:
            self.assertNotIn(section, pulse.label)

    def test_exhausted_retry_still_emits_exactly_one_pulse(self) -> None:
        result = self.execute(self._agent([self.partial, self.partial]), self._request())
        self.assertEqual(result.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertEqual(len(self.rejected()), 1)

    def test_clean_first_reply_emits_no_pulse(self) -> None:
        result = self.execute(self._agent([self.valid]), self._request())
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(self.rejected(), [])


class PlanRejectedPulseTests(RejectedPulseBase):
    def setUp(self) -> None:
        super().setUp()
        self.template = load_plan_template(REPO_ROOT / "templates")

    def _agent(self, script: list[Any]) -> PlanAgent:
        runtime = AgentRuntime(
            models=ScriptedModelGateway(script), clock=lambda: T_START, new_id=counter_id()
        )
        settings = PlanSettings(
            prompts=load_plan_prompts(), template=self.template, model="test-model"
        )
        return PlanAgent(runtime, settings)

    def test_missing_sections_emits_one_pulse_without_retrying(self) -> None:
        request = make_request("agent-plan", [spec_artifact()], {})
        result = self.execute(self._agent(["# PLAN: Test\nSome prose."]), request)
        self.assertEqual(result.errors[0].code, "LLM_INVALID_RESPONSE")
        pulses = self.rejected()
        self.assertEqual(len(pulses), 1)
        total = len(self.template.required_sections)
        stamped = 1 if "## Linked SPEC" in self.template.required_sections else 0
        self.assertEqual(pulses[0].label, f"rejected: missing {total - stamped}/{total} sections")
        self.assertEqual(pulses[0].attempt, 1)


class TaskRejectedPulseTests(RejectedPulseBase):
    def _agent(self, script: list[Any]) -> TaskAgent:
        runtime = AgentRuntime(
            models=ScriptedModelGateway(script), clock=lambda: T_START, new_id=counter_id()
        )
        settings = TaskSettings(
            prompts=load_task_prompts(),
            template=load_task_template(REPO_ROOT / "templates"),
            model="test-model",
        )
        return TaskAgent(runtime, settings)

    def _request(self) -> AgentRequest:
        return make_request("agent-task", [spec_artifact(), plan_artifact()], {})

    def test_invalid_json_emits_one_structure_pulse(self) -> None:
        result = self.execute(self._agent(["this is not json"]), self._request())
        self.assertEqual(result.errors[0].code, "LLM_INVALID_RESPONSE")
        pulses = self.rejected()
        self.assertEqual(len(pulses), 1)
        self.assertEqual(pulses[0].label, TASK_STRUCTURE_REJECTED_LABEL)
        self.assertEqual(pulses[0].error_code, "LLM_INVALID_RESPONSE")

    def test_invalid_structure_emits_one_structure_pulse(self) -> None:
        result = self.execute(self._agent(['{"tasks": []}']), self._request())
        self.assertEqual(result.errors[0].code, "LLM_INVALID_RESPONSE")
        pulses = self.rejected()
        self.assertEqual(len(pulses), 1)
        self.assertEqual(pulses[0].label, TASK_STRUCTURE_REJECTED_LABEL)


class RejectedHelperTests(RejectedPulseBase):
    def test_label_forms(self) -> None:
        self.assertEqual(
            sections_rejected_label(3, 7, retrying=True), "rejected: missing 3/7 sections, retrying"
        )
        self.assertEqual(
            sections_rejected_label(3, 7, retrying=False), "rejected: missing 3/7 sections"
        )

    def test_no_context_emits_nothing(self) -> None:
        request = make_request("agent-spec", [], {"requirement": "Build auth"})
        emit_output_rejected(request, "rejected: missing 1/7 sections")
        self.assertEqual(self.tap.events, [])

    def test_no_run_id_emits_nothing(self) -> None:
        request = make_request("agent-spec", [], {"requirement": "Build auth"})
        request = request.model_copy(update={"metadata": {"attempt": 1}})
        with map_call_context(request, T_START):
            emit_output_rejected(request, "rejected: missing 1/7 sections")
        self.assertEqual(self.tap.events, [])

    def test_broken_tap_never_raises(self) -> None:
        class BrokenTap:
            def emit(self, event: MapEvent) -> None:
                raise RuntimeError("tap down")

        set_default_map_tap(BrokenTap())
        request = make_request("agent-spec", [], {"requirement": "Build auth"})
        with map_call_context(request, T_START):
            emit_output_rejected(request, "rejected: missing 1/7 sections")


if __name__ == "__main__":
    unittest.main()
