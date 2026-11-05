from __future__ import annotations

import json
from itertools import count
from pathlib import Path

import pytest
import yaml

from asf.agents.base import AgentRuntime
from asf.agents.fix import build_fix_agent
from asf.agents.implement import build_implement_agent
from asf.agents.plan import build_plan_agent
from asf.agents.review import build_review_agent
from asf.agents.spec import build_spec_agent
from asf.agents.task import build_task_agent
from asf.agents.test import build_test_agent
from asf.approval.models import ApprovalPolicy
from asf.configuration.platform import RetryPolicySettings
from asf.contracts.models import AgentResult, RunMetrics
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, CodeLoopPolicy, Orchestrator
from asf.storage.sqlite import SQLiteExecutionStore
from asf.tools.fake import InMemoryRepository, ScriptedSandbox
from asf.tools.ports import CommandResult
from asf.workflow.definition import WorkflowDefinition
from tests.integration.test_chain import (
    PLATFORM,
    TEMPLATES_DIR,
    make_plan_artifact,
    make_spec_artifact,
    make_task_artifact,
)
from tests.unit.contract_models import validator_for
from tests.unit.test_orchestrator import NOW


def change(path="calculator.py", content="def add(a, b): return a + b"):
    return json.dumps({"changes": [{"path": path, "operation": "create", "content": content}]})


def review(verdict="APPROVE", path="calculator.py"):
    findings = [] if verdict == "APPROVE" else [{
        "severity": "ERROR", "path": path, "description": "Correct the implementation",
    }]
    return json.dumps({"findings": findings, "verdict": verdict})


class RecordingSandbox(ScriptedSandbox):
    def __init__(self, exits):
        super().__init__()
        self.exits = iter(exits)
        self.calls = []

    def run(self, commands, changes, ref, *, fail_fast=True):
        self.calls.append((changes, ref))
        self._default_result = CommandResult(next(self.exits), "fixture output", "", 1)
        return super().run(commands, changes, ref, fail_fast=fail_fast)


def harness(
    tmp_path, *, review_replies, exits, fix_replies=(), task_reply=None,
    implement_replies=None, max_fixes=3, with_actions=False,
    code_policy=None,
):
    registry = AgentRegistry()
    gateways = {}

    def runtime(kind, replies):
        ids = count(1)
        gateway = ScriptedModelGateway(replies)
        gateways[kind] = gateway
        return AgentRuntime(gateway, lambda: NOW, lambda: f"{kind}-{next(ids)}")

    registry.register(build_spec_agent(
        runtime("spec", [make_spec_artifact().content["text"]]), PLATFORM, TEMPLATES_DIR,
    ))
    registry.register(build_plan_agent(
        runtime("plan", [make_plan_artifact().content["text"]]), PLATFORM, TEMPLATES_DIR,
    ))
    registry.register(build_task_agent(
        runtime("task", [task_reply or make_task_artifact().content["text"]]),
        PLATFORM, TEMPLATES_DIR,
    ))
    repository = InMemoryRepository()
    registry.register(build_implement_agent(
        runtime("implement", implement_replies or [change()]), PLATFORM, TEMPLATES_DIR, repository,
    ))
    registry.register(build_review_agent(
        runtime("review", review_replies), PLATFORM, TEMPLATES_DIR,
    ))
    sandbox = RecordingSandbox(exits)
    registry.register(build_test_agent(runtime("test", []), PLATFORM, TEMPLATES_DIR, sandbox))
    registry.register(build_fix_agent(
        runtime("fix", fix_replies), PLATFORM, TEMPLATES_DIR, repository,
    ))
    definition = WorkflowDefinition.model_validate(yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "workflows" / "software-development.yaml").read_text(
            encoding="utf-8",
        ),
    ))
    if not with_actions:
        definition = definition.model_copy(update={"steps": definition.steps[:6]})
    store = SQLiteExecutionStore(tmp_path / "workflow.sqlite")
    ids = count(1)
    engine = Orchestrator(
        definition, registry, clock=lambda: NOW, new_id=lambda: f"orchestration-{next(ids)}",
        store=store, approval_policy=ApprovalPolicy(reviewers=["reviewer"]),
        code_loop=code_policy or CodeLoopPolicy(max_fixes=max_fixes),
    )
    run = engine.start(
        task_id="work-1", project_id="project-1",
        inputs={"spec": {"requirement": "Create a calculator"},
                "implement": {"ref": "main"}},
        context={"project": {"testCommands": [["pytest", "-q"]]}},
    )
    return engine, run, store, gateways, repository, sandbox


