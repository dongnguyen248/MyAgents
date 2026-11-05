from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.contracts.models import (
    AgentMetadata,
    AgentRequest,
    Artifact,
)
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from tests.unit.contract_models import validator_for

T_AWARE = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)
T_NAIVE = datetime(2026, 10, 20, 14, 0, 0)


class CountingClock:
    def __init__(self, start_time: datetime, step: timedelta = timedelta(seconds=1)) -> None:
        self.current = start_time
        self.step = step
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        t = self.current
        self.current = self.current + self.step
        return t


class CounterId:
    def __init__(self, prefix: str = "id-") -> None:
        self.count = 0
        self.prefix = prefix

    def __call__(self) -> str:
        self.count += 1
        return f"{self.prefix}{self.count}"


def make_request(metadata: dict[str, Any] | None = None) -> AgentRequest:
    return AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="test-agent",
        input={"requirement": "Test requirement"},
        context={"project": {"name": "sample"}},
        artifacts=[],
        metadata=metadata if metadata is not None else {"attempt": 1},
    )


class DummyAgent(BaseAgent):
    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        metadata: AgentMetadata | None = None,
        issues: list[Issue] | None = None,
        run_behavior: Any = None,
        revision_count: int = 0,
    ) -> None:
        super().__init__(runtime)
        self._metadata = metadata or AgentMetadata(
            id="test-agent",
            name="Test Agent",
            type="test",
            version="1.0.0",
            status="IDLE",
            capabilities=["testing"],
            configuration={},
        )
        self._issues = issues or []
        self._run_behavior = run_behavior
        self._revision_count = revision_count
        self.run_called = False

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    def _check(self, request: AgentRequest) -> list[Issue]:
        return list(self._issues)

    def _run(self, request: AgentRequest) -> tuple[Any, list[Artifact]]:
        self.run_called = True
        if isinstance(self._run_behavior, Exception):
            raise self._run_behavior
        if callable(self._run_behavior):
            return self._run_behavior(request)
        return ({"summary": "dummy ok"}, [])

    def _compute_revision_count(self, request: AgentRequest) -> int:
        return self._revision_count


