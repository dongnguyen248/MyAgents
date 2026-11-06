"""Golden tests for the assembled model prompts (Phase 11a).

Each test runs one AI agent end to end against a scripted gateway
with a fixed request whose project context carries skills and
review rules, then compares the messages of the first model
request byte-for-byte with the golden file in tests/golden/prompts.
Capturing at the gateway boundary keeps the goldens valid across
internal refactors of the prompt builders (parameter objects,
extracted helpers): any diff means the prompt the model receives
changed.

Regenerate (only when a prompt change is intended and reviewed):
    ASF_UPDATE_GOLDENS=1 pytest tests/unit/test_prompt_goldens.py
"""

from __future__ import annotations

import itertools
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from asf.agents.base import AgentRuntime
from asf.agents.fix.agent import FixAgent, FixSettings
from asf.agents.implement.agent import ImplementAgent, ImplementSettings
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
from asf.agents.plan.agent import PlanAgent, PlanSettings
from asf.agents.review.agent import ReviewAgent
from asf.agents.spec.agent import SpecAgent, SpecSettings
from asf.agents.task.agent import TaskAgent, TaskSettings
from asf.contracts.models import AgentRequest, Artifact, ModelRequest
from asf.models.fake import ScriptedModelGateway
from asf.tools.fake import InMemoryRepository
from tests.unit.implement_helpers import (
    make_agent_and_gateway,
    make_implement_request,
    make_valid_changeset_reply,
)
from tests.unit.test_task_agent import make_valid_task_reply

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden" / "prompts"
NOW = datetime(2026, 11, 2, tzinfo=UTC)

PROJECT: dict[str, Any] = {
    "name": "AuthService",
    "description": "Handles authentication",
    "technology": ["python", "fastapi"],
    "skills": [
        {"id": "general", "content": "GENERAL SKILL BODY"},
        {"id": "code-structure", "content": "CODE STRUCTURE SKILL BODY"},
        {"id": "git", "content": "GIT SKILL BODY"},
    ],
    "reviewRules": "GOLDEN RULES TEXT",
}

FIX_BLOCKS_REPLY = (
    "FILE: src/calculator.py\n"
    "<<<<<<< SEARCH\n"
    "def add(a, b):\n"
    "    return a + b\n"
    "=======\n"
    "def add(a, b):\n"
    "    return a + b + 0\n"
    ">>>>>>> REPLACE\n"
)

IMPLEMENT_BLOCKS_REPLY = (
    "CREATE: src/calculator.py\n<<<<<<< FILE\ndef add(a, b):\n    return a + b\n>>>>>>> FILE\n"
)


def counter_id(prefix: str = "gen-"):
    count = itertools.count(1)
    return lambda: f"{prefix}{next(count)}"


def runtime_for(gateway: ScriptedModelGateway) -> AgentRuntime:
    return AgentRuntime(models=gateway, clock=lambda: NOW, new_id=counter_id())


def base_request(agent_id: str, **overrides: Any) -> AgentRequest:
    fields: dict[str, Any] = {
        "request_id": "req-123",
        "task_id": "task-456",
        "project_id": "proj-789",
        "workflow_id": "software-development",
        "agent_id": agent_id,
        "input": {},
        "context": {"project": PROJECT},
        "artifacts": [],
        "feedback": [],
        "metadata": {"attempt": 1},
    }
    fields.update(overrides)
    return AgentRequest(**fields)


def markdown_artifact(
    kind: str,
    artifact_id: str,
    text: str,
    *,
    created_by: str,
    metadata: dict[str, Any] | None = None,
) -> Artifact:
    return Artifact(
        id=artifact_id,
        type=kind,
        name=f"{kind}.md",
        version="1",
        content={"format": "markdown", "text": text},
        created_by=created_by,
        created_at=NOW,
        metadata=metadata or {},
    )


SPEC_ARTIFACT = markdown_artifact(
    "SPEC",
    "spec-123",
    "# SPEC: Test Spec\n## Background / Goal\nTest spec content.",
    created_by="agent-spec",
    metadata={"template": "spec"},
)

