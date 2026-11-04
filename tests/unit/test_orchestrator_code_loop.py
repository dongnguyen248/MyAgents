import json

import pytest

from asf.orchestrator import CodeLoopPolicy, Orchestrator
from asf.orchestrator.code_loop import code_steps, loop_graph, ordered_task_ids
from asf.state_machine.graph import build_graph
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
from tests.integration.test_chain import make_task_artifact
from tests.unit.test_orchestrator import NOW, make_engine


def definition():
    return WorkflowDefinition(
        id="code", name="Code", version="1", steps=[
            WorkflowStepDef(
                id=kind, name=kind, type="AGENT", stage=kind.upper(),
                agent_type=kind, requires_approval=False, produces=[artifact],
            )
            for kind, artifact in (
                ("implement", "CODE"), ("review", "CODE_REVIEW"), ("test", "TEST_REPORT"),
            )
        ],
    )


def tasks(*items):
    template = json.loads(make_task_artifact().content["text"])["tasks"][0]
    return make_task_artifact().model_copy(update={
        "content": {"tasks": [{**template, **item} for item in items], "text": "Tasks"},
    })


def test_dependency_ordering_handles_unordered_and_independent_tasks_deterministically():
    artifact = tasks(
        {"id": "T3", "dependsOn": ["T2", "T1"]},
        {"id": "T2", "dependsOn": ["T1"]},
        {"id": "T1"}, {"id": "T4"},
    )
    assert ordered_task_ids(artifact) == ["T1", "T4", "T2", "T3"]
    assert ordered_task_ids(make_task_artifact()) == ["T1"]


@pytest.mark.parametrize("items", [
    [{"id": "T1", "dependsOn": ["T1"]}],
    [{"id": "T1", "dependsOn": ["T2"]}, {"id": "T2", "dependsOn": ["T1"]}],
    [{"id": "T1", "dependsOn": ["T9"]}],
    [{"id": "T1"}, {"id": "T1"}],
    [{"id": "bad-id"}],
    [],
])
def test_invalid_task_dependencies_or_identity_are_rejected(items):
    with pytest.raises(ValueError):
        ordered_task_ids(tasks(*items))


@pytest.mark.parametrize("content", [
    None, "text", {}, {"text": "[]"}, {"text": "not JSON"}, {"tasks": "wrong"},
])
def test_malformed_task_content_is_rejected(content):
    artifact = make_task_artifact().model_copy(update={"content": content})
    with pytest.raises(ValueError):
        ordered_task_ids(artifact)


def test_task_count_limit_is_enforced():
    with pytest.raises(ValueError, match="count"):
        ordered_task_ids(tasks(*[{"id": f"T{index}"} for index in range(1, 102)]))


@pytest.mark.parametrize("defect", [
    "missing", "duplicate", "approval", "action", "order", "output",
    "stage-collision", "id-collision",
])
def test_loop_policy_rejects_incompatible_workflow_shapes(defect):
    workflow = definition()
    steps = workflow.steps
    if defect == "missing":
        steps.pop()
    elif defect == "duplicate":
        steps.append(steps[0])
    elif defect == "approval":
        steps[0] = steps[0].model_copy(update={"requires_approval": True})
    elif defect == "action":
        steps[0] = steps[0].model_copy(update={"action": "something"})
    elif defect == "order":
        steps[0], steps[1] = steps[1], steps[0]
    elif defect == "output":
        steps[0] = steps[0].model_copy(update={"produces": ["OTHER"]})
    elif defect == "stage-collision":
        steps[0] = steps[0].model_copy(update={"stage": "CODE_FIX"})
    else:
        steps[0] = steps[0].model_copy(update={"id": "__code_fix"})
    with pytest.raises(ValueError):
        loop_graph(build_graph(workflow), workflow, CodeLoopPolicy())


def test_valid_loop_graph_has_bounded_revision_and_resume_edges():
    workflow = definition()
    graph = loop_graph(build_graph(workflow), workflow, CodeLoopPolicy(max_fixes=3))
    assert graph.max_revisions["__code_fix"] == 3
    assert {stage.name for stage in graph.stages} >= {
        "CODE_FIX", "CODE_REWORK", "CODE_FIX_ESCALATED",
    }
    assert code_steps(workflow)["implement"].id == "implement"


def test_approval_workflow_requires_single_artifact_per_approval():
    engine, _, _, _ = make_engine(approval=True)
    workflow = engine._definition.model_copy(deep=True)
    workflow.steps[0] = workflow.steps[0].model_copy(update={"produces": ["SPEC", "OTHER"]})
    with pytest.raises(ValueError, match="exactly one"):
        Orchestrator(
            workflow, engine._registry, clock=lambda: NOW, new_id=engine._new_id,
            approvals=engine._approvals, approval_policy=engine._approval_policy,
        )
