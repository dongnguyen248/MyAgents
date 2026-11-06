"""Golden tests for the assembled *system* prompt of every AI agent (Phase 11b, H1).

The goldens in `tests/golden/harness/` were captured from the code
*before* the HarnessComponents refactor. After the refactor, the
default harness (contract + system, new components empty) must
assemble byte-identical system prompts in every scenario: with and
without revision, with and without skills/rules.

Regenerate (only for an intended, reviewed prompt change):
    ASF_UPDATE_GOLDENS=1 pytest tests/unit/test_harness_prompt_goldens.py
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from asf.agents._shared.codegen import FixContext
from asf.agents.fix.prompts import build_fix_messages
from asf.agents.implement.prompts import ImplementPromptContext, build_implement_messages
from asf.agents.loading import (
    load_fix_prompts,
    load_implement_prompts,
    load_plan_prompts,
    load_plan_template,
    load_review_prompts,
    load_spec_prompts,
    load_spec_template,
    load_task_prompts,
    load_task_template,
)
from asf.agents.plan.prompts import PlanPromptContext, build_plan_messages
from asf.agents.review.prompts import build_review_messages
from asf.agents.spec.prompts import SpecPromptContext, build_spec_messages
from asf.agents.task.prompts import TaskPromptContext, build_task_messages
from asf.contracts.models import AgentRequest, ApprovalFeedback, Artifact

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden" / "harness"
NOW = datetime(2026, 11, 2, tzinfo=UTC)

PROJECT: dict[str, Any] = {
    "name": "AuthService",
    "description": "Handles authentication",
    "technology": ["python", "fastapi"],
    "enabledSkills": ["general", "code-structure", "git"],
    "skills": [
        {"id": "general", "content": "GENERAL SKILL BODY"},
        {"id": "code-structure", "content": "CODE STRUCTURE SKILL BODY"},
        {"id": "git", "content": "GIT SKILL BODY"},
    ],
    "reviewRules": "GOLDEN RULES TEXT",
}

FEEDBACK = [
    ApprovalFeedback(
        approvalId="appr-1",
        reviewer="qa",
        decision="REQUEST_CHANGES",
        comment="Narrow the scope",
    )
]

SPEC_ARTIFACT: dict[str, Any] = {
    "id": "spec-123",
    "version": "1",
    "content": {"format": "markdown", "text": "# SPEC\nspec body"},
}
PLAN_ARTIFACT: dict[str, Any] = {
    "id": "plan-123",
    "version": "1",
    "content": {"format": "markdown", "text": "# PLAN\nplan body"},
}
TASK_ARTIFACT: dict[str, Any] = {
    "id": "task-123",
    "version": "1",
    "content": {
        "format": "json",
        "text": "task text",
        "tasks": [
            {
                "id": "T1",
                "title": "Do it",
                "description": "Do the thing",
                "acceptanceCriteria": ["It works"],
                "expectedFiles": ["src/unit.py"],
                "verificationHint": "Run tests",
            }
        ],
    },
}


def _spec_system(project: dict[str, Any] | None, revision: bool) -> str:
    context = SpecPromptContext(
        prompts=load_spec_prompts(),
        template=load_spec_template(REPO_ROOT / "templates"),
        requirement="Build user authentication service",
        language="en",
        project_context=project,
        previous_spec=("1", "previous spec text") if revision else None,
        feedback=FEEDBACK if revision else (),
    )
    return build_spec_messages(context)[0].content


def _plan_system(project: dict[str, Any] | None, revision: bool) -> str:
    context = PlanPromptContext(
        prompts=load_plan_prompts(),
        template=load_plan_template(REPO_ROOT / "templates"),
        spec_artifact=SPEC_ARTIFACT,
        language="en",
        project_context=project,
        previous_plan=("1", "previous plan text") if revision else None,
        feedback=FEEDBACK if revision else (),
    )
    return build_plan_messages(context)[0].content


def _task_system(project: dict[str, Any] | None, revision: bool) -> str:
    context = TaskPromptContext(
        prompts=load_task_prompts(),
        template=load_task_template(REPO_ROOT / "templates"),
        spec_artifact=SPEC_ARTIFACT,
        plan_artifact=PLAN_ARTIFACT,
        language="en",
        project_context=project,
        previous_task=("1", "previous task text") if revision else None,
        feedback=FEEDBACK if revision else (),
    )
    return build_task_messages(context)[0].content


def _implement_system(project: dict[str, Any] | None) -> str:
    context = ImplementPromptContext(
        prompts=load_implement_prompts(),
        spec_artifact=SPEC_ARTIFACT,
        plan_artifact=PLAN_ARTIFACT,
        task_artifact=TASK_ARTIFACT,
        task_item_id="T1",
        existing_files={},
        language="en",
        project_context=json.dumps(project) if project is not None else None,
    )
    return build_implement_messages(context)[0].content


def _artifact(kind: str, metadata: dict[str, Any], **content: Any) -> Artifact:
    return Artifact(
        id=f"{kind.lower()}-1",
        type=kind,
        name=f"{kind}.json",
        version="1",
        content={"format": "json", "text": f"{kind} inline context", **content},
        created_by=f"agent-{kind.lower()}",
        created_at=NOW,
        metadata=metadata,
    )


def _review_artifacts() -> list[Artifact]:
    spec_link = {"specArtifactId": "spec-1", "specVersion": "1"}
    plan_link = {**spec_link, "planArtifactId": "plan-1", "planVersion": "1"}
    code_link = {
        **plan_link,
        "taskArtifactId": "task-1",
        "taskVersion": "1",
        "taskItemId": "T1",
        "baseRef": "base-ref",
    }
    return [
        _artifact("SPEC", {}),
        _artifact("PLAN", spec_link),
        _artifact(
            "TASK",
            plan_link,
            tasks=[
                {"id": "T1", "description": "Implement the unit", "expectedFiles": ["src/unit.py"]}
            ],
        ),
        _artifact(
            "CODE",
            code_link,
            changeSet={
                "changes": [
                    {"path": "src/unit.py", "operation": "create", "content": "value = 1\n"},
                ]
            },
        ),
    ]


def _request(agent_id: str, project: dict[str, Any] | None, **overrides: Any) -> AgentRequest:
    fields: dict[str, Any] = {
        "request_id": "req-1",
        "task_id": "task-1",
        "project_id": "proj-1",
        "workflow_id": "software-development",
        "agent_id": agent_id,
        "input": {"taskItemId": "T1", "ref": "base-ref"},
        "context": {"project": project} if project is not None else {},
        "artifacts": _review_artifacts(),
        "feedback": [],
        "metadata": {"attempt": 1},
    }
    fields.update(overrides)
    return AgentRequest(**fields)


def _review_system(project: dict[str, Any] | None) -> str:
    messages = build_review_messages(
        prompts=load_review_prompts(),
        request=_request("agent-review", project),
    )
    return messages[0].content


def _fix_system(project: dict[str, Any] | None) -> str:
    context = FixContext(
        task_id="T1",
        spec_summary="spec",
        plan_summary="plan",
        task_summary="task",
        expected_files=("src/unit.py",),
        existing_files={},
        review_findings=(),
        previous_changeset=None,
    )
    messages = build_fix_messages(load_fix_prompts(), _request("agent-fix", project), context)
    return messages[0].content


def _scenarios() -> dict[str, str]:
    texts: dict[str, str] = {}
    for agent, builder in (
        ("spec", _spec_system),
        ("plan", _plan_system),
        ("task", _task_system),
    ):
        texts[f"{agent}__plain"] = builder(None, False)
        texts[f"{agent}__rules-skills"] = builder(PROJECT, False)
        texts[f"{agent}__revision"] = builder(None, True)
        texts[f"{agent}__revision-rules-skills"] = builder(PROJECT, True)
    for agent, builder in (
        ("implement", _implement_system),
        ("review", _review_system),
        ("fix", _fix_system),
    ):
        texts[f"{agent}__plain"] = builder(None)
        texts[f"{agent}__rules-skills"] = builder(PROJECT)
    return texts


SCENARIOS = sorted(_scenarios())


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_system_prompt_matches_golden(scenario: str) -> None:
    text = _scenarios()[scenario]
    golden = GOLDEN_DIR / f"{scenario}.txt"
    if os.environ.get("ASF_UPDATE_GOLDENS") == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden.write_text(text, encoding="utf-8")
        return
    assert golden.exists(), f"missing golden {golden}; run with ASF_UPDATE_GOLDENS=1"
    assert text == golden.read_text(encoding="utf-8"), (
        f"assembled system prompt for {scenario} changed; if intended, "
        "regenerate with ASF_UPDATE_GOLDENS=1 and review the diff"
    )