PLAN_ARTIFACT = markdown_artifact(
    "PLAN",
    "plan-123",
    (
        "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n"
        "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
        "### M2: Core\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: M1"
    ),
    created_by="agent-plan",
    metadata={"template": "plan", "specArtifactId": "spec-123", "specVersion": "1"},
)


def spec_valid_reply(sections: list[str]) -> str:
    lines = ["# SPEC: Test Specification"]
    for section in sections:
        lines.append(section)
        lines.append("Section details content.")
    return "\n\n".join(lines)


def plan_valid_reply(sections: list[str]) -> str:
    lines = ["# PLAN: Test Plan"]
    for section in sections:
        lines.append(section)
        if section == "## Linked SPEC":
            lines.append("ID: spec-123")
            lines.append("Version: 1")
        else:
            lines.append("Section details content.")
    lines.append("## Milestones")
    lines.append("### M1: Setup")
    lines.append("- Deliverables: Project scaffold")
    lines.append("- Acceptance criteria: Project builds and runs")
    lines.append("- Depends on: none")
    lines.append("### M2: Core Implementation")
    lines.append("- Deliverables: Core modules")
    lines.append("- Acceptance criteria: All unit tests pass")
    lines.append("- Depends on: M1")
    return "\n\n".join(lines)


def capture_spec() -> ModelRequest:
    template = load_spec_template(REPO_ROOT / "templates")
    gateway = ScriptedModelGateway([spec_valid_reply(template.required_sections)])
    agent = SpecAgent(
        runtime_for(gateway),
        SpecSettings(
            prompts=load_spec_prompts(),
            template=template,
            model="test-model",
            parameters={"temperature": 0.3},
        ),
    )
    request = base_request(
        "agent-spec",
        input={"requirement": "Build user authentication service", "language": "en"},
    )
    result = agent.execute(request)
    assert result.status == "SUCCESS", result.errors
    return gateway.requests[0]


def capture_plan() -> ModelRequest:
    template = load_plan_template(REPO_ROOT / "templates")
    gateway = ScriptedModelGateway([plan_valid_reply(template.required_sections)])
    agent = PlanAgent(
        runtime_for(gateway),
        PlanSettings(
            prompts=load_plan_prompts(),
            template=template,
            model="test-model",
            parameters={"temperature": 0.3},
        ),
    )
    request = base_request("agent-plan", input={"language": "en"}, artifacts=[SPEC_ARTIFACT])
    result = agent.execute(request)
    assert result.status == "SUCCESS", result.errors
    return gateway.requests[0]


def capture_task() -> ModelRequest:
    gateway = ScriptedModelGateway(
        [
            make_valid_task_reply(
                spec_id="spec-123",
                spec_version="1",
                plan_id="plan-123",
                plan_version="1",
                task_count=3,
                milestones=[("M1", "Setup"), ("M2", "Core")],
            )
        ]
    )
    agent = TaskAgent(
        runtime_for(gateway),
        TaskSettings(
            prompts=load_task_prompts(),
            template=load_task_template(REPO_ROOT / "templates"),
            model="test-model",
            parameters={"temperature": 0.3},
        ),
    )
    request = base_request(
        "agent-task",
        input={"language": "en"},
        artifacts=[SPEC_ARTIFACT, PLAN_ARTIFACT],
    )
    result = agent.execute(request)
    assert result.status == "SUCCESS", result.errors
    return gateway.requests[0]


def capture_implement() -> ModelRequest:
    gateway = ScriptedModelGateway([IMPLEMENT_BLOCKS_REPLY])
    agent = ImplementAgent(
        runtime_for(gateway),
        InMemoryRepository(),
        ImplementSettings(
            prompts=load_implement_prompts(),
            model="test-model",
            parameters={"temperature": 0.3},
        ),
    )
    request = make_implement_request(project_context=PROJECT)
    result = agent.execute(request)
    assert result.status == "SUCCESS", result.errors
    return gateway.requests[0]


