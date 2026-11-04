"""Offline evaluation runner: real Spec/Plan agents + orchestrator, scripted model.

Everything here is deterministic and offline. The agents are the real runtime
agents; only the model gateway is scripted, with canned SPEC/PLAN replies whose
format follows the templates the agents validate against.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from asf.agents.base import AgentRuntime
from asf.agents.plan.factory import build_plan_agent
from asf.agents.spec.factory import build_spec_agent
from asf.approval.models import ApprovalPolicy
from asf.approval.service import ApprovalService
from asf.configuration.platform import PlatformConfig
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.storage.memory import InMemoryApprovalRepository
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
from harness.evaluation.cases import BenchmarkCase

__all__ = ["CaseResult", "EvaluationRunner", "Report"]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATES_DIR = REPO_ROOT / "templates"
REVIEWER = "harness"
MAX_TICKS = 50
TERMINAL_STAGES = {"COMPLETED", "FAILED", "CANCELLED"}


class _StepClock:
    """Deterministic clock: every call advances by one second."""

    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self._now
        self._now += timedelta(seconds=1)
        return current


def _spec_text(case: BenchmarkCase) -> str:
    return f"""# SPEC: {case.id}

## Background / Goal
{case.requirement}

## Scope (in / out)
In scope: The feature described in the requirement above.
Out of scope: Anything not stated in the requirement.

## Functional requirements
- REQ-1: Implement the feature described in the requirement: {case.requirement}
- REQ-2: Reject invalid input with a clear, descriptive error.

## Non-functional requirements
- Python 3.12+ compatible
- No external dependencies beyond the standard library

## Acceptance criteria
- The feature behaves exactly as described in the requirement
- Invalid input is rejected with a descriptive error

## Open questions
None.

## Revision history
- v1: Initial specification.
"""


def _plan_text(case: BenchmarkCase) -> str:
    # The canned SPEC artifact is the spec agent's first generated id: "spec-1".
    return f"""# PLAN: {case.id}

## Linked SPEC
ID: spec-1
Version: 1

## Scope and out of scope
In scope: The feature described in the linked SPEC.
Out of scope: Anything not stated in the linked SPEC.

## Approach / architecture
Implement the feature as a single small module, then cover it with unit tests.

## Impacted components
- app.py (new file)

## Milestones
### M1: Implementation
- Deliverables: app.py
- Acceptance criteria: All SPEC acceptance criteria pass
- Depends on: none

## Testing strategy
Unit tests covering the requirement and its invalid-input behaviour.

## Risks & mitigations
- Risk: Ambiguous requirement details. Mitigation: Follow the SPEC literally.

## Open questions
None.

## Revision history
- v1: Initial plan.
"""


def _workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="spec-plan",
        name="Spec and Plan",
        version="1",
        steps=[
            WorkflowStepDef(
                id="spec", name="Spec", type="AGENT", stage="SPEC",
                agent_type="spec", requires_approval=True, produces=["SPEC"],
            ),
            WorkflowStepDef(
                id="plan", name="Plan", type="AGENT", stage="PLAN",
                agent_type="plan", requires_approval=True,
                consumes=["SPEC"], produces=["PLAN"],
            ),
        ],
    )


class CaseResult(BaseModel):
    """Scored outcome of one benchmark case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    completed: bool
    artifacts_produced: list[str] = Field(default_factory=list)
    revisions: int = 0
    duration_seconds: float = 0.0
    score: float = Field(ge=0, le=1)
    passed: bool
    failures: list[str] = Field(default_factory=list)


class Report(BaseModel):
    """Aggregate result of a full evaluation run."""

    model_config = ConfigDict(extra="forbid")

    results: list[CaseResult] = Field(default_factory=list)
    mean_score: float = 0.0
    pass_rate: float = 0.0


class EvaluationRunner:
    """Runs benchmark cases through the real spec -> plan chain, auto-approving."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._templates_dir = templates_dir or DEFAULT_TEMPLATES_DIR

    def _build_engine(self, case: BenchmarkCase) -> Orchestrator:
        clock = _StepClock()
        ids = count(1)

        def new_id() -> str:
            return f"id-{next(ids)}"

        def agent_ids(prefix: str):  # noqa: ANN202 - small local factory
            counter = count(1)
            return lambda: f"{prefix}-{next(counter)}"

        platform = PlatformConfig()
        registry = AgentRegistry()
        registry.register(build_spec_agent(
            AgentRuntime(
                models=ScriptedModelGateway([_spec_text(case)]),
                clock=clock, new_id=agent_ids("spec"),
            ),
            platform, self._templates_dir,
        ))
        registry.register(build_plan_agent(
            AgentRuntime(
                models=ScriptedModelGateway([_plan_text(case)]),
                clock=clock, new_id=agent_ids("plan"),
            ),
            platform, self._templates_dir,
        ))
        return Orchestrator(
            _workflow_definition(), registry, clock=clock, new_id=new_id,
            approvals=ApprovalService(InMemoryApprovalRepository(), id_factory=new_id),
            approval_policy=ApprovalPolicy(reviewers=[REVIEWER]),
        )

    def run_case(self, case: BenchmarkCase) -> CaseResult:
        engine = self._build_engine(case)
        run = engine.start(
            task_id=f"task-{case.id}", project_id="harness",
            inputs={"spec": {"requirement": case.requirement}},
        )
        for _ in range(MAX_TICKS):
            if run.state.stage in TERMINAL_STAGES:
                break
            if run.approval_id:
                run = engine.decide(run.id, reviewer=REVIEWER, decision="APPROVED")
            else:
                run = engine.tick(run.id)

        completed = run.state.stage == "COMPLETED"
        produced = sorted(run.artifacts)
        revisions = sum(run.state.revisions.values())
        duration = max(0.0, (run.updated_at - run.started_at).total_seconds())

        failures: list[str] = []
        if case.must_complete and not completed:
            failures.append(f"workflow ended in stage {run.state.stage}, not COMPLETED")
        missing = [kind for kind in case.expected_artifacts if kind not in produced]
        if missing:
            failures.append(f"missing expected artifacts: {', '.join(missing)}")
        if revisions > case.max_revisions:
            failures.append(
                f"revisions {revisions} exceeded max_revisions {case.max_revisions}"
            )
        for error in run.errors:
            failures.append(f"{error.code}: {error.message}")

        artifact_fraction = (
            (len(case.expected_artifacts) - len(missing)) / len(case.expected_artifacts)
            if case.expected_artifacts else 1.0
        )
        score = (
            (0.5 if completed else 0.0)
            + 0.3 * artifact_fraction
            + (0.2 if revisions <= case.max_revisions else 0.0)
        )
        return CaseResult(
            case_id=case.id,
            completed=completed,
            artifacts_produced=produced,
            revisions=revisions,
            duration_seconds=duration,
            score=round(score, 4),
            passed=not failures,
            failures=failures,
        )

    def run_all(self, cases: list[BenchmarkCase]) -> Report:
        results = [self.run_case(case) for case in cases]
        if not results:
            return Report()
        mean_score = round(sum(r.score for r in results) / len(results), 4)
        pass_rate = round(sum(1 for r in results if r.passed) / len(results), 4)
        return Report(results=results, mean_score=mean_score, pass_rate=pass_rate)
