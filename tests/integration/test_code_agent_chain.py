from __future__ import annotations

import json

import pytest

from asf.agents.base import AgentRuntime
from asf.agents.fix import build_fix_agent
from asf.agents.implement import build_implement_agent
from asf.agents.plan import build_plan_agent
from asf.agents.review import build_review_agent
from asf.agents.spec import build_spec_agent
from asf.agents.task import build_task_agent
from asf.agents.test import build_test_agent
from asf.contracts.models import AgentRequest, Artifact
from asf.models.fake import ScriptedModelGateway
from asf.tools.fake import InMemoryRepository, ScriptedSandbox
from asf.tools.ports import CommandResult
from tests.integration.test_chain import (
    PLATFORM,
    TEMPLATES_DIR,
    make_implement_request,
    make_plan_artifact,
    make_plan_request,
    make_spec_artifact,
    make_spec_request,
    make_task_artifact,
    make_task_request,
)
from tests.unit.contract_models import validator_for
from tests.unit.implement_helpers import T_AWARE, counter_id


def runtime(reply: str | None, prefix: str) -> AgentRuntime:
    return AgentRuntime(
        ScriptedModelGateway([reply] if reply is not None else []),
        lambda: T_AWARE,
        counter_id(prefix),
    )


def upstream_code() -> tuple[AgentRequest, Artifact, InMemoryRepository]:
    spec_agent = build_spec_agent(
        runtime(make_spec_artifact().content["text"], "spec-"), PLATFORM, TEMPLATES_DIR
    )
    spec_result = spec_agent.execute(make_spec_request())
    assert spec_result.status == "SUCCESS"
    spec = spec_result.artifacts[0]
    plan_agent = build_plan_agent(
        runtime(make_plan_artifact().content["text"], "plan-"), PLATFORM, TEMPLATES_DIR
    )
    plan_result = plan_agent.execute(make_plan_request(spec))
    assert plan_result.status == "SUCCESS"
    plan = plan_result.artifacts[0]
    task_agent = build_task_agent(
        runtime(make_task_artifact().content["text"], "task-"), PLATFORM, TEMPLATES_DIR
    )
    task_result = task_agent.execute(make_task_request(spec, plan))
    assert task_result.status == "SUCCESS"
    task = task_result.artifacts[0]
    changes = json.dumps({"changes": [
        {"path": "calculator.py", "operation": "create", "content": "def add(a, b): return a - b"}
    ]})
    repository = InMemoryRepository()
    implement = build_implement_agent(
        runtime(changes, "code-"), PLATFORM, TEMPLATES_DIR, repository
    )
    request = make_implement_request(spec, plan, task, "T1")
    result = implement.execute(request)
    assert result.status == "SUCCESS"
    return request, result.artifacts[0], repository


@pytest.mark.parametrize("failure_source", ["review", "test", "both"])
def test_full_chain_with_fix_and_successful_recheck(failure_source: str):
    request, code, repository = upstream_code()
    upstream = list(request.artifacts)
    review_reply = {
        "findings": (
            [{"severity": "ERROR", "path": "calculator.py", "line": 1,
              "description": "Addition subtracts", "suggestion": "Use addition"}]
            if failure_source in {"review", "both"} else []
        ),
        "verdict": "CHANGES_REQUESTED" if failure_source in {"review", "both"} else "APPROVE",
    }
    review = build_review_agent(
        runtime(json.dumps(review_reply), "review-"), PLATFORM, TEMPLATES_DIR
    )
    review_request = request.model_copy(update={
        "agent_id": "agent-review", "artifacts": [*upstream, code],
    })
    reviewed = review.execute(review_request)
    assert reviewed.status == "SUCCESS"
    assert reviewed.output["verdict"] == review_reply["verdict"]

    exit_code = 1 if failure_source in {"test", "both"} else 0
    test_runtime = runtime(None, "test-")
    tester = build_test_agent(
        test_runtime, PLATFORM, TEMPLATES_DIR,
        ScriptedSandbox(default_result=CommandResult(exit_code, "result", "", 1)),
    )
    test_request = request.model_copy(update={
        "agent_id": "agent-test",
        "artifacts": [next(a for a in upstream if a.type == "TASK"), code],
        "context": {"project": {"testCommands": [["pytest", "-q"]]}},
    })
    tested = tester.execute(test_request)
    assert tested.status == "SUCCESS"
    assert tested.output["verdict"] == ("FAIL" if exit_code else "PASS")
    assert not test_runtime.models.requests

    correction = json.dumps({"changes": [
        {"path": "calculator.py", "operation": "create", "content": "def add(a, b): return a + b"}
    ]})
    fix = build_fix_agent(
        runtime(correction, "fixed-"), PLATFORM, TEMPLATES_DIR, repository
    )
    fix_request = request.model_copy(update={
        "agent_id": "agent-fix",
        "artifacts": [*upstream, code, *reviewed.artifacts, *tested.artifacts],
    })
    fixed = fix.execute(fix_request)
    assert fixed.status == "SUCCESS"
    replacement = fixed.artifacts[0]
    assert replacement.version == "2"
    assert replacement.metadata["revisionOf"] == code.id
    assert replacement.metadata["fixedReviewIds"] == [reviewed.artifacts[0].id]
    assert replacement.metadata["fixedTestReportIds"] == [tested.artifacts[0].id]
    assert repository.list_tree("main") == ()

    reviewer = build_review_agent(
        runtime('{"findings":[],"verdict":"APPROVE"}', "recheck-"),
        PLATFORM, TEMPLATES_DIR,
    )
    rechecked = reviewer.execute(review_request.model_copy(update={
        "artifacts": [*upstream, replacement],
    }))
    assert rechecked.status == "SUCCESS"
    assert rechecked.output["verdict"] == "APPROVE"
    passing_tester = build_test_agent(
        runtime(None, "retest-"), PLATFORM, TEMPLATES_DIR, ScriptedSandbox()
    )
    passed = passing_tester.execute(test_request.model_copy(update={
        "artifacts": [next(a for a in upstream if a.type == "TASK"), replacement],
    }))
    assert passed.status == "SUCCESS"
    assert passed.output["verdict"] == "PASS"
    assert passed.artifacts[0].metadata["codeVersion"] == "2"

    for result in (reviewed, tested, fixed, rechecked, passed):
        validator_for("AgentResult").validate(result.to_contract())
        for artifact in result.artifacts:
            validator_for("Artifact").validate(artifact.to_contract())

    stale = fix.execute(fix_request.model_copy(update={
        "artifacts": [*upstream, replacement, *reviewed.artifacts, *tested.artifacts],
    }))
    assert stale.status == "REJECTED"
