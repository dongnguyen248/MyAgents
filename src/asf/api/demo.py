"""Runnable dashboard-backend demo assembly.

    .venv/bin/python -m asf.api.demo --port 8000        # serve the REST/SSE API
    .venv/bin/python -m asf.api.demo --selftest         # headless end-to-end run

All seven real agents are registered with one deterministic routing
``ScriptedModelGateway``: replies are chosen per agent from the system
prompt and use the exact canned SPEC/PLAN/TASK/CODE/CODE_REVIEW formats the
agents' own tests use. The TestAgent is deterministic and runs against a
scripted sandbox. This demonstrates wiring, not real LLM reasoning.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

import asf
from asf.agents.base import AgentRuntime
from asf.agents.fix.factory import build_fix_agent
from asf.agents.implement.factory import build_implement_agent
from asf.agents.loading import load_plan_template, load_spec_template
from asf.agents.plan.factory import build_plan_agent
from asf.agents.review.factory import build_review_agent
from asf.agents.spec.factory import build_spec_agent
from asf.agents.task.factory import build_task_agent
from asf.agents.test.factory import build_test_agent
from asf.api.app import create_app
from asf.api.service import FactoryService
from asf.approval.models import ApprovalPolicy
from asf.configuration.loader import load_platform_config, load_projects
from asf.configuration.project import ProjectProfile
from asf.configuration.yamlio import scan_secrets
from asf.contracts.models import (
    ActivityEvent,
    AgentRequest,
    AgentResult,
    ModelRequest,
    ModelResponse,
    RunMetrics,
)
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.storage.sqlite import SQLiteExecutionStore
from asf.tools.fake import InMemoryRepository, ScriptedSandbox
from asf.workflow.loader import load_workflow

_TASK_REPLY = json.dumps({
    "tasks": [{
        "id": "T1",
        "title": "Create the demo module",
        "milestoneRef": "M1",
        "description": "Implement the demo module described by the SPEC",
        "acceptanceCriteria": ["The demo module exists and imports cleanly"],
        "dependsOn": [],
        "expectedFiles": ["calculator.py"],
        "verificationHint": "Run the project test commands",
    }],
}, indent=2)

_CODE_REPLY = json.dumps({
    "changes": [{
        "path": "calculator.py",
        "operation": "create",
        "content": "def add(a, b):\n    return a + b\n",
    }],
}, indent=2)

_REVIEW_REPLY = '{"findings": [], "verdict": "APPROVE"}'


class DemoRoutingGateway:
    """Deterministic per-agent replies over one ScriptedModelGateway."""

    def __init__(self, templates_dir: Path) -> None:
        self._templates_dir = templates_dir
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        system = request.messages[0].content
        user = request.messages[-1].content
        if "senior business analyst" in system:
            reply = self._spec_reply(user)
        elif "senior software architect" in system:
            reply = self._plan_reply(user)
        elif "breaking down implementation plans" in system:
            reply = _TASK_REPLY
        elif "implementing code changes" in system:
            reply = _CODE_REPLY
        elif "You review exactly one task" in system:
            reply = _REVIEW_REPLY
        elif "You fix one task item" in system:
            reply = _CODE_REPLY
        else:  # pragma: no cover - defensive: every demo agent is routed above
            raise RuntimeError(f"No demo reply routed for system prompt: {system[:60]}")
        return ScriptedModelGateway([reply]).complete(request)

    def _spec_reply(self, user: str) -> str:
        template = load_spec_template(self._templates_dir)
        revised = "## Reviewer feedback" in user
        body = "Revised demo specification." if revised else "Initial demo specification."
        return "# SPEC: Demo\n\n" + "\n\n".join(
            f"{heading}\n{body}" for heading in template.required_sections
        )

    def _plan_reply(self, user: str) -> str:
        template = load_plan_template(self._templates_dir)
        linked = re.search(r"## Linked SPEC\nID: ([^\n]+)\nVersion: ([^\n]+)", user)
        linked_text = (
            f"ID: {linked[1]}\nVersion: {linked[2]}" if linked else "ID: unknown\nVersion: 1"
        )
        sections = {
            "## Linked SPEC": linked_text,
            "## Milestones": (
                "### M1: Demonstrate the approved SPEC handoff\n"
                "- Deliverables: Demo PLAN\n"
                "- Acceptance criteria: PLAN uses the approved SPEC\n"
                "- Depends on: none"
            ),
        }
        return "# PLAN: Demo\n\n" + "\n\n".join(
            f"{heading}\n{sections.get(heading, 'Deterministic demo plan content.')}"
            for heading in template.required_sections
        )


class _FallbackMetrics:
    """Minimal in-memory metrics recorder used until asf.evaluation lands."""

    def __init__(self) -> None:
        self._results: list[AgentResult] = []
        self._events: list[ActivityEvent] = []
        self._decisions: list[dict[str, Any]] = []

    def record(self, agent_id: str, result: AgentResult) -> None:
        self._results.append(result)

    def publish(self, event: ActivityEvent) -> None:
        self._events.append(event)

    def agent_metrics(self, agent_id: str) -> dict[str, Any]:
        own = [result for result in self._results if result.agent_id == agent_id]
        completed = sum(result.status == "SUCCESS" for result in own)
        failed = sum(result.status in ("FAILED", "REJECTED") for result in own)
        cancelled = sum(result.status == "CANCELLED" for result in own)
        total = len(own)
        durations = [result.metrics.duration_seconds for result in own]
        return {
            "total": total, "completed": completed,
            "running": total - completed - failed - cancelled,
            "failed": failed, "cancelled": cancelled,
            "successRate": completed / total if total else 0.0,
            "avgDurationSec": sum(durations) / total if total else 0.0,
            "avgRevisions": 0.0, "humanApprovalRate": 0.0,
            "testPassRate": 0.0, "ciPassRate": 0.0,
        }

    def overview(self) -> dict[str, Any]:
        return {
            "daily": [],
            "human": {
                "approvalRate": 0.0, "rejectionRate": 0.0, "avgRevisions": 0.0,
                "avgApprovalMinutes": 0.0, "daily": [],
            },
            "quality": {
                "codeReviewRejectionRate": 0.0, "testPassRate": 0.0,
                "ciPassRate": 0.0, "reworkRate": 0.0, "daily": [],
            },
            "agents": [],
        }

    def events(self) -> list[ActivityEvent]:
        return list(self._events)

    def project_outcomes(self, project_id: str) -> dict[str, Any]:
        return {}

    def record_approval_decision(self, **kwargs: Any) -> None:
        self._decisions.append(kwargs)


def _load_metrics() -> Any:
    """Use asf.evaluation's service when importable; otherwise the fallback."""
    for module_name in ("asf.evaluation", "asf.evaluation.service", "asf.evaluation.metrics"):
        try:
            module = importlib.import_module(module_name)
        except Exception:  # nosec B112
            continue
        for class_name in ("MetricsService", "EvaluationService"):
            cls = getattr(module, class_name, None)
            if cls is None:
                continue
            instance = None
            for kwargs in ({"clock": lambda: datetime.now(timezone.utc)}, {}):
                try:
                    instance = cls(**kwargs)
                    break
                except Exception:  # nosec B112
                    continue
            if instance is None:
                continue
            if all(
                hasattr(instance, name)
                for name in ("agent_metrics", "overview", "events", "project_outcomes")
            ):
                return instance
    return _FallbackMetrics()


