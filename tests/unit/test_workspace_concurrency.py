"""Concurrency safety: workspace binding isolation, per-project
locks, the bounded drive pool, and the model-call limiter.

The workspace race test drives the REAL _WorkspaceBindingAgent (the
wrapper the demo assembly puts around implement/test/fix) from two
threads whose inner agent rendezvous on a barrier INSIDE execute —
with the old shared-attribute binding, the second bind overwrote the
first and both threads read/wrote one project's folder.
"""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from asf.agents.base import AgentRuntime
from asf.agents.spec.factory import build_spec_agent
from asf.api.demo import _WorkspaceBindingAgent
from asf.api.service import FactoryService
from asf.approval.models import ApprovalPolicy
from asf.approval.service import ApprovalService
from asf.configuration.platform import ExecutionConfig, PlatformConfig
from asf.contracts.models import (
    AgentRequest,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from asf.models.limited import ConcurrencyLimitedGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.storage.memory import InMemoryApprovalRepository
from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.local import LocalWorkspace, WorkspaceRepository, WorkspaceSandbox
from asf.tools.ports import CommandSpec
from tests.unit.test_api_service import PROJECTS, FakeMetrics, RoutingGateway

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
PYTHON = sys.executable


def make_request(project_id: str) -> AgentRequest:
    return AgentRequest(
        request_id=f"req-{project_id}",
        task_id="task-1",
        project_id=project_id,
        workflow_id="software-development",
        agent_id="implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={},
        artifacts=[],
        metadata={"attempt": 1},
    )


# -- 1. Cross-project binding isolation -----------------------------------


class _PortTouchingAgent:
    """Inner agent double: rendezvous inside execute, then use the
    routed repository/sandbox ports exactly like the code agents."""

    def __init__(self, repository, sandbox, barrier, seen) -> None:  # noqa: ANN001
        self._repository = repository
        self._sandbox = sandbox
        self._barrier = barrier
        self._seen = seen

    def get_metadata(self):  # noqa: ANN202
        raise NotImplementedError

    def validate(self, request):  # noqa: ANN202
        raise NotImplementedError

    def execute(self, request: AgentRequest):  # noqa: ANN202
        # Both threads are inside execute (both bindings made) before
        # either touches a port.
        self._barrier.wait(timeout=15)
        self._seen[request.project_id] = self._repository.read_file(
            "marker.txt",
            "main",
        )
        changeset = ChangeSet(
            changes=[
                FileChange(
                    path="written.txt",
                    operation="create",
                    content=f"written-by-{request.project_id}",
                )
            ]
        )
        self._sandbox.run(
            [CommandSpec(argv=(PYTHON, "-c", "pass"))],
            changeset,
            "main",
        )
        return None


def test_parallel_runs_never_touch_each_others_folders(tmp_path: Path):
    for iteration in range(50):
        dir_a = tmp_path / f"iter{iteration}" / "a"
        dir_b = tmp_path / f"iter{iteration}" / "b"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)
        (dir_a / "marker.txt").write_text("marker-A", encoding="utf-8")
        (dir_b / "marker.txt").write_text("marker-B", encoding="utf-8")
        workspace = LocalWorkspace({"proj-a": dir_a, "proj-b": dir_b})
        repository = WorkspaceRepository(workspace, fallback=None)  # type: ignore[arg-type]
        sandbox = WorkspaceSandbox(workspace, fallback=None)  # type: ignore[arg-type]
        seen: dict[str, str] = {}
        agent = _WorkspaceBindingAgent(
            _PortTouchingAgent(
                repository,
                sandbox,
                threading.Barrier(2),
                seen,
            ),
            workspace,
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(agent.execute, make_request("proj-a")),
                pool.submit(agent.execute, make_request("proj-b")),
            ]
            for future in futures:
                future.result(timeout=30)
        assert seen == {"proj-a": "marker-A", "proj-b": "marker-B"}, (
            f"iteration {iteration}: a run read the other project's files"
        )
        assert (dir_a / "written.txt").read_text(encoding="utf-8") == ("written-by-proj-a")
        assert (dir_b / "written.txt").read_text(encoding="utf-8") == ("written-by-proj-b")
        # Bindings were reset by the wrapper: the main context is clean.
        assert workspace.bound_project() is None


def test_binding_is_reset_even_when_the_agent_raises(tmp_path: Path):
    workspace = LocalWorkspace({"proj-a": tmp_path})

    class _Boom:
        def get_metadata(self):  # noqa: ANN202
            raise NotImplementedError

        def validate(self, request):  # noqa: ANN202
            raise NotImplementedError

        def execute(self, request):  # noqa: ANN202
            raise RuntimeError("agent blew up")

    agent = _WorkspaceBindingAgent(_Boom(), workspace)
    with pytest.raises(RuntimeError, match="blew up"):
        agent.execute(make_request("proj-a"))
    assert workspace.bound_project() is None