class AgentBaseTests(unittest.TestCase):
    def test_clock_called_counts(self):
        # SUCCESS: clock called exactly twice
        clock = CountingClock(T_AWARE)
        runtime = AgentRuntime(models=ScriptedModelGateway([]), clock=clock, new_id=CounterId())
        agent = DummyAgent(runtime)
        res = agent.execute(make_request())
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(clock.calls, 2)

        # REJECTED: clock called exactly twice
        clock_rej = CountingClock(T_AWARE)
        runtime_rej = AgentRuntime(
            models=ScriptedModelGateway([]), clock=clock_rej, new_id=CounterId()
        )
        agent_rej = DummyAgent(runtime_rej, issues=[Issue("input.req", "Invalid")])
        res_rej = agent_rej.execute(make_request())
        self.assertEqual(res_rej.status, "REJECTED")
        self.assertEqual(clock_rej.calls, 2)

        # FAILED (ModelGatewayError): clock called exactly twice
        clock_gw = CountingClock(T_AWARE)
        runtime_gw = AgentRuntime(
            models=ScriptedModelGateway([]), clock=clock_gw, new_id=CounterId()
        )
        agent_gw = DummyAgent(runtime_gw, run_behavior=ModelGatewayError("LLM_TIMEOUT", "Timeout"))
        res_gw = agent_gw.execute(make_request())
        self.assertEqual(res_gw.status, "FAILED")
        self.assertEqual(clock_gw.calls, 2)

        # FAILED (Exception): clock called exactly twice
        clock_exc = CountingClock(T_AWARE)
        runtime_exc = AgentRuntime(
            models=ScriptedModelGateway([]), clock=clock_exc, new_id=CounterId()
        )
        agent_exc = DummyAgent(runtime_exc, run_behavior=RuntimeError("boom"))
        res_exc = agent_exc.execute(make_request())
        self.assertEqual(res_exc.status, "FAILED")
        self.assertEqual(clock_exc.calls, 2)

        # validate (valid): clock called 0 times
        clock_val_ok = CountingClock(T_AWARE)
        runtime_val_ok = AgentRuntime(
            models=ScriptedModelGateway([]), clock=clock_val_ok, new_id=CounterId()
        )
        val_res_ok = DummyAgent(runtime_val_ok).validate(make_request())
        self.assertTrue(val_res_ok.valid)
        self.assertEqual(clock_val_ok.calls, 0)

        # validate (with issues): clock called exactly 1 time
        clock_val_err = CountingClock(T_AWARE)
        runtime_val_err = AgentRuntime(
            models=ScriptedModelGateway([]), clock=clock_val_err, new_id=CounterId()
        )
        val_res_err = DummyAgent(runtime_val_err, issues=[Issue("input", "bad")]).validate(
            make_request()
        )
        self.assertFalse(val_res_err.valid)
        self.assertEqual(clock_val_err.calls, 1)

    def test_rejected_when_check_returns_issues(self):
        clock = CountingClock(T_AWARE)
        runtime = AgentRuntime(models=ScriptedModelGateway([]), clock=clock, new_id=CounterId())
        issues = [Issue("input.requirement", "Required field missing")]
        agent = DummyAgent(runtime, issues=issues)
        req = make_request()

        res = agent.execute(req)
        self.assertFalse(agent.run_called)
        self.assertEqual(res.status, "REJECTED")
        self.assertIsNone(res.output)
        self.assertEqual(res.artifacts, [])
        self.assertEqual(res.events, [])
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(res.errors[0].code, "VALIDATION_FAILED")
        self.assertEqual(res.errors[0].category, "VALIDATION")
        self.assertEqual(res.errors[0].details, {"path": "input.requirement"})
        self.assertFalse(res.errors[0].retryable)

        validator_for("AgentResult").validate(res.to_contract())

    def test_success_events_and_id_assignment_order(self):
        new_id = CounterId("gen-")
        clock = CountingClock(T_AWARE, step=timedelta(seconds=2))
        runtime = AgentRuntime(models=ScriptedModelGateway([]), clock=clock, new_id=new_id)

        def make_artifacts(req: AgentRequest) -> tuple[Any, list[Artifact]]:
            # Call new_id inside _run for artifacts
            art1 = Artifact(
                id=runtime.new_id(),  # gen-1
                type="SPEC",
                name="SPEC.md",
                version="1",
                content={"text": "spec 1"},
                created_by="test-agent",
                created_at=T_AWARE,
            )
            art2 = Artifact(
                id=runtime.new_id(),  # gen-2
                type="SPEC",
                name="SPEC.md",
                version="2",
                content={"text": "spec 2"},
                created_by="test-agent",
                created_at=T_AWARE,
            )
            return ({"summary": "created"}, [art1, art2])

        agent = DummyAgent(runtime, run_behavior=make_artifacts)
        req = make_request()
        res = agent.execute(req)

        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.artifacts[0].id, "gen-1")
        self.assertEqual(res.artifacts[1].id, "gen-2")

        # Events emitted in exact order: AGENT_STARTED, ARTIFACT_CREATED x2, AGENT_COMPLETED
        event_types = [e.event_type for e in res.events]
        self.assertEqual(
            event_types,
            ["AGENT_STARTED", "ARTIFACT_CREATED", "ARTIFACT_CREATED", "AGENT_COMPLETED"],
        )

        # Ids assigned in sequence: gen-3, gen-4, gen-5, gen-6
        event_ids = [e.id for e in res.events]
        self.assertEqual(event_ids, ["gen-3", "gen-4", "gen-5", "gen-6"])

        # Check event timestamps
        self.assertEqual(res.events[0].timestamp, T_AWARE)  # t_start
        self.assertEqual(res.events[1].timestamp, T_AWARE + timedelta(seconds=2))  # t_end
        self.assertEqual(res.events[2].timestamp, T_AWARE + timedelta(seconds=2))  # t_end
        self.assertEqual(res.events[3].timestamp, T_AWARE + timedelta(seconds=2))  # t_end

        validator_for("AgentResult").validate(res.to_contract())

    def test_model_gateway_error_results_in_failed(self):
        clock = CountingClock(T_AWARE)
        runtime = AgentRuntime(models=ScriptedModelGateway([]), clock=clock, new_id=CounterId())
        gw_err = ModelGatewayError("LLM_RATE_LIMITED", "Throttled", details={"retryAfter": 10})
        agent = DummyAgent(runtime, run_behavior=gw_err)
        req = make_request()

        res = agent.execute(req)
        self.assertEqual(res.status, "FAILED")
        self.assertIsNone(res.output)
        self.assertEqual(res.artifacts, [])
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(res.errors[0].code, "LLM_RATE_LIMITED")
        self.assertEqual(res.errors[0].category, "LLM")
        self.assertTrue(res.errors[0].retryable)
        self.assertEqual(res.errors[0].details, {"retryAfter": 10})

        event_types = [e.event_type for e in res.events]
        self.assertEqual(event_types, ["AGENT_STARTED", "AGENT_FAILED"])

        validator_for("AgentResult").validate(res.to_contract())

    def test_failure_is_logged_with_code_and_details(self):
        clock = CountingClock(T_AWARE)
        runtime = AgentRuntime(models=ScriptedModelGateway([]), clock=clock, new_id=CounterId())
        gw_err = ModelGatewayError("LLM_RATE_LIMITED", "Throttled", details={"retryAfter": 10})
        agent = DummyAgent(runtime, run_behavior=gw_err)
        with self.assertLogs("asf.agents.base", level="WARNING") as logs:
            agent.execute(make_request())
        text = "\n".join(logs.output)
        self.assertIn("test-agent", text)
        self.assertIn("LLM_RATE_LIMITED", text)
        self.assertIn("retryAfter", text)

    def test_unexpected_exception_redacts_details(self):
        clock = CountingClock(T_AWARE)
        runtime = AgentRuntime(models=ScriptedModelGateway([]), clock=clock, new_id=CounterId())
        agent = DummyAgent(runtime, run_behavior=RuntimeError("SECRET_TOKEN_12345"))
        req = make_request()

        res = agent.execute(req)
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(len(res.errors), 1)
        err = res.errors[0]
        self.assertEqual(err.code, "AGENT_EXECUTION_FAILED")
        self.assertEqual(err.category, "AGENT")
        self.assertTrue(err.retryable)
        self.assertEqual(err.message, "Agent execution failed")
        # Details must contain ONLY exceptionType
        self.assertEqual(err.details, {"exceptionType": "RuntimeError"})

        # Sentinel must NEVER appear in the entire serialized result
        dumped = json.dumps(res.to_contract())
        self.assertNotIn("SECRET_TOKEN_12345", dumped)

        validator_for("AgentResult").validate(res.to_contract())

    def test_metrics_duration_and_backwards_clock(self):
        # Normal duration
        clock = CountingClock(T_AWARE, step=timedelta(seconds=5))
        runtime = AgentRuntime(models=ScriptedModelGateway([]), clock=clock, new_id=CounterId())
        res = DummyAgent(runtime).execute(make_request())
        self.assertEqual(res.metrics.duration_seconds, 5.0)

        # Backwards clock -> duration clamped to 0.0
        backwards_clock = CountingClock(T_AWARE, step=timedelta(seconds=-10))
        runtime_backwards = AgentRuntime(
            models=ScriptedModelGateway([]), clock=backwards_clock, new_id=CounterId()
        )
        res_backwards = DummyAgent(runtime_backwards).execute(make_request())
        self.assertEqual(res_backwards.metrics.duration_seconds, 0.0)

    def test_metrics_attempt_parsing_and_revision_count(self):
        cases = [
            ({"attempt": 3}, 3),  # valid int >= 1
            ({}, 1),  # missing
            ({"attempt": 0}, 1),  # 0 -> 1
            ({"attempt": -2}, 1),  # negative -> 1
            ({"attempt": True}, 1),  # bool -> 1
            ({"attempt": False}, 1),  # bool -> 1
            ({"attempt": "2"}, 1),  # string -> 1
        ]
        for meta, expected_attempt in cases:
            with self.subTest(meta=meta):
                runtime = AgentRuntime(
                    models=ScriptedModelGateway([]),
                    clock=CountingClock(T_AWARE),
                    new_id=CounterId(),
                )
                agent = DummyAgent(runtime, revision_count=7)
                res = agent.execute(make_request(metadata=meta))
                self.assertEqual(res.metrics.attempt, expected_attempt)
                self.assertEqual(res.metrics.revision_count, 7)

    def test_validate_never_raises_and_returns_structured_errors(self):
        runtime = AgentRuntime(
            models=ScriptedModelGateway([]), clock=CountingClock(T_AWARE), new_id=CounterId()
        )
        agent = DummyAgent(
            runtime,
            issues=[
                Issue("input.field1", "Field 1 error"),
                Issue("input.field2", "Field 2 error"),
            ],
        )
        val = agent.validate(make_request())
        self.assertFalse(val.valid)
        self.assertEqual(len(val.errors), 2)
        self.assertEqual(val.errors[0].code, "VALIDATION_FAILED")
        self.assertEqual(val.errors[0].details, {"path": "input.field1"})
        self.assertEqual(val.errors[1].details, {"path": "input.field2"})
        validator_for("ValidationResult").validate(val.to_contract())

    def test_naive_clock_raises_value_error(self):
        def naive_clock() -> datetime:
            return T_NAIVE

        runtime = AgentRuntime(
            models=ScriptedModelGateway([]), clock=naive_clock, new_id=CounterId()
        )
        agent = DummyAgent(runtime)
        with self.assertRaises(ValueError):
            agent.execute(make_request())

    def test_inputs_are_not_mutated(self):
        runtime = AgentRuntime(
            models=ScriptedModelGateway([]), clock=CountingClock(T_AWARE), new_id=CounterId()
        )
        agent = DummyAgent(runtime)
        req = make_request()
        req_copy = copy.deepcopy(req)

        agent.validate(req)
        self.assertEqual(req, req_copy)

        agent.execute(req)
        self.assertEqual(req, req_copy)

    def test_get_metadata_validates(self):
        runtime = AgentRuntime(
            models=ScriptedModelGateway([]), clock=CountingClock(T_AWARE), new_id=CounterId()
        )
        agent = DummyAgent(runtime)
        meta = agent.get_metadata()
        self.assertEqual(meta.id, "test-agent")
        self.assertEqual(meta.status, "IDLE")
        validator_for("AgentMetadata").validate(meta.to_contract())
