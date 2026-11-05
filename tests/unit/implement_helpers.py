"""Shared test helpers for ImplementAgent tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from asf.agents.base import AgentRuntime
from asf.agents.implement.agent import ImplementAgent
from asf.agents.loading import load_implement_prompts
from asf.contracts.models import AgentRequest, Artifact
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from asf.tools.fake import InMemoryRepository
from asf.tools.ports import FileNotFoundInRepository, FileTooLargeError

REPO_ROOT = Path(__file__).resolve().parents[2]
T_AWARE = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)


def counter_id(prefix: str = "id-") -> Callable[[], str]:
    """Create a counter function for generating unique IDs."""
    count = 0

    def _next() -> str:
        nonlocal count
        count += 1
        return f"{prefix}{count}"

    return _next


def make_valid_changeset_reply(
    *,
    changes: list[dict[str, Any]] | None = None,
) -> str:
    """Create a valid ChangeSet reply JSON."""
    if changes is None:
        changes = [
            {
                "path": "src/calculator.py",
                "operation": "create",
                "content": "def add(a, b):\n    return a + b\n",
            }
        ]
    reply = {"changes": changes}
    return json.dumps(reply, indent=2)


def make_spec_artifact(
    *,
    artifact_id: str = "spec-1",
    version: str = "1",
    text: str = "# SPEC: Test Spec\n## Background / Goal\nTest spec content.",
) -> Artifact:
    """Create a valid SPEC artifact."""
    return Artifact(
        id=artifact_id,
        type="SPEC",
        name="SPEC.md",
        version=version,
        content={"format": "markdown", "text": text},
        created_by="agent-spec",
        created_at=T_AWARE,
        metadata={"template": "spec"},
    )


def make_plan_artifact(
    *,
    artifact_id: str = "plan-1",
    version: str = "1",
    text: str = (
        "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n"
        "### M1: Setup\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none\n"
    ),
    spec_artifact_id: str = "spec-1",
    spec_version: str = "1",
) -> Artifact:
    """Create a valid PLAN artifact."""
    return Artifact(
        id=artifact_id,
        type="PLAN",
        name="PLAN.md",
        version=version,
        content={"format": "markdown", "text": text},
        created_by="agent-plan",
        created_at=T_AWARE,
        metadata={
            "template": "plan",
            "specArtifactId": spec_artifact_id,
            "specVersion": spec_version,
        },
    )


def make_task_artifact(
    *,
    artifact_id: str = "task-1",
    version: str = "1",
    tasks: list[dict[str, Any]] | None = None,
    spec_artifact_id: str = "spec-1",
    spec_version: str = "1",
    plan_artifact_id: str = "plan-1",
    plan_version: str = "1",
) -> Artifact:
    """Create a valid TASK artifact matching TaskAgent output shape (camelCase)."""
    if tasks is None:
        tasks = [
            {
                "id": "T1",
                "title": "Create calculator module",
                "milestoneRef": "M1",
                "description": "Implement add, subtract, multiply, divide functions",
                "acceptanceCriteria": [
                    "Function add(a, b) returns a + b",
                    "Function subtract(a, b) returns a - b",
                    "Function multiply(a, b) returns a * b",
                    "Function divide(a, b) returns a / b or raises ValueError for divide by zero",
                ],
                "dependsOn": [],
                "expectedFiles": ["src/calculator.py"],
                "verificationHint": "Run unit tests",
            }
        ]
    task_text = json.dumps({"tasks": tasks}, indent=2)
    return Artifact(
        id=artifact_id,
        type="TASK",
        name="TASK.md",
        version=version,
        content={"format": "json", "text": task_text},
        created_by="agent-task",
        created_at=T_AWARE,
        metadata={
            "template": "task",
            "specArtifactId": spec_artifact_id,
            "specVersion": spec_version,
            "planArtifactId": plan_artifact_id,
            "planVersion": plan_version,
        },
    )


def make_implement_request(
    *,
    spec_artifact: Artifact | None = None,
    plan_artifact: Artifact | None = None,
    task_artifact: Artifact | None = None,
    task_item_id: str = "T1",
    ref: str = "main",
    language: str | None = None,
    agent_id: str = "agent-implement",
    metadata: dict[str, Any] | None = None,
    project_context: dict[str, Any] | None = None,
    expected_files: list[str] | None = None,
) -> AgentRequest:
    """Create a valid AgentRequest for ImplementAgent.

    If expected_files is provided, the default TASK artifact will be updated
    to include expectedFiles in the task item for the given task_item_id.
    """
    spec_art = spec_artifact or make_spec_artifact()
    plan_art = plan_artifact or make_plan_artifact()

    # If expected_files provided and using default task_artifact, update it
    if task_artifact is None:
        default_tasks = [
            {
                "id": task_item_id,
                "title": "Test task",
                "milestoneRef": "M1",
                "description": "Test description",
                "acceptanceCriteria": ["Test criteria"],
                "dependsOn": [],
                "expectedFiles": expected_files or ["src/calculator.py"],
                "verificationHint": "Run tests",
            }
        ]
        task_art = make_task_artifact(tasks=default_tasks)
    else:
        # If task_artifact provided and expected_files given, update the task item
        if expected_files is not None:
            import json as _json

            task_text = task_artifact.content.get("text") if task_artifact.content else None
            if not isinstance(task_text, str):
                raise ValueError("Task artifact content text is missing or not a string")
            task_content = _json.loads(task_text)
            for task in task_content["tasks"]:
                if task.get("id") == task_item_id:
                    task["expectedFiles"] = expected_files
                    break
            updated_text = _json.dumps(task_content, indent=2)
            task_art = task_artifact.model_copy(
                update={"content": {"format": "json", "text": updated_text}}
            )
        else:
            # For custom task artifacts with non-default IDs (e.g., test_full_metadata_injected),
            # ensure the task_item_id exists in the artifact
            import json as _json

            is_default_task_artifact = (
                getattr(task_artifact, "id", None) == "task-1"
                and getattr(task_artifact, "version", None) == "1"
            )
            if not is_default_task_artifact:
                task_text = task_artifact.content.get("text") if task_artifact.content else None
                if isinstance(task_text, str):
                    task_content = _json.loads(task_text)
                    found = any(task.get("id") == task_item_id for task in task_content["tasks"])
                    if not found:
                        default_expected = ["src/calculator.py"]
                        task_content["tasks"].append(
                            {
                                "id": task_item_id,
                                "title": "Test task",
                                "milestoneRef": "M1",
                                "description": "Test description",
                                "acceptanceCriteria": ["Test criteria"],
                                "dependsOn": [],
                                "expectedFiles": default_expected,
                                "verificationHint": "Run tests",
                            }
                        )
                        updated_text = _json.dumps(task_content, indent=2)
                        task_art = task_artifact.model_copy(
                            update={"content": {"format": "json", "text": updated_text}}
                        )
                    else:
                        task_art = task_artifact
                else:
                    task_art = task_artifact
            else:
                task_art = task_artifact

    artifacts = [spec_art, plan_art, task_art]

    inp: dict[str, Any] = {"taskItemId": task_item_id, "ref": ref}
    if language is not None:
        inp["language"] = language

    ctx: dict[str, Any] = {}
    if project_context is not None:
        ctx["project"] = project_context
    else:
        ctx["project"] = {}

    return AgentRequest(
        request_id="req-123",
        task_id="task-456",
        project_id="proj-789",
        workflow_id="software-development",
        agent_id=agent_id,
        input=inp,
        context=ctx,
        artifacts=artifacts,
        metadata=metadata if metadata is not None else {"attempt": 1},
    )


def make_agent_and_gateway(
    script: list[Any],
    *,
    model: str | None = "test-model",
    parameters: dict[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    new_id: Callable[[], str] | None = None,
) -> tuple[ImplementAgent, ScriptedModelGateway]:
    """Create an ImplementAgent with a ScriptedModelGateway."""
    gateway = ScriptedModelGateway(script)
    clk = clock or (lambda: T_AWARE)
    nid = new_id or counter_id("gen-")
    runtime = AgentRuntime(models=gateway, clock=clk, new_id=nid)
    prompts = load_implement_prompts()
    repo = InMemoryRepository()
    agent = ImplementAgent(
        runtime,
        repo,
        prompts=prompts,
        model=model,
        parameters=parameters or {"temperature": 0.3},
        # These helpers back the suites written against the legacy
        # JSON contract: pin it (and no repair loop) explicitly.
        edit_format="json",
        repair_attempts=0,
    )
    return agent, gateway


def make_agent_with_repo(
    script: list[Any],
    repo: InMemoryRepository,
    *,
    model: str | None = "test-model",
    parameters: dict[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    new_id: Callable[[], str] | None = None,
) -> tuple[ImplementAgent, ScriptedModelGateway]:
    """Create an ImplementAgent with a specific InMemoryRepository."""
    gateway = ScriptedModelGateway(script)
    clk = clock or (lambda: T_AWARE)
    nid = new_id or counter_id("gen-")
    runtime = AgentRuntime(models=gateway, clock=clk, new_id=nid)
    prompts = load_implement_prompts()
    agent = ImplementAgent(
        runtime,
        repo,
        prompts=prompts,
        model=model,
        parameters=parameters or {"temperature": 0.3},
        # These helpers back the suites written against the legacy
        # JSON contract: pin it (and no repair loop) explicitly.
        edit_format="json",
        repair_attempts=0,
    )
    return agent, gateway


def make_agent_with_gateway(
    gateway: Any,
    *,
    repo: InMemoryRepository | None = None,
    model: str | None = "test-model",
    parameters: dict[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    new_id: Callable[[], str] | None = None,
) -> ImplementAgent:
    """Create an ImplementAgent with a custom ModelGateway instance."""
    clk = clock or (lambda: T_AWARE)
    nid = new_id or counter_id("gen-")
    runtime = AgentRuntime(models=gateway, clock=clk, new_id=nid)
    prompts = load_implement_prompts()
    repository = repo or InMemoryRepository()
    agent = ImplementAgent(
        runtime,
        repository,
        prompts=prompts,
        model=model,
        parameters=parameters or {"temperature": 0.3},
        # These helpers back the suites written against the legacy
        # JSON contract: pin it (and no repair loop) explicitly.
        edit_format="json",
        repair_attempts=0,
    )
    return agent


# Fake repository/gateway classes for error testing
class FailingRepository(InMemoryRepository):  # type: ignore[misc]
    """Repository that fails on read_file."""

    def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
        raise FileNotFoundInRepository(path, ref)


class TooLargeRepository(InMemoryRepository):  # type: ignore[misc]
    """Repository that raises FileTooLargeError on read_file."""

    def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
        raise FileTooLargeError(path, ref, max_bytes=max_bytes)


class ErrorRepository(InMemoryRepository):  # type: ignore[misc]
    """Repository that raises unexpected error on read_file."""

    def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
        raise RuntimeError("Database connection failed")


class TimeoutGateway:
    """Gateway that raises LLM_TIMEOUT."""

    def complete(self, request: Any) -> None:
        raise ModelGatewayError("LLM_TIMEOUT", "Model request timed out")


class RateLimitGateway:
    """Gateway that raises LLM_RATE_LIMITED."""

    def complete(self, request: Any) -> None:
        raise ModelGatewayError("LLM_RATE_LIMITED", "Rate limit exceeded")


class ModelErrorGateway:
    """Gateway that raises LLM_INVALID_RESPONSE."""

    def complete(self, request: Any) -> None:
        raise ModelGatewayError("LLM_INVALID_RESPONSE", "Internal model error")


class UnexpectedErrorGateway:
    """Gateway that raises unexpected error."""

    def complete(self, request: Any) -> None:
        raise RuntimeError("Unexpected error")