def drive(engine, run, *, limit=50):
    for _ in range(limit):
        if run.state.stage in ("COMPLETED", "FAILED", "CODE_FIX_ESCALATED"):
            return run
        if run.approval_id:
            run = engine.decide(run.id, reviewer="reviewer", decision="APPROVED")
        else:
            run = engine.tick(run.id)
    pytest.fail("Orchestrator did not reach a bounded stop")


@pytest.mark.parametrize("failure_source", ["none", "review", "test", "both"])
def test_actual_agents_complete_bounded_rework_and_preserve_links(tmp_path, failure_source):
    review_replies = [review()]
    exits = [0]
    fixes = []
    if failure_source == "review":
        review_replies = [review("CHANGES_REQUESTED"), review()]
        fixes = [change()]
    elif failure_source == "test":
        review_replies = [review(), review()]
        exits, fixes = [1, 0], [change()]
    elif failure_source == "both":
        review_replies = [review("CHANGES_REQUESTED"), review(), review()]
        exits, fixes = [1, 0], [change(), change()]
    engine, run, store, gateways, repository, sandbox = harness(
        tmp_path, review_replies=review_replies, exits=exits, fix_replies=fixes,
    )
    run = drive(engine, run)
    assert run.state.stage == "COMPLETED", [(error.code, error.message) for error in run.errors]
    assert run.errors == []
    assert sum(item.event.event_type == "WORKFLOW_COMPLETED"
               for item in run.observations if item.event) == 1
    assert len(gateways["fix"].requests) == len(fixes)
    assert len(gateways["implement"].requests) == 1
    assert not gateways["test"].requests
    assert len(sandbox.calls) == len(exits)
    assert all(ref == "main" for _, ref in sandbox.calls)
    assert repository.list_tree("main") == ()
    final = run.item_results["T1"]
    assert final["CODE"].version == str(1 + len(fixes))
    assert final["CODE_REVIEW"].metadata["codeArtifactId"] == final["CODE"].id
    assert final["TEST_REPORT"].metadata["codeArtifactId"] == final["CODE"].id
    assert final["CODE_REVIEW"].content["review"]["verdict"] == "APPROVE"
    assert final["TEST_REPORT"].content["report"]["verdict"] == "PASS"
    assert len(run.artifact_history) == sum(len(result.artifacts) for result in run.results)
    validator_for("WorkflowRun").validate(engine.workflow_run(run.id))
    validator_for("Task").validate(engine.task(run.id))
    for result in run.results:
        validator_for("AgentResult").validate(result.to_contract())
    store.close()


def test_three_fixes_max_then_persisted_escalation_and_explicit_resume(tmp_path):
    engine, run, store, gateways, _, _ = harness(
        tmp_path, review_replies=[review("CHANGES_REQUESTED")] * 4 + [review()],
        exits=[0], fix_replies=[change()] * 4,
    )
    run = drive(engine, run)
    assert run.state.stage == "CODE_FIX_ESCALATED"
    assert len(gateways["fix"].requests) == 3
    assert len(gateways["review"].requests) == 4
    assert engine.tick(run.id).state.stage == "CODE_FIX_ESCALATED"
    assert len(gateways["fix"].requests) == 3
    store.close()
    store = SQLiteExecutionStore(tmp_path / "workflow.sqlite")
    engine = Orchestrator(
        engine._definition, engine._registry, clock=engine._clock, new_id=engine._new_id,
        store=store, approval_policy=engine._approval_policy, code_loop=engine._code_loop,
    )
    assert engine.workflow_run(run.id)["status"] == "WAITING"
    run = engine.resume(run.id, reason="Operator reviewed findings and approved another window")
    assert run.state.stage == "CODE_FIX"
    run = drive(engine, run)
    assert run.state.stage == "COMPLETED"
    assert len(gateways["fix"].requests) == 4
    assert run.item_results["T1"]["CODE"].version == "5"
    store.close()


