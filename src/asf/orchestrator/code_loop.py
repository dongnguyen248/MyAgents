from __future__ import annotations

from pydantic import Field

from asf.agents._shared.code_agents import task_items
from asf.agents.task.agent import MAX_TASKS, TaskContent
from asf.configuration.platform import ConfigModel, RetryPolicySettings
from asf.contracts.models import Artifact
from asf.state_machine.graph import Edge, StageGraph, StageInfo
from asf.state_machine.triggers import StageKind, Trigger
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef

FIX_STEP = "__code_fix"
FIX_STAGE = "CODE_FIX"
REWORK_STAGE = "CODE_REWORK"
ESCALATED_STAGE = "CODE_FIX_ESCALATED"


class CodeLoopPolicy(ConfigModel):
    max_fixes: int = Field(default=3, ge=0, le=100)
    all_task_items: bool = True
    fix_retry_policy: RetryPolicySettings | None = None


def code_steps(definition: WorkflowDefinition) -> dict[str, WorkflowStepDef]:
    result: dict[str, WorkflowStepDef] = {}
    for kind in ("implement", "review", "test"):
        matches = [step for step in definition.steps if step.agent_type == kind]
        if len(matches) != 1 or matches[0].requires_approval or matches[0].action is not None:
            raise ValueError("Code loops require one plain implement, review and test agent step")
        result[kind] = matches[0]
    indices = [definition.steps.index(result[kind]) for kind in ("implement", "review", "test")]
    if indices != list(range(indices[0], indices[0] + 3)):
        raise ValueError("Implement, review and test must be consecutive and ordered")
    for kind, produces in (
        ("implement", ["CODE"]),
        ("review", ["CODE_REVIEW"]),
        ("test", ["TEST_REPORT"]),
    ):
        if result[kind].produces != produces:
            raise ValueError("Code loop artifact outputs do not match the agent contracts")
    return result


def loop_graph(
    graph: StageGraph,
    definition: WorkflowDefinition,
    policy: CodeLoopPolicy,
) -> StageGraph:
    steps = code_steps(definition)
    names = {stage.name for stage in graph.stages}
    if names & {FIX_STAGE, REWORK_STAGE, ESCALATED_STAGE}:
        raise ValueError("Workflow stages collide with code-loop stages")
    if any(step.id == FIX_STEP for step in definition.steps):
        raise ValueError("Workflow step ID collides with the code-loop step")
    stages = (
        *graph.stages,
        StageInfo(FIX_STAGE, StageKind.STEP, FIX_STEP),
        StageInfo(REWORK_STAGE, StageKind.REJECTED, FIX_STEP),
        StageInfo(ESCALATED_STAGE, StageKind.ESCALATED, FIX_STEP),
    )
    edges = list(graph.edges)
    for kind in ("review", "test"):
        edges.append(Edge(steps[kind].stage, Trigger.REQUEST_CHANGES, REWORK_STAGE))
    edges.extend(
        [
            Edge(REWORK_STAGE, Trigger.REVISE, FIX_STAGE, "within_limit"),
            Edge(REWORK_STAGE, Trigger.REVISE, ESCALATED_STAGE, "limit_reached"),
            Edge(ESCALATED_STAGE, Trigger.RESUME, FIX_STAGE),
            Edge(FIX_STAGE, Trigger.COMPLETE, steps["review"].stage),
            Edge(steps["test"].stage, Trigger.ADVANCE, steps["implement"].stage),
        ]
    )
    for stage in (FIX_STAGE, REWORK_STAGE, ESCALATED_STAGE):
        edges.extend(
            [
                Edge(stage, Trigger.FAIL, "FAILED"),
                Edge(stage, Trigger.CANCEL, "CANCELLED"),
            ]
        )
    return StageGraph(stages, tuple(edges), {**graph.max_revisions, FIX_STEP: policy.max_fixes})


def ordered_task_ids(artifact: Artifact) -> list[str]:
    items = task_items(artifact)
    tasks = TaskContent.model_validate({"tasks": items}).tasks
    if len(tasks) > MAX_TASKS:
        raise ValueError("TASK exceeds the task count limit")
    by_id = {task.id: task for task in tasks}
    if len(by_id) != len(tasks):
        raise ValueError("TASK IDs must be unique")
    if any(set(task.depends_on) - by_id.keys() for task in tasks):
        raise ValueError("TASK has unknown dependencies")
    ordered: list[str] = []
    while len(ordered) < len(tasks):
        ready = [
            task.id
            for task in tasks
            if task.id not in ordered and set(task.depends_on) <= set(ordered)
        ]
        if not ready:
            raise ValueError("TASK dependencies contain a cycle")
        ordered.extend(ready)
    return ordered
