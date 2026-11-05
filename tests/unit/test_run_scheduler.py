"""RunScheduler + the service wiring that unsticks scheduled retries.

Unit tests drive the scheduler with a fake clock: moving the clock
and calling notify() must fire a run exactly once, at its retry_at,
and never before. The service test is the regression for the original
bug: a run parked in WAITING by a retryable failure used to sit there
until someone ticked it by hand — now it resumes on its own when the
backoff expires.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
from pydantic import ValidationError

from asf.agents.base import AgentRuntime
from asf.agents.plan.factory import build_plan_agent
from asf.agents.spec.factory import build_spec_agent
from asf.api.scheduler import RunScheduler
from asf.api.service import FactoryService
from asf.approval.models import ApprovalPolicy
from asf.approval.service import ApprovalService
from asf.configuration.platform import PlatformConfig, RetryPolicySettings
from asf.models.errors import ModelGatewayError
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.storage.memory import InMemoryApprovalRepository
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
from tests.unit.test_api_service import PROJECTS, TEMPLATES, RoutingGateway

START = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _wait_until(predicate, timeout: float = 5.0) -> bool:  # noqa: ANN001, ANN202
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# -- RunScheduler unit behaviour ---------------------------------------


def _scheduler(clock: FakeClock, wakes: list[str]) -> RunScheduler:
    scheduler = RunScheduler(clock=clock, wake=wakes.append)
    scheduler.start()
    return scheduler


def test_scheduler_fires_exactly_once_when_due():
    clock = FakeClock()
    wakes: list[str] = []
    scheduler = _scheduler(clock, wakes)
    try:
        scheduler.register("run-1", START + timedelta(seconds=30))
        clock.advance(29)
        scheduler.notify()
        assert not _wait_until(lambda: wakes, timeout=0.3)
        clock.advance(1)
        scheduler.notify()
        assert _wait_until(lambda: wakes == ["run-1"])
        # Further clock movement / notifications must not re-fire it.
        clock.advance(3600)
        scheduler.notify()
        time.sleep(0.1)
        assert wakes == ["run-1"]
        assert scheduler.registered() == {}
    finally:
        scheduler.stop()


def test_scheduler_reschedule_replaces_the_earlier_time():
    clock = FakeClock()
    wakes: list[str] = []
    scheduler = _scheduler(clock, wakes)
    try:
        scheduler.register("run-1", START + timedelta(seconds=600))
        scheduler.register("run-1", START + timedelta(seconds=10))
        clock.advance(10)
        scheduler.notify()
        assert _wait_until(lambda: wakes == ["run-1"])
        clock.advance(600)
        scheduler.notify()
        time.sleep(0.1)
        assert wakes == ["run-1"]  # the stale 600s entry never fires
    finally:
        scheduler.stop()


def test_scheduler_unregister_prevents_firing():
    clock = FakeClock()
    wakes: list[str] = []
    scheduler = _scheduler(clock, wakes)
    try:
        scheduler.register("run-1", START + timedelta(seconds=5))
        scheduler.unregister("run-1")
        clock.advance(60)
        scheduler.notify()
        time.sleep(0.1)
        assert wakes == []
    finally:
        scheduler.stop()


def test_scheduler_fires_multiple_runs_in_due_order():
    clock = FakeClock()
    wakes: list[str] = []
    scheduler = _scheduler(clock, wakes)
    try:
        scheduler.register("late", START + timedelta(seconds=50))
        scheduler.register("early", START + timedelta(seconds=10))
        clock.advance(60)
        scheduler.notify()
        assert _wait_until(lambda: len(wakes) == 2)
        assert wakes == ["early", "late"]
    finally:
        scheduler.stop()


def test_scheduler_stop_is_clean_and_idempotent():
    clock = FakeClock()
    scheduler = RunScheduler(clock=clock, wake=lambda _run_id: None)
    scheduler.start()
    scheduler.stop()
    scheduler.stop()
    assert scheduler._thread is None


# -- config validation (requirement: unknown retryOn codes rejected) --


def test_retry_on_rejects_unknown_codes_with_the_valid_list():
    with pytest.raises(ValidationError) as caught:
        RetryPolicySettings(max_attempts=2, retry_on=["TIMEOUT", "RATE_LIMITED"])
    message = str(caught.value)
    assert "TIMEOUT" in message
    assert "LLM_TIMEOUT" in message  # the valid codes are listed


def test_retry_on_accepts_gateway_and_agent_codes():
    policy = RetryPolicySettings(
        max_attempts=2,
        retry_on=[
            "LLM_TIMEOUT",
            "LLM_RATE_LIMITED",
            "COMMAND_TIMEOUT",
            "SANDBOX_ERROR",
            "INTEGRATION_UNAVAILABLE",
        ],
    )
    assert policy.retry_on[0] == "LLM_TIMEOUT"


# -- the WAITING run resumes by itself (bug A, end to end) -------------


class _FlakyGateway:
    """Fails the first model call with a retryable timeout, then routes."""

    def __init__(self) -> None:
        self._inner = RoutingGateway()
        self.calls = 0

    def complete(self, request):  # noqa: ANN001, ANN202
        self.calls += 1
        if self.calls == 1:
            raise ModelGatewayError("LLM_TIMEOUT", "provider stalled")
        return self._inner.complete(request)


def _service_with_flaky_gateway(clock: FakeClock):  # noqa: ANN202
    ids = count(1)

    def new_id() -> str:
        return f"id-{next(ids)}"

    gateway = _FlakyGateway()
    runtime = AgentRuntime(models=gateway, clock=clock, new_id=new_id)
    registry = AgentRegistry()
    registry.register(build_spec_agent(runtime, PlatformConfig(), TEMPLATES))
    registry.register(build_plan_agent(runtime, PlatformConfig(), TEMPLATES))
    definition = WorkflowDefinition(
        id="spec-plan",
        name="Spec and Plan",
        version="1",
        steps=[
            WorkflowStepDef(
                id="spec",
                name="Spec",
                type="AGENT",
                stage="SPEC",
                agent_type="spec",
                requires_approval=True,
                produces=["SPEC"],
                retry_policy=RetryPolicySettings(
                    max_attempts=2,
                    backoff_seconds=30,
                    retry_on=["LLM_TIMEOUT"],
                ),
            ),
            WorkflowStepDef(
                id="plan",
                name="Plan",
                type="AGENT",
                stage="PLAN",
                agent_type="plan",
                requires_approval=True,
                consumes=["SPEC"],
                produces=["PLAN"],
            ),
        ],
    )
    engine = Orchestrator(
        definition,
        registry,
        clock=clock,
        new_id=new_id,
        approval_policy=ApprovalPolicy(reviewers=["dashboard"]),
        approvals=ApprovalService(InMemoryApprovalRepository(), id_factory=new_id),
    )
    service = FactoryService(
        engine,
        projects=PROJECTS,
        metrics=None,
        clock=clock,
    )
    return service, engine, gateway


def test_waiting_run_resumes_by_itself_after_retry_at():
    clock = FakeClock()
    service, engine, gateway = _service_with_flaky_gateway(clock)
    try:
        run = service.start_run(
            "task-retry",
            "proj-1",
            inputs={"spec": {"requirement": "Build a calculator"}},
        )
        # The background drive runs the spec step, the gateway times
        # out, and the run parks in WAITING with a scheduled retry.
        assert _wait_until(lambda: engine.get(run.id).retry_at is not None)
        parked = engine.get(run.id)
        assert parked.retry_at == START + timedelta(seconds=30)
        assert gateway.calls == 1
        assert service._scheduler.registered().get(run.id) == parked.retry_at

        # Nobody ticks anything. Time passes; the scheduler wakes the
        # run, the retry succeeds, and the run reaches its approval
        # gate on its own.
        clock.advance(31)
        service._scheduler.notify()
        assert _wait_until(
            lambda: service.get_workflow(run.id)["status"] == "WAITING_APPROVAL",
        )
        assert gateway.calls == 2
        assert engine.get(run.id).retry_at is None
    finally:
        service.stop_scheduler()
        service.wait_for_drives(timeout=5)