def test_dependency_ordered_two_items_are_independent_changes_against_original_base(tmp_path):
    first = json.loads(make_task_artifact().content["text"])["tasks"][0]
    second = {**first, "id": "T2", "title": "Helper", "dependsOn": ["T1"],
              "expectedFiles": ["helper.py"]}
    task_reply = json.dumps({"tasks": [first, second]})
    engine, run, store, gateways, repository, sandbox = harness(
        tmp_path, task_reply=task_reply, review_replies=[review(), review()],
        exits=[0, 0], implement_replies=[change(), change("helper.py", "def helper(): return 1")],
    )
    run = drive(engine, run)
    assert run.state.stage == "COMPLETED", [(error.code, error.message) for error in run.errors]
    assert run.task_order == ["T1", "T2"]
    assert list(run.item_results) == ["T1", "T2"]
    assert run.item_results["T1"]["CODE"].metadata["taskItemId"] == "T1"
    assert run.item_results["T2"]["CODE"].metadata["taskItemId"] == "T2"
    assert all(item["CODE"].metadata["baseRef"] == "main" for item in run.item_results.values())
    assert [code.changes[0].path for code, _ in sandbox.calls] == ["calculator.py", "helper.py"]
    assert all(len(code.changes) == 1 for code, _ in sandbox.calls)
    assert repository.list_tree("main") == ()
    assert len(gateways["implement"].requests) == 2
    assert not gateways["fix"].requests
    assert len(engine.task(run.id)["artifacts"]) == 9
    store.close()


def test_restart_after_failed_report_does_not_reuse_stale_review_or_report(tmp_path):
    engine, run, store, gateways, _, _ = harness(
        tmp_path, review_replies=[review(), review()], exits=[1, 0], fix_replies=[change()],
    )
    for _ in range(20):
        if run.state.stage == "CODE_FIX":
            break
        run = engine.decide(run.id, reviewer="reviewer", decision="APPROVED") \
            if run.approval_id else engine.tick(run.id)
    assert run.state.stage == "CODE_FIX"
    original_code = run.artifacts["CODE"]
    store.close()
    store = SQLiteExecutionStore(tmp_path / "workflow.sqlite")
    engine = Orchestrator(
        engine._definition, engine._registry, clock=engine._clock, new_id=engine._new_id,
        store=store, approval_policy=engine._approval_policy, code_loop=engine._code_loop,
    )
    run = engine.tick(run.id)
    assert run.state.stage == "CODE_REVIEW"
    assert "CODE_REVIEW" not in run.artifacts and "TEST_REPORT" not in run.artifacts
    assert run.artifacts["CODE"].metadata["revisionOf"] == original_code.id
    assert run.artifacts["CODE"].metadata["fixedTestReportIds"]
    run = drive(engine, run)
    assert run.state.stage == "COMPLETED"
    assert len(gateways["fix"].requests) == 1
    store.close()


def test_default_workflow_stops_at_missing_ci_handler_not_false_completion(tmp_path):
    engine, run, store, _, _, _ = harness(
        tmp_path, review_replies=[review()], exits=[0], with_actions=True,
    )
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "INTEGRATION_UNAVAILABLE"
    assert list(run.item_results) == ["T1"]
    assert not any(result.agent_id == "action:await-merge" for result in run.results)
    store.close()