# -- 2. Same-project serialization ------------------------------------------


class _OccupancyAgent:
    """Counts how many executions are inside the agent at once."""

    def __init__(self, hold_seconds: float = 0.25) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self._hold = hold_seconds
        self.both_inside = threading.Event()

    def get_metadata(self):  # noqa: ANN202
        raise NotImplementedError

    def validate(self, request):  # noqa: ANN202
        raise NotImplementedError

    def execute(self, request):  # noqa: ANN202
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.active == 2:
                self.both_inside.set()
        # Give a wrongly-parallel second execution every chance to
        # enter; correct serialization just costs the wait.
        self.both_inside.wait(timeout=self._hold)
        with self._lock:
            self.active -= 1
        return None


def test_same_project_code_agents_never_overlap(tmp_path: Path):
    workspace = LocalWorkspace({"proj-a": tmp_path})
    occupancy = _OccupancyAgent()
    agent = _WorkspaceBindingAgent(occupancy, workspace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(agent.execute, make_request("proj-a")),
            pool.submit(agent.execute, make_request("proj-a")),
        ]
        for future in futures:
            future.result(timeout=30)
    assert occupancy.max_active == 1


def test_different_projects_still_run_in_parallel(tmp_path: Path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    workspace = LocalWorkspace({"proj-a": dir_a, "proj-b": dir_b})
    occupancy = _OccupancyAgent()
    agent = _WorkspaceBindingAgent(occupancy, workspace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(agent.execute, make_request("proj-a")),
            pool.submit(agent.execute, make_request("proj-b")),
        ]
        for future in futures:
            future.result(timeout=30)
    assert occupancy.max_active == 2  # the lock is per project, not global


# -- 3 + 5. Bounded drive pool, cancel queued/running ------------------------


def build_engine(gateway: Any) -> Orchestrator:
    ids = count(1)

    def new_id() -> str:
        return f"id-{next(ids)}"

    runtime = AgentRuntime(models=gateway, clock=lambda: NOW, new_id=new_id)
    registry = AgentRegistry()
    registry.register(build_spec_agent(runtime, PlatformConfig(), TEMPLATES))
    from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef

    definition = WorkflowDefinition(
        id="spec-only",
        name="Spec only",
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
            ),
        ],
    )
    return Orchestrator(
        definition,
        registry,
        clock=lambda: NOW,
        new_id=new_id,
        approval_policy=ApprovalPolicy(reviewers=["dashboard"]),
        approvals=ApprovalService(InMemoryApprovalRepository(), id_factory=new_id),
    )


class _CountingGateway:
    """Wraps the deterministic routing gateway, measuring overlap."""

    def __init__(self, inner: Any, delay: float = 0.4) -> None:
        self._inner = inner
        self._delay = delay
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        with self._lock:
            self.active += 1
            self.calls += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self._delay)
            return self._inner.complete(request)
        finally:
            with self._lock:
                self.active -= 1


def test_drive_pool_bounds_concurrent_runs():
    gateway = _CountingGateway(RoutingGateway())
    service = FactoryService(
        build_engine(gateway),
        projects=PROJECTS,
        metrics=FakeMetrics(),
        clock=lambda: NOW,
        max_concurrent_runs=2,
    )
    runs = [
        service.start_run(
            f"task-{index}",
            "proj-1",
            inputs={"spec": {"requirement": "Build a calculator"}},
        )
        for index in range(5)
    ]
    service.wait_for_drives(timeout=60)
    try:
        assert gateway.max_active == 2  # bounded AND actually parallel
        for run in runs:
            view = service.get_workflow(run.id)
            assert view is not None and view["status"] == "WAITING_APPROVAL"
    finally:
        service.shutdown()


def test_factory_service_defaults_to_two_concurrent_runs():
    service = FactoryService(
        build_engine(RoutingGateway()),
        projects=PROJECTS,
        metrics=FakeMetrics(),
        clock=lambda: NOW,
    )
    try:
        assert service._max_concurrent_runs == 2
    finally:
        service.shutdown()