def _action_ok(request: AgentRequest) -> AgentResult:
    """Successful no-artifact result for the workflow's CI / merge actions."""
    return AgentResult(
        request_id=request.request_id, agent_id=request.agent_id, status="SUCCESS",
        output={}, artifacts=[], events=[],
        metrics=RunMetrics(duration_seconds=0.0, revision_count=0, attempt=1),
    )


class DemoFactoryService(FactoryService):
    """FactoryService with demo-scenario defaults for HTTP-started runs.

    The scripted demo has exactly one task item (``T1``) on ref ``main`` and a
    deterministic test command, so a caller that starts a run over HTTP with
    only a requirement still gets a runnable workflow. Caller-supplied inputs
    and context always win; real deployments supply these values from the
    project/task data instead of relying on these defaults.
    """

    _STEP_DEFAULTS: dict[str, dict[str, Any]] = {
        "implement": {"taskItemId": "T1", "ref": "main"},
        "review": {"taskItemId": "T1", "ref": "main"},
        "test": {"taskItemId": "T1", "ref": "main"},
    }

    def start_run(
        self,
        task_id: str,
        project_id: str,
        inputs: Any = None,
        context: Any = None,
    ) -> Any:
        merged_inputs: dict[str, Any] = {
            step: dict(values) for step, values in self._STEP_DEFAULTS.items()
        }
        for step, values in dict(inputs or {}).items():
            merged_inputs[step] = {**merged_inputs.get(step, {}), **dict(values)}
        merged_context: dict[str, Any] = {
            "project": {"testCommands": [["python", "-m", "pytest", "-q"]]},
        }
        for key, value in dict(context or {}).items():
            if key == "project" and isinstance(value, dict):
                merged_context["project"] = {**merged_context["project"], **value}
            else:
                merged_context[key] = value
        return super().start_run(
            task_id, project_id, inputs=merged_inputs, context=merged_context,
        )