def test_default_workflow_completes_only_with_explicit_injected_ci_and_merge_handlers(tmp_path):
    engine, run, store, _, _, _ = harness(
        tmp_path, review_replies=[review()], exits=[0], with_actions=True,
    )
    received = []

    def handler(request):
        received.append(request)
        return AgentResult(
            request_id=request.request_id, agent_id=request.agent_id, status="SUCCESS",
            output={"summary": "simulated action"},
            metrics=RunMetrics(duration_seconds=0, revision_count=0, attempt=1),
        )

    engine._actions = {"run-pipeline": handler, "await-merge": handler}
    run = drive(engine, run)
    assert run.state.stage == "COMPLETED"
    assert [request.agent_id for request in received] == [
        "action:run-pipeline", "action:await-merge",
    ]
    assert [artifact.type for artifact in received[0].artifacts] == ["CODE"]
    assert [artifact.type for artifact in received[1].artifacts] == ["CODE_REVIEW", "TEST_REPORT"]
    assert run.errors == []
    store.close()


@pytest.mark.parametrize("defect", ["stale-code-id", "stale-task-id", "inconsistent-verdict"])
def test_stale_or_inconsistent_report_never_dispatches_fix_or_ci(tmp_path, monkeypatch, defect):
    engine, run, store, gateways, _, _ = harness(
        tmp_path, review_replies=[review()], exits=[0],
    )
    reviewer = engine._registry.for_type("review")
    execute = reviewer.execute

    def tamper(request):
        result = execute(request)
        artifact = result.artifacts[0]
        if defect == "stale-code-id":
            artifact.metadata["codeArtifactId"] = "old-code"
        elif defect == "stale-task-id":
            artifact.metadata["taskItemId"] = "T9"
        else:
            artifact.content["review"]["verdict"] = "CHANGES_REQUESTED"
        return result

    monkeypatch.setattr(reviewer, "execute", tamper)
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "VALIDATION_FAILED"
    assert not gateways["fix"].requests
    assert "TEST_REPORT" not in run.artifacts
    store.close()


@pytest.mark.parametrize("version,revision", [("1", "implement-1"), ("2", "old-code")])
def test_wrong_fix_revision_cannot_be_accepted(tmp_path, monkeypatch, version, revision):
    engine, run, store, _, _, _ = harness(
        tmp_path, review_replies=[review("CHANGES_REQUESTED")], exits=[], fix_replies=[change()],
    )
    fixer = engine._registry.for_type("fix")
    execute = fixer.execute

    def tamper(request):
        result = execute(request)
        artifact = result.artifacts[0]
        result.artifacts[0] = artifact.model_copy(update={
            "version": version, "metadata": {**artifact.metadata, "revisionOf": revision},
        })
        return result

    monkeypatch.setattr(fixer, "execute", tamper)
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "VALIDATION_FAILED"
    assert run.artifacts["CODE"].version == "1"
    store.close()


def test_zero_fix_budget_escalates_without_calling_model_and_cannot_resume(tmp_path):
    engine, run, store, gateways, _, _ = harness(
        tmp_path, review_replies=[review("CHANGES_REQUESTED")], exits=[], max_fixes=0,
    )
    run = drive(engine, run)
    assert run.state.stage == "CODE_FIX_ESCALATED"
    assert not gateways["fix"].requests
    with pytest.raises(ValueError, match="zero Fix"):
        engine.resume(run.id, reason="Manual request")
    assert engine.get(run.id).state.stage == "CODE_FIX_ESCALATED"
    store.close()