def capture_fix() -> ModelRequest:
    request = make_implement_request(project_context=PROJECT)
    implement, _ = make_agent_and_gateway([make_valid_changeset_reply()])
    implemented = implement.execute(request)
    assert implemented.status == "SUCCESS", implemented.errors
    code = implemented.artifacts[0]
    review = Artifact(
        id="review-1",
        type="CODE_REVIEW",
        name="CODE_REVIEW.md",
        version="1",
        content={
            "format": "json",
            "text": "Changes requested",
            "review": {"findings": [], "verdict": "CHANGES_REQUESTED"},
        },
        created_by="agent-review",
        created_at=NOW,
        metadata={
            "codeArtifactId": code.id,
            "codeVersion": code.version,
            "taskItemId": "T1",
        },
    )
    fix_request = request.model_copy(
        update={
            "agent_id": "agent-fix",
            "artifacts": [*request.artifacts, code, review],
        }
    )
    gateway = ScriptedModelGateway([FIX_BLOCKS_REPLY])
    agent = FixAgent(
        runtime_for(gateway),
        InMemoryRepository(),
        FixSettings(
            prompts=load_fix_prompts(),
            model="test-model",
            parameters={"temperature": 0.3},
        ),
    )
    result = agent.execute(fix_request)
    assert result.status == "SUCCESS", result.errors
    return gateway.requests[0]


def capture_review() -> ModelRequest:
    def artifact(kind: str, metadata: dict[str, Any], **content: Any) -> Artifact:
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

    spec_link = {"specArtifactId": "spec-1", "specVersion": "1"}
    plan_link = {**spec_link, "planArtifactId": "plan-1", "planVersion": "1"}
    code_link = {
        **plan_link,
        "taskArtifactId": "task-1",
        "taskVersion": "1",
        "taskItemId": "T1",
        "baseRef": "base-ref",
    }
    request = AgentRequest(
        request_id="request-review",
        task_id="workflow-task",
        project_id="project-review",
        workflow_id="workflow-review",
        agent_id="agent-review",
        input={"taskItemId": "T1"},
        context={"project": PROJECT},
        artifacts=[
            artifact("SPEC", {}),
            artifact("PLAN", spec_link),
            artifact(
                "TASK",
                plan_link,
                tasks=[
                    {
                        "id": "T1",
                        "description": "Implement the unit",
                        "expectedFiles": ["src/unit.py", "old.py"],
                    }
                ],
            ),
            artifact(
                "CODE",
                code_link,
                changeSet={
                    "changes": [
                        {
                            "path": "src/unit.py",
                            "operation": "create",
                            "content": "value = 1\n",
                        },
                        {"path": "old.py", "operation": "delete"},
                    ]
                },
            ),
        ],
    )
    gateway = ScriptedModelGateway(['{"findings": [], "verdict": "APPROVE"}'])
    agent = ReviewAgent(
        runtime_for(gateway),
        prompts=load_review_prompts(),
        model="review-model",
        parameters={"temperature": 0.1},
    )
    result = agent.execute(request)
    assert result.status == "SUCCESS", result.errors
    return gateway.requests[0]


CAPTURES = {
    "spec": capture_spec,
    "plan": capture_plan,
    "task": capture_task,
    "implement": capture_implement,
    "fix": capture_fix,
    "review": capture_review,
}


def serialize(request: ModelRequest) -> str:
    blocks = [f"=== {message.role} ===\n{message.content}" for message in request.messages]
    return "\n".join(blocks) + "\n"


@pytest.mark.parametrize("agent_name", sorted(CAPTURES))
def test_assembled_prompt_matches_golden(agent_name: str) -> None:
    text = serialize(CAPTURES[agent_name]())
    golden = GOLDEN_DIR / f"{agent_name}.txt"
    if os.environ.get("ASF_UPDATE_GOLDENS") == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden.write_text(text, encoding="utf-8")
        return
    assert golden.exists(), f"missing golden {golden}; run with ASF_UPDATE_GOLDENS=1"
    assert text == golden.read_text(encoding="utf-8"), (
        f"assembled prompt for {agent_name} changed; if intended, "
        "regenerate with ASF_UPDATE_GOLDENS=1 and review the diff"
    )
