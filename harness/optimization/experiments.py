"""Optimization experiments over agent/orchestrator configuration.

Design choice: this module runs the *real code loop* (Spec -> Plan -> Task ->
Implement -> Review -> Test, with Fix on review failure) end-to-end through
the orchestrator, instead of the lighter spec/plan revision fallback. The
scenario is deterministic: the first code review always requests changes,
so a run can only complete if the ``CodeLoopPolicy`` fix budget lets the
FixAgent repair the code. Comparing ``max_fixes=0`` with ``max_fixes=3``
therefore measures a real configuration effect, not simulated numbers.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from asf.agents.base import AgentRuntime
from asf.agents.fix import build_fix_agent
from asf.agents.implement import build_implement_agent
from asf.agents.plan import build_plan_agent
from asf.agents.review import build_review_agent
from asf.agents.spec import build_spec_agent
from asf.agents.task import build_task_agent
from asf.agents.test import build_test_agent
from asf.approval.models import ApprovalPolicy
from asf.configuration.platform import AgentSettings, PlatformConfig
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, CodeLoopPolicy, Orchestrator
from asf.storage.memory import InMemoryStore
from asf.tools.fake import InMemoryRepository, ScriptedSandbox
from asf.workflow.definition import WorkflowDefinition
from harness.evaluation.cases import BenchmarkCase
from harness.evaluation.runner import _plan_text, _spec_text

__all__ = ["ConfigResult", "ExperimentResult", "run_fix_cycle_experiment"]

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "templates"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
REVIEWER = "harness"
_HUMAN_GATE = {"approval": {"overrides": {"mode": "human"}}}
TERMINAL_STAGES = {"COMPLETED", "FAILED", "CANCELLED", "CODE_FIX_ESCALATED"}
MAX_TICKS = 50

_CASE = BenchmarkCase(
    id="calculator",
    requirement=(
        "Build a small calculator module with add, subtract, multiply and "
        "divide functions, where division by zero raises a clear error."
    ),
    expected_artifacts=["SPEC", "PLAN"],
    max_revisions=2,
    must_complete=True,
)

_TASK_TEXT = json.dumps(
    {
        "tasks": [
            {
                "id": "T1",
                "title": "Create calculator module",
                "milestoneRef": "M1",
                "description": "Implement add, subtract, multiply, divide in calculator.py",
                "acceptanceCriteria": ["Function add(a, b) returns a + b"],
                "dependsOn": [],
                "expectedFiles": ["calculator.py"],
                "verificationHint": "Run unit tests",
            }
        ]
    },
    indent=2,
)


def _change() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "calculator.py",
                    "operation": "create",
                    "content": "def add(a, b):\n    return a + b\n",
                }
            ]
        }
    )


def _review(verdict: str) -> str:
    findings = (
        []
        if verdict == "APPROVE"
        else [
            {
                "severity": "ERROR",
                "path": "calculator.py",
                "description": "Correct the implementation",
            }
        ]
    )
    return json.dumps({"findings": findings, "verdict": verdict})


class ConfigResult(BaseModel):
    """Outcome of one code-loop configuration in the experiment."""

    model_config = ConfigDict(extra="forbid")

    config: str
    max_fixes: int
    completed: bool
    final_stage: str
    fix_cycles_used: int = 0
    revisions: int = 0
    score: float = Field(ge=0, le=1)


class ExperimentResult(BaseModel):
    """All configurations tried, plus the declared winner and why."""

    model_config = ConfigDict(extra="forbid")

    results: list[ConfigResult] = Field(default_factory=list)
    winner: str
    rationale: str


def _run_code_loop(max_fixes: int) -> ConfigResult:
    clock = lambda: NOW  # noqa: E731 - fixed clock, as in the integration tests
    # The experiment's scripted replies speak the legacy JSON code
    # format; the experiment varies the fix-cycle budget, not the
    # output format, so pin the format (and no repair loop, which
    # would consume scripted replies) explicitly.
    platform = PlatformConfig(
        agents={
            "implement": AgentSettings(
                settings={"editFormat": "json", "repairAttempts": 0},
            ),
            "fix": AgentSettings(
                settings={"editFormat": "json", "repairAttempts": 0},
            ),
        }
    )
    registry = AgentRegistry()
    gateways: dict[str, ScriptedModelGateway] = {}

    def runtime(kind: str, replies: list[str]) -> AgentRuntime:
        counter = count(1)
        gateway = ScriptedModelGateway(replies)
        gateways[kind] = gateway
        return AgentRuntime(gateway, clock, lambda: f"{kind}-{next(counter)}")

    repository = InMemoryRepository()
    registry.register(
        build_spec_agent(runtime("spec", [_spec_text(_CASE)]), platform, TEMPLATES_DIR)
    )
    registry.register(
        build_plan_agent(runtime("plan", [_plan_text(_CASE)]), platform, TEMPLATES_DIR)
    )
    registry.register(build_task_agent(runtime("task", [_TASK_TEXT]), platform, TEMPLATES_DIR))
    registry.register(
        build_implement_agent(
            runtime("implement", [_change()]), platform, TEMPLATES_DIR, repository
        )
    )
    registry.register(
        build_review_agent(
            runtime("review", [_review("CHANGES_REQUESTED"), _review("APPROVE")]),
            platform,
            TEMPLATES_DIR,
        )
    )
    registry.register(
        build_test_agent(runtime("test", []), platform, TEMPLATES_DIR, ScriptedSandbox())
    )
    registry.register(
        build_fix_agent(
            runtime("fix", [_change(), _change(), _change()]), platform, TEMPLATES_DIR, repository
        )
    )

    definition = WorkflowDefinition.model_validate(
        yaml.safe_load(
            (REPO_ROOT / "workflow-definitions" / "software-development.yaml").read_text(
                encoding="utf-8"
            )
        )
    )
    definition = definition.model_copy(update={"steps": definition.steps[:6]})

    with tempfile.TemporaryDirectory():
        store = InMemoryStore()
        ids = count(1)
        engine = Orchestrator(
            definition,
            registry,
            clock=clock,
            new_id=lambda: f"orchestration-{next(ids)}",
            store=store,
            approval_policy=ApprovalPolicy(reviewers=[REVIEWER]),
            code_loop=CodeLoopPolicy(max_fixes=max_fixes),
        )
        run = engine.start(
            task_id="experiment-1",
            project_id="harness",
            inputs={"spec": {"requirement": _CASE.requirement}, "implement": {"ref": "main"}},
            # The experiment approves the gates itself, so the run is
            # pinned to human approval (the shipped workflow's gates
            # otherwise default to the Phase 12 ai review loop).
            context={"project": {"testCommands": [["pytest", "-q"]]}, **_HUMAN_GATE},
        )
        for _ in range(MAX_TICKS):
            if run.state.stage in TERMINAL_STAGES:
                break
            if run.approval_id:
                run = engine.decide(run.id, reviewer=REVIEWER, decision="APPROVED")
            else:
                run = engine.tick(run.id)
        store.close()

    completed = run.state.stage == "COMPLETED"
    fix_cycles = len(gateways["fix"].requests)
    return ConfigResult(
        config=f"max_fixes={max_fixes}",
        max_fixes=max_fixes,
        completed=completed,
        final_stage=run.state.stage,
        fix_cycles_used=fix_cycles,
        revisions=sum(run.state.revisions.values()),
        score=1.0 if completed else 0.0,
    )


def run_fix_cycle_experiment() -> ExperimentResult:
    """Compare fix budgets 0 vs 3 on a review-fails-first code-loop scenario."""
    results = [_run_code_loop(0), _run_code_loop(3)]
    winner = max(results, key=lambda r: (r.score, -r.fix_cycles_used))
    loser = next(r for r in results if r is not winner)
    if winner.completed and not loser.completed:
        rationale = (
            f"{winner.config} completed after {winner.fix_cycles_used} fix cycle(s); "
            f"{loser.config} ended in {loser.final_stage} without recovering."
        )
    elif winner.completed == loser.completed:
        rationale = (
            f"Both configurations completed={winner.completed}; {winner.config} "
            f"wins on fewer fix cycles ({winner.fix_cycles_used})."
        )
    else:
        rationale = f"Neither configuration completed; {winner.config} scored highest."
    return ExperimentResult(results=results, winner=winner.config, rationale=rationale)
