from __future__ import annotations

import time
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any

from asf.agents._shared.model_call import call_model
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.contracts.map_events import MapEvent
from asf.contracts.models import (
    AgentMetadata,
    AgentRequest,
    AgentResult,
    Artifact,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from asf.models.errors import ModelGatewayError
from asf.models.map_tap import MapTap, set_default_map_tap

T_START = datetime(2026, 11, 23, 9, 0, 0, tzinfo=UTC)


class StepClock:
    def __init__(self) -> None:
        self.current = T_START

    def __call__(self) -> datetime:
        moment = self.current
        self.current = self.current + timedelta(seconds=1)
        return moment


class CounterId:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> str:
        self.count += 1
        return f"id-{self.count}"


class ReplyGateway:
    def __init__(self, finish_reason: str = "stop") -> None:
        self.finish_reason = finish_reason

    def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content="a spec draft",
            model="fake-1",
            usage=ModelUsage(prompt_tokens=120, completion_tokens=30),
            finish_reason=self.finish_reason,
        )


class FailingGateway:
    def complete(self, request: ModelRequest) -> ModelResponse:
        raise ModelGatewayError("LLM_TIMEOUT", "provider is down")


class ModelAgent(BaseAgent):
    @property
    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            id="agent-spec",
            name="Spec Agent",
            type="spec",
            version="1.0.0",
            status="IDLE",
            capabilities=["spec"],
            configuration={},
        )

    def _check(self, request: AgentRequest) -> list[Issue]:
        return []

    def _run(self, request: AgentRequest) -> tuple[Any, list[Artifact]]:
        outgoing = ModelRequest(
            messages=[ModelMessage(role="user", content="write it")],
            model="fake-1",
        )
        response = call_model(self._runtime.models, outgoing)
        artifact = Artifact(
            id="spec-1",
            type="SPEC",
            name="Spec",
            version="1",
            content=response.content,
            created_by="agent-spec",
            created_at=T_START,
        )
        return response.content, [artifact]


class RecordingTap:
    def __init__(self) -> None:
        self.events: list[MapEvent] = []

    def emit(self, event: MapEvent) -> None:
        self.events.append(event)


class RaisingTap:
    def emit(self, event: MapEvent) -> None:
        raise RuntimeError("the map is broken")


class SlowTap:
    def __init__(self) -> None:
        self.events: list[MapEvent] = []

    def emit(self, event: MapEvent) -> None:
        time.sleep(0.05)
        self.events.append(event)


def make_request() -> AgentRequest:
    return AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="agent-spec",
        input={"requirement": "a login page"},
        metadata={"attempt": 1, "runId": "run-1"},
    )


def run_agent(tap: MapTap | None, gateway: Any = None) -> AgentResult:
    set_default_map_tap(tap)
    try:
        runtime = AgentRuntime(
            models=gateway or ReplyGateway(),
            clock=StepClock(),
            new_id=CounterId(),
        )
        return ModelAgent(runtime).execute(make_request())
    finally:
        set_default_map_tap(None)


def comparable(result: AgentResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


class MapTapResultSafetyTests(unittest.TestCase):
    def test_no_tap_baseline(self) -> None:
        result = run_agent(None)
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.metrics.prompt_tokens, 120)
        self.assertEqual(result.metrics.model_calls, 1)

    def test_raising_tap_leaves_the_result_unchanged(self) -> None:
        baseline = comparable(run_agent(None))
        with_tap = comparable(run_agent(RaisingTap()))
        self.assertEqual(with_tap, baseline)

    def test_slow_tap_leaves_the_result_unchanged(self) -> None:
        baseline = comparable(run_agent(None))
        with_tap = comparable(run_agent(SlowTap()))
        self.assertEqual(with_tap, baseline)

    def test_raising_tap_leaves_a_failure_result_unchanged(self) -> None:
        baseline = comparable(run_agent(None, FailingGateway()))
        with_tap = comparable(run_agent(RaisingTap(), FailingGateway()))
        self.assertEqual(with_tap, baseline)
        self.assertEqual(with_tap["status"], "FAILED")


class MapTapPulseTests(unittest.TestCase):
    def test_agent_and_model_pulses_wrap_the_execution(self) -> None:
        tap = RecordingTap()
        result = run_agent(tap)
        self.assertEqual(result.status, "SUCCESS")
        kinds = [(e.type, e.phase) for e in tap.events]
        self.assertEqual(
            kinds,
            [("agent", "start"), ("model", "start"), ("model", "end"), ("agent", "end")],
        )

    def test_model_end_pulse_carries_usage_and_parentage(self) -> None:
        tap = RecordingTap()
        run_agent(tap)
        model_end = tap.events[2]
        self.assertEqual(model_end.status, "ok")
        self.assertEqual(model_end.agent_id, "agent-spec")
        self.assertEqual(model_end.run_id, "run-1")
        self.assertEqual(model_end.parent_id, "req-1")
        self.assertEqual(model_end.prompt_tokens, 120)
        self.assertEqual(model_end.completion_tokens, 30)
        self.assertEqual(model_end.model, "fake-1")
        agent_end = tap.events[3]
        self.assertEqual(agent_end.status, "ok")
        self.assertEqual(agent_end.span_id, "req-1")

    def test_gateway_error_marks_both_pulses_as_errors(self) -> None:
        tap = RecordingTap()
        result = run_agent(tap, FailingGateway())
        self.assertEqual(result.status, "FAILED")
        model_end = tap.events[2]
        self.assertEqual(model_end.status, "error")
        self.assertEqual(model_end.error_code, "LLM_TIMEOUT")
        self.assertEqual(tap.events[3].status, "error")
        self.assertEqual(tap.events[3].error_code, "LLM_TIMEOUT")

    def test_provider_block_marks_the_model_pulse_blocked(self) -> None:
        tap = RecordingTap()
        result = run_agent(tap, ReplyGateway(finish_reason="SAFETY"))
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(tap.events[2].status, "blocked")

    def test_request_without_a_run_id_emits_nothing(self) -> None:
        tap = RecordingTap()
        set_default_map_tap(tap)
        try:
            runtime = AgentRuntime(models=ReplyGateway(), clock=StepClock(), new_id=CounterId())
            request = make_request()
            request = request.model_copy(update={"metadata": {"attempt": 1}})
            result = ModelAgent(runtime).execute(request)
        finally:
            set_default_map_tap(None)
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(tap.events, [])


if __name__ == "__main__":
    unittest.main()
