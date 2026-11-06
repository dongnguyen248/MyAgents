"""TaskAdapters for the Spec and Plan agents over `harness/evaluation/cases`.

Each rollout runs the real agent in-process with a recording gateway
around a gateway the caller supplies (scripted replies by default;
the harness-sensitive fake for the demo). The run directory holds
`trajectory.jsonl`, `result.json` and, when delivered,
`artifact.json`. Execution is idempotent by run id: a run directory
with a `result.json` is returned as-is and the model is not called
again.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

from asf.agents.base import AgentRuntime
from asf.agents.loading import (
    load_plan_prompts,
    load_plan_template,
    load_spec_prompts,
    load_spec_template,
)
from asf.agents.plan.agent import PlanAgent, PlanSettings
from asf.agents.spec.agent import SpecAgent, SpecSettings
from asf.contracts.models import AgentRequest, AgentResult, Artifact
from asf.models.fake import ScriptedModelGateway
from harness.evaluation.cases import BenchmarkCase, load_cases
from harness.harness2.bundle import default_tree, tree_to_components, validate_candidate
from harness.harness2.surface import Tree
from harness.harness2.trajectory import (
    RecordingGateway,
    TrajectoryRecorder,
    load_events,
    render_trajectory,
    save_events,
)

__all__ = ["PlanTaskAdapter", "SpecTaskAdapter"]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_DIR = REPO_ROOT / "harness" / "evaluation" / "cases"
DEFAULT_TEMPLATES_DIR = REPO_ROOT / "templates"
FIXTURE_SPEC_PATH = Path(__file__).resolve().parent / "fixtures" / "plan_spec_artifact.json"
DOMAIN = "python"
FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)

GatewayFactory = Callable[[], Any]


def _spec_reply(case: BenchmarkCase) -> str:
    template = load_spec_template(DEFAULT_TEMPLATES_DIR)
    lines = [f"# SPEC: {case.id}", ""]
    for section in template.required_sections:
        lines.append(section)
        lines.append(f"Content for {case.id}: {case.requirement}")
        lines.append("")
    return "\n".join(lines)


def _plan_reply() -> str:
    template = load_plan_template(DEFAULT_TEMPLATES_DIR)
    lines = ["# PLAN: frozen-spec", ""]
    for section in template.required_sections:
        lines.append(section)
        lines.extend(_plan_section_lines(section))
        lines.append("")
    return "\n".join(lines)


def _plan_section_lines(section: str) -> list[str]:
    if section == "## Linked SPEC":
        return ["ID: spec-1", "Version: 1"]
    if section == "## Milestones":
        return [
            "### M1: Implementation",
            "- Deliverables: The module described by the SPEC",
            "- Acceptance criteria: All SPEC acceptance criteria pass",
            "- Depends on: none",
        ]
    return ["Content."]


class _CaseAdapter:
    """Shared rollout plumbing over the evaluation case set."""

    agent_type = ""

    def __init__(
        self,
        *,
        runs_root: Path,
        gateway_factory: GatewayFactory | None = None,
        cases_dir: Path = DEFAULT_CASES_DIR,
    ) -> None:
        self._runs_root = runs_root
        self._gateway_factory = gateway_factory or self._default_gateway_factory
        self._cases = {case.id: case for case in load_cases(cases_dir)}

    def _default_gateway_factory(self) -> Any:
        raise NotImplementedError

    def _run_agent(self, task_id: str, harness: Tree | None, gateway: Any) -> AgentResult:
        raise NotImplementedError

    def tasks(self) -> list[str]:
        return sorted(self._cases)

    def domain_of(self, task_id: str) -> str:
        return DOMAIN

    def base_harness(self) -> Tree:
        return default_tree(self.agent_type)

    def validate_tree(self, tree: Tree) -> None:
        errors = validate_candidate(self.agent_type, tree)
        if errors:
            raise ValueError("\n".join(errors))

    def execute(self, task_id: str, harness: Tree | None, run_id: str) -> Path:
        run_dir = self._runs_root / run_id
        if (run_dir / "result.json").is_file():
            return run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        recorder = TrajectoryRecorder()
        gateway = RecordingGateway(self._gateway_factory(), recorder)
        result = self._run_agent(task_id, harness, gateway)
        _record_result(recorder, result)
        save_events(run_dir / "trajectory.jsonl", recorder.events)
        _write_result(run_dir, task_id, result)
        return run_dir

    def delivered(self, run_dir: Path) -> bool:
        payload = _read_result(run_dir)
        return bool(payload and payload.get("delivered"))

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        return render_trajectory(load_events(run_dir / "trajectory.jsonl"), obs_trunc=obs_trunc)

    def deliverable_text(self, run_dir: Path) -> str:
        artifact_path = run_dir / "artifact.json"
        if not artifact_path.is_file():
            return ""
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        content = artifact.get("content")
        return str(content.get("text", "")) if isinstance(content, dict) else ""

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        payload = _read_result(run_dir)
        if payload is None:
            return None
        delivered = bool(payload.get("delivered"))
        return {"delivered": delivered, "completion": 1.0 if delivered else 0.0}


def _record_result(recorder: TrajectoryRecorder, result: AgentResult) -> None:
    for artifact in result.artifacts:
        text = ""
        if isinstance(artifact.content, dict):
            text = str(artifact.content.get("text", ""))
        recorder.record_artifact(artifact.type, artifact.id, artifact.version, text)
    for error in result.errors:
        recorder.record_error("agent", f"{error.code}: {error.message}")


def _write_result(run_dir: Path, task_id: str, result: AgentResult) -> None:
    payload = {
        "taskId": task_id,
        "status": result.status,
        "delivered": bool(result.artifacts),
        "errors": [f"{error.code}: {error.message}" for error in result.errors],
    }
    (run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if result.artifacts:
        artifact = result.artifacts[0].to_contract()
        (run_dir / "artifact.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")


def _read_result(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "result.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime(gateway: Any, prefix: str) -> AgentRuntime:
    ids = count(1)
    return AgentRuntime(
        models=gateway,
        clock=lambda: FIXED_NOW,
        new_id=lambda: f"{prefix}-{next(ids)}",
    )


def _components(harness: Tree | None, agent: str):
    return tree_to_components(harness, agent) if harness is not None else None


class SpecTaskAdapter(_CaseAdapter):
    """Spec agent over the evaluation cases (input: the case requirement)."""

    agent_type = "spec"

    def _default_gateway_factory(self) -> Any:
        case = next(iter(self._cases.values()))
        return ScriptedModelGateway([_spec_reply(case)] * 64)

    def task_input(self, task_id: str) -> AgentRequest:
        case = self._cases[task_id]
        return AgentRequest(
            request_id=f"req-{task_id}",
            task_id=task_id,
            project_id="harness-cases",
            workflow_id="harness2",
            agent_id="agent-spec",
            input={"requirement": case.requirement, "language": "en"},
            context={"project": {"name": task_id, "technology": ["python"]}},
            artifacts=[],
            feedback=[],
            metadata={"attempt": 1},
        )

    def _run_agent(self, task_id: str, harness: Tree | None, gateway: Any) -> AgentResult:
        settings = SpecSettings(
            prompts=load_spec_prompts(),
            template=load_spec_template(DEFAULT_TEMPLATES_DIR),
            harness=_components(harness, "spec"),
        )
        agent = SpecAgent(_runtime(gateway, "spec"), settings)
        return agent.execute(self.task_input(task_id))


class PlanTaskAdapter(_CaseAdapter):
    """Plan agent over the cases; the upstream SPEC is a committed fixture."""

    agent_type = "plan"

    def _default_gateway_factory(self) -> Any:
        return ScriptedModelGateway([_plan_reply()] * 64)

    def task_input(self, task_id: str) -> AgentRequest:
        fixture = json.loads(FIXTURE_SPEC_PATH.read_text(encoding="utf-8"))
        spec = Artifact.model_validate(fixture)
        return AgentRequest(
            request_id=f"req-{task_id}",
            task_id=task_id,
            project_id="harness-cases",
            workflow_id="harness2",
            agent_id="agent-plan",
            input={"language": "en"},
            context={"project": {"name": task_id, "technology": ["python"]}},
            artifacts=[spec],
            feedback=[],
            metadata={"attempt": 1},
        )

    def _run_agent(self, task_id: str, harness: Tree | None, gateway: Any) -> AgentResult:
        settings = PlanSettings(
            prompts=load_plan_prompts(),
            template=load_plan_template(DEFAULT_TEMPLATES_DIR),
            harness=_components(harness, "plan"),
        )
        agent = PlanAgent(_runtime(gateway, "plan"), settings)
        return agent.execute(self.task_input(task_id))