class _BlockFirstGateway:
    """First call blocks until released; later calls answer at once."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self._lock = threading.Lock()

    def complete(self, request: ModelRequest) -> ModelResponse:
        with self._lock:
            self.calls += 1
            first = self.calls == 1
        if first:
            self.entered.set()
            self.release.wait(timeout=30)
        return self._inner.complete(request)


def test_cancel_a_run_still_queued_in_the_pool():
    gateway = _BlockFirstGateway(RoutingGateway())
    service = FactoryService(
        build_engine(gateway),
        projects=PROJECTS,
        metrics=FakeMetrics(),
        clock=lambda: NOW,
        max_concurrent_runs=1,
    )
    try:
        run_a = service.start_run(
            "task-a",
            "proj-1",
            inputs={"spec": {"requirement": "Build a calculator"}},
        )
        # The single pool worker is inside A's model call.
        assert gateway.entered.wait(timeout=15)
        run_b = service.start_run(
            "task-b",
            "proj-1",
            inputs={"spec": {"requirement": "Build a calculator"}},
        )
        # B's drive is queued behind A's. Cancelling now records a
        # cooperative request (B is "driving" — queued counts).
        view = service.cancel_run(run_b.id)
        assert view is not None and view["status"] != "CANCELLED"
        assert run_b.id in service._cancel_requested

        gateway.release.set()
        service.wait_for_drives(timeout=60)
        # A reached its gate; B was cancelled by its queued drive
        # BEFORE any dispatch — the gateway only ever served A.
        view_a = service.get_workflow(run_a.id)
        assert view_a is not None and view_a["status"] == "WAITING_APPROVAL"
        view_b = service.get_workflow(run_b.id)
        assert view_b is not None and view_b["status"] == "CANCELLED"
        assert gateway.calls == 1
    finally:
        gateway.release.set()
        service.shutdown()


def test_cancel_a_running_run_still_applies_between_steps():
    gateway = _BlockFirstGateway(RoutingGateway())
    service = FactoryService(
        build_engine(gateway),
        projects=PROJECTS,
        metrics=FakeMetrics(),
        clock=lambda: NOW,
        max_concurrent_runs=1,
    )
    try:
        run = service.start_run(
            "task-a",
            "proj-1",
            inputs={"spec": {"requirement": "Build a calculator"}},
        )
        assert gateway.entered.wait(timeout=15)
        view = service.cancel_run(run.id)
        assert view is not None and view["status"] != "CANCELLED"
        gateway.release.set()
        service.wait_for_drives(timeout=60)
        view = service.get_workflow(run.id)
        assert view is not None and view["status"] == "CANCELLED"
    finally:
        gateway.release.set()
        service.shutdown()


# -- 4. Model-call limiter ----------------------------------------------------


def _response() -> ModelResponse:
    return ModelResponse(
        content="ok",
        model="fake",
        usage=ModelUsage(prompt_tokens=1, completion_tokens=1),
        finish_reason="stop",
    )


class _SlowGateway:
    def __init__(self, delay: float = 0.15) -> None:
        self._delay = delay
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self._delay)
            return _response()
        finally:
            with self._lock:
                self.active -= 1


def _request() -> ModelRequest:
    return ModelRequest(
        model="fake",
        messages=[ModelMessage(role="user", content="hello")],
    )


def test_concurrency_limited_gateway_caps_parallel_calls():
    inner = _SlowGateway()
    gateway = ConcurrencyLimitedGateway(inner, max_concurrent=2)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(gateway.complete, _request()) for _ in range(6)]
        for future in futures:
            assert future.result(timeout=30).content == "ok"
    assert inner.max_active == 2


def test_concurrency_limited_gateway_releases_the_slot_on_error():
    class _FailOnce:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            if self.calls == 1:
                raise ModelGatewayError("LLM_TIMEOUT", "boom")
            return _response()

    gateway = ConcurrencyLimitedGateway(_FailOnce(), max_concurrent=1)
    with pytest.raises(ModelGatewayError):
        gateway.complete(_request())
    # The semaphore was released despite the exception.
    assert gateway.complete(_request()).content == "ok"
    with pytest.raises(ValueError):
        ConcurrencyLimitedGateway(_FailOnce(), max_concurrent=0)


def test_scripted_gateway_still_satisfies_the_limiter_protocol():
    gateway = ConcurrencyLimitedGateway(
        ScriptedModelGateway({}),
        max_concurrent=2,
    )
    assert gateway.max_concurrent == 2


# -- Config -------------------------------------------------------------------


def test_execution_config_defaults_and_validation():
    config = ExecutionConfig()
    assert config.max_concurrent_runs == 2
    assert config.max_concurrent_model_calls == 2
    assert PlatformConfig().execution.max_concurrent_runs == 2
    with pytest.raises(ValueError):
        ExecutionConfig(max_concurrent_runs=0)
    with pytest.raises(ValueError):
        ExecutionConfig(max_concurrent_model_calls=0)
