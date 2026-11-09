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
TEST_ESCALATED_STAGE = "TEST_ESCALATED"


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


_LOOP_STAGES = (FIX_STAGE, REWORK_STAGE, ESCALATED_STAGE, TEST_ESCALATED_STAGE)


def loop_graph(
    graph: StageGraph,
    definition: WorkflowDefinition,
    policy: CodeLoopPolicy,
) -> StageGraph:
    steps = code_steps(definition)
    if {stage.name for stage in graph.stages} & set(_LOOP_STAGES):
        raise ValueError("Workflow stages collide with code-loop stages")
    if any(step.id == FIX_STEP for step in definition.steps):
        raise ValueError("Workflow step ID collides with the code-loop step")
    stages = (*graph.stages, *_loop_stages(steps))
    edges = [*graph.edges, *_loop_edges(graph, steps)]
    return StageGraph(stages, tuple(edges), {**graph.max_revisions, FIX_STEP: policy.max_fixes})


def _loop_stages(steps: dict[str, WorkflowStepDef]) -> tuple[StageInfo, ...]:
    return (
        StageInfo(FIX_STAGE, StageKind.STEP, FIX_STEP),
        StageInfo(REWORK_STAGE, StageKind.REJECTED, FIX_STEP),
        StageInfo(ESCALATED_STAGE, StageKind.ESCALATED, FIX_STEP),
        StageInfo(TEST_ESCALATED_STAGE, StageKind.ESCALATED, steps["test"].id),
    )


def _loop_edges(graph: StageGraph, steps: dict[str, WorkflowStepDef]) -> list[Edge]:
    edges = [
        Edge(steps["review"].stage, Trigger.REQUEST_CHANGES, REWORK_STAGE),
        Edge(steps["test"].stage, Trigger.REQUEST_CHANGES, REWORK_STAGE),
        Edge(REWORK_STAGE, Trigger.REVISE, FIX_STAGE, "within_limit"),
        Edge(REWORK_STAGE, Trigger.REVISE, ESCALATED_STAGE, "limit_reached"),
        Edge(ESCALATED_STAGE, Trigger.RESUME, FIX_STAGE),
        Edge(FIX_STAGE, Trigger.COMPLETE, steps["review"].stage),
        Edge(steps["test"].stage, Trigger.ADVANCE, steps["implement"].stage),
        *_test_escalation_edges(graph, steps),
    ]
    for stage in _LOOP_STAGES:
        edges.extend(
            [
                Edge(stage, Trigger.FAIL, "FAILED"),
                Edge(stage, Trigger.CANCEL, "CANCELLED"),
            ]
        )
    return edges


def _test_escalation_edges(graph: StageGraph, steps: dict[str, WorkflowStepDef]) -> list[Edge]:
    """The NO_TESTS operator stop, hung off the test stage.

    ESCALATE parks the run at TEST_ESCALATED; RESUME returns for a
    retest with replaced commands; COMPLETE leaves by the test
    stage's own exit (the skip path), and ADVANCE serves the
    multi-item skip through the same bookkeeping a pass uses.
    """
    test_stage = steps["test"].stage
    after_test = next(
        (
            edge.target
            for edge in graph.edges
            if edge.source == test_stage and edge.trigger == Trigger.COMPLETE
        ),
        "COMPLETED",
    )
    return [
        Edge(test_stage, Trigger.ESCALATE, TEST_ESCALATED_STAGE),
        Edge(TEST_ESCALATED_STAGE, Trigger.RESUME, test_stage),
        Edge(TEST_ESCALATED_STAGE, Trigger.COMPLETE, after_test),
        Edge(TEST_ESCALATED_STAGE, Trigger.ADVANCE, steps["implement"].stage),
    ]


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