def test_one_selected_item_mode_does_not_execute_other_items(tmp_path):
    first = json.loads(make_task_artifact().content["text"])["tasks"][0]
    second = {**first, "id": "T2", "title": "Helper", "dependsOn": ["T1"],
              "expectedFiles": ["helper.py"]}
    engine, run, store, gateways, _, _ = harness(
        tmp_path, task_reply=json.dumps({"tasks": [first, second]}),
        review_replies=[review()], exits=[0],
        implement_replies=[change("helper.py", "def helper(): return 1")],
    )
    # Configure the explicit policy before creating a new execution; stored policy is pinned.
    engine._code_loop = CodeLoopPolicy(all_task_items=False)
    run = engine.start(
        task_id="selected-work", project_id="project-1",
        inputs={"spec": {"requirement": "Create a calculator"},
                "implement": {"ref": "main", "taskItemId": "T2"}},
        context={"project": {"testCommands": [["pytest", "-q"]]}},
    )
    run = drive(engine, run)
    assert run.state.stage == "COMPLETED"
    assert run.task_order == ["T2"]
    assert list(run.item_results) == ["T2"]
    assert len(gateways["implement"].requests) == 1
    store.close()


def test_fix_transport_retry_does_not_consume_a_second_rework_slot(tmp_path):
    engine, run, store, gateways, _, _ = harness(
        tmp_path, review_replies=[review("CHANGES_REQUESTED"), review()], exits=[0],
        fix_replies=[ModelGatewayError("LLM_TIMEOUT", "Timeout"), change()],
        code_policy=CodeLoopPolicy(
            max_fixes=1, fix_retry_policy=RetryPolicySettings(
                max_attempts=2, retry_on=["LLM_TIMEOUT"],
            ),
        ),
    )
    run = drive(engine, run)
    assert run.state.stage == "COMPLETED"
    assert len(gateways["fix"].requests) == 2
    assert run.state.revisions["__code_fix"] == 1
    assert run.item_results["T1"]["CODE"].version == "2"
    assert run.errors == []
    assert [result.status for result in run.results if result.agent_id == "agent-fix"] == [
        "FAILED", "SUCCESS",
    ]
    store.close()


def test_fix_budget_is_per_item_and_resets_only_after_passing_review_and_test(tmp_path):
    first = json.loads(make_task_artifact().content["text"])["tasks"][0]
    second = {**first, "id": "T2", "title": "Helper", "dependsOn": ["T1"],
              "expectedFiles": ["helper.py"]}
    engine, run, store, gateways, _, _ = harness(
        tmp_path, task_reply=json.dumps({"tasks": [first, second]}), max_fixes=1,
        review_replies=[review("CHANGES_REQUESTED"), review(),
                        review("CHANGES_REQUESTED", "helper.py"), review()],
        exits=[0, 0],
        implement_replies=[change(), change("helper.py", "def helper(): return 1")],
        fix_replies=[change(), change("helper.py", "def helper(): return 2")],
    )
    run = drive(engine, run)
    assert run.state.stage == "COMPLETED"
    assert len(gateways["fix"].requests) == 2
    assert run.item_results["T1"]["CODE"].version == "2"
    assert run.item_results["T2"]["CODE"].version == "2"
    assert run.state.revisions["__code_fix"] == 1
    store.close()


def test_malformed_dependency_graph_stops_before_implement_model(tmp_path, monkeypatch):
    engine, run, store, gateways, _, _ = harness(
        tmp_path, review_replies=[], exits=[],
    )
    task_agent = engine._registry.for_type("task")
    execute = task_agent.execute

    def tamper(request):
        result = execute(request)
        result.artifacts[0].content["tasks"][0]["dependsOn"] = ["T99"]
        return result

    monkeypatch.setattr(task_agent, "execute", tamper)
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "VALIDATION_FAILED"
    assert not gateways["implement"].requests
    assert not gateways["fix"].requests
    store.close()


def test_conflicting_base_refs_are_rejected_before_execution(tmp_path):
    engine, _, store, gateways, _, _ = harness(tmp_path, review_replies=[], exits=[])
    with pytest.raises(ValueError, match="same base ref"):
        engine.start(task_id="other", project_id="project-1", inputs={
            "implement": {"ref": "main"}, "review": {"ref": "another"},
        })
    assert not any(gateway.requests for gateway in gateways.values())
    store.close()