def _project_writer(projects_dir: Path) -> Callable[[ProjectProfile], None]:
    """Persist dashboard-created projects as ``projects/<id>.yaml``.

    The written file is a regular project profile: it goes through the same
    secret scan as hand-written files (literal secrets are rejected; use
    ``{env: VAR}`` references), and the loader picks it up on the next start
    because its stem equals the profile id.
    """

    def write(profile: ProjectProfile) -> None:
        data = profile.to_contract()
        if scan_secrets(data):
            raise ValueError(
                "Project profile contains literal secrets; "
                "use {env: VAR} references instead",
            )
        path = projects_dir / f"{profile.id}.yaml"
        if path.exists():
            raise ValueError(f"Project file already exists: {path.name}")
        path.write_text(
            yaml.safe_dump(data, sort_keys=False), encoding="utf-8",
        )

    return write


def build_demo(
    db_path: Path,
) -> tuple[FactoryService, Orchestrator, SQLiteExecutionStore]:
    """Assemble store, engine (all seven agents), and dashboard service."""
    root = Path(asf.__file__).resolve().parents[2]
    templates_dir = root / "templates"
    platform = load_platform_config(root / "config")
    projects_dir = root / "projects"
    projects = load_projects(projects_dir)
    definition = load_workflow(root / "workflows" / "software-development.yaml")

    def clock() -> datetime:
        return datetime.now(timezone.utc)

    def new_id() -> str:
        return str(uuid4())

    runtime = AgentRuntime(
        models=DemoRoutingGateway(templates_dir), clock=clock, new_id=new_id,
    )
    repository = InMemoryRepository()
    registry = AgentRegistry()
    registry.register(build_spec_agent(runtime, platform, templates_dir))
    registry.register(build_plan_agent(runtime, platform, templates_dir))
    registry.register(build_task_agent(runtime, platform, templates_dir))
    registry.register(build_implement_agent(runtime, platform, templates_dir, repository))
    registry.register(build_review_agent(runtime, platform, templates_dir))
    registry.register(build_test_agent(runtime, platform, templates_dir, ScriptedSandbox()))
    registry.register(build_fix_agent(runtime, platform, templates_dir, repository))

    store = SQLiteExecutionStore(db_path)
    metrics = _load_metrics()
    engine = Orchestrator(
        definition, registry, clock=clock, new_id=new_id, store=store,
        approval_policy=ApprovalPolicy(reviewers=["dashboard"]),
        actions={"run-pipeline": _action_ok, "await-merge": _action_ok},
        events=metrics if hasattr(metrics, "publish") else None,
        metrics=metrics if hasattr(metrics, "record") else None,
    )
    service = DemoFactoryService(
        engine, projects=projects, metrics=metrics, store=store,
        reviewer="dashboard", clock=clock,
        on_project_created=_project_writer(projects_dir),
    )
    return service, engine, store


def run_selftest(service: FactoryService, engine: Orchestrator) -> int:
    """Drive one run to completion, approving every artifact as 'dashboard'."""
    project_id = service.list_projects()[0]["id"]
    run = service.start_run(
        "demo-task", project_id,
        inputs={
            "spec": {"requirement": "Demonstrate the dashboard backend end to end"},
            "implement": {"taskItemId": "T1", "ref": "main"},
            "review": {"taskItemId": "T1", "ref": "main"},
            "test": {"taskItemId": "T1", "ref": "main"},
        },
        context={"project": {"testCommands": [["python", "-m", "pytest", "-q"]]}},
    )
    for _ in range(100):
        run = engine.get(run.id)
        print(f"stage: {run.state.stage}")
        if run.state.stage in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        if run.approval_id is not None:
            pending = engine.pending_approval(run.id)
            service.decide_approval(pending.id, decision="APPROVE")
        else:
            service.tick_run(run.id)
    run = engine.get(run.id)
    artifact_types = {artifact.type for artifact in run.artifact_history.values()}
    missing = {"SPEC", "PLAN", "TASK", "CODE"} - artifact_types
    if run.state.stage != "COMPLETED" or missing:
        print(f"SELFTEST FAILED: stage={run.state.stage} missing={sorted(missing)}")
        for error in run.errors:
            print(f"error: {error.code}: {error.message}")
        return 1
    print(f"SELFTEST OK - final stage: {run.state.stage}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=None, help="SQLite store path")
    parser.add_argument(
        "--selftest", action="store_true",
        help="Run one headless end-to-end run instead of serving HTTP",
    )
    args = parser.parse_args()
    db_path = args.db or Path(tempfile.mkdtemp(prefix="asf-api-demo-")) / "demo.sqlite"
    service, engine, store = build_demo(db_path)
    try:
        if args.selftest:
            raise SystemExit(run_selftest(service, engine))
        import uvicorn

        print(f"Dashboard API on http://127.0.0.1:{args.port} (db: {db_path})")
        print("Dashboard: set VITE_API_BASE_URL to that URL and run the frontend dev server.")
        uvicorn.run(create_app(service), host="127.0.0.1", port=args.port)
    finally:
        store.close()


if __name__ == "__main__":
    main()
