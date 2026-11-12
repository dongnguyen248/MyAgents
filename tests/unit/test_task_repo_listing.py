"""Task agent repository listing: prompt injection and advisory warnings.

The Task agent used to break a plan down with no knowledge of the
repository, so expectedFiles for existing code were invented paths.
With a repository bound, the prompt carries a bounded tree listing
and a mis-named existing file (a basename twin in the listing) earns
an advisory warning on the TASK artifact, never an error.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from asf.agents._shared.repomap import build_tree_listing
from asf.agents.base import AgentRuntime
from asf.agents.loading import load_task_prompts, load_task_template
from asf.agents.task.agent import TaskAgent, TaskSettings
from asf.contracts.models import AgentRequest, Artifact
from asf.models.fake import ScriptedModelGateway
from asf.tools.fake import InMemoryRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
T_AWARE = datetime(2026, 10, 20, 14, 0, 0, tzinfo=UTC)

TREE_FILES = {
    "Messenger.sln": "sln",
    "Messenger/frmMain.cs": "form",
    "Messenger/Program.cs": "entry",
    "docs/guide.md": "guide",
    "Messenger/bin/Debug/app.exe": "binary",
    "Messenger/obj/Debug/build.cache": "cache",
    "packages/Newtonsoft/lib/net45/Newtonsoft.dll": "dll",
    ".vs/App/v17/state.json": "state",
    "deep/a/b/c/d/e/f.cs": "too deep",
}


def _repo() -> InMemoryRepository:
    return InMemoryRepository({"HEAD": dict(TREE_FILES)})


def _reply(expected_files: list[str]) -> str:
    task = {
        "id": "T1",
        "title": "Investigate the main form",
        "milestoneRef": "M1",
        "description": "Find the root cause in the main form",
        "acceptanceCriteria": ["Root cause named with file and line"],
        "dependsOn": [],
        "expectedFiles": expected_files,
        "verificationHint": "Read the finding document",
    }
    return json.dumps({"tasks": [task]})


def _artifact(artifact_id: str, kind: str, name: str, text: str) -> Artifact:
    return Artifact(
        id=artifact_id,
        type=kind,
        name=name,
        version="1",
        content={"format": "markdown", "text": text},
        created_by="agent-test",
        created_at=T_AWARE,
        metadata={"template": kind.lower()},
    )


def _request() -> AgentRequest:
    spec = _artifact("spec-1", "SPEC", "SPEC.md", "# SPEC\n## Background / Goal\nFix it.")
    plan_text = (
        "# PLAN\n## Milestones\n"
        "### M1: Investigate\n"
        "- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none"
    )
    plan = _artifact("plan-1", "PLAN", "PLAN.md", plan_text)
    plan = plan.model_copy(
        update={"metadata": {"template": "plan", "specArtifactId": "spec-1", "specVersion": "1"}}
    )
    return AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="messenger",
        workflow_id="software-development",
        agent_id="agent-task",
        input={},
        context={"project": {"name": "Messenger", "technology": ["csharp"]}},
        artifacts=[spec, plan],
        metadata={"attempt": 1},
    )


def _agent(reply: str, repository: InMemoryRepository | None) -> tuple[TaskAgent, Any]:
    gateway = ScriptedModelGateway([reply])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "gen-1")
    agent = TaskAgent(
        runtime,
        TaskSettings(
            prompts=load_task_prompts(),
            template=load_task_template(REPO_ROOT / "templates"),
            model="test-model",
        ),
        repository=repository,
    )
    return agent, gateway


def test_tree_listing_prunes_build_output_and_sorts_shallow_first() -> None:
    listing = build_tree_listing(_repo(), ref="HEAD")
    assert "- Messenger/frmMain.cs" in listing.text
    assert "bin/Debug" not in listing.text
    assert "obj/Debug" not in listing.text
    assert "packages/" not in listing.text
    assert ".vs/" not in listing.text
    assert "deep/a" not in listing.text
    assert listing.text.index("Messenger.sln") < listing.text.index("Messenger/frmMain.cs")
    assert set(listing.paths) == {
        "Messenger.sln",
        "Messenger/frmMain.cs",
        "Messenger/Program.cs",
        "docs/guide.md",
    }


def test_tree_listing_truncation_is_visible_and_paths_stay_complete() -> None:
    listing = build_tree_listing(_repo(), ref="HEAD", max_paths=2)
    shown = [line for line in listing.text.splitlines() if line.startswith("- ")]
    assert len(shown) == 2
    assert listing.text.endswith("… 2 more paths not shown")
    assert len(listing.paths) == 4


def test_tree_listing_empty_repository() -> None:
    listing = build_tree_listing(InMemoryRepository(), ref="HEAD")
    assert listing.text == ""
    assert listing.paths == ()


def test_task_prompt_carries_the_repository_listing() -> None:
    agent, gateway = _agent(_reply(["docs/root-cause-finding.md"]), _repo())
    result = agent.execute(_request())
    user_message = gateway.requests[0].messages[1].content
    assert "## Repository files" in user_message
    assert "- Messenger/frmMain.cs" in user_message
    artifact = result.artifacts[0]
    assert "expectedFileWarnings" not in artifact.metadata


def test_task_warning_for_a_case_twin_of_a_listed_file(
    caplog: pytest.LogCaptureFixture,
) -> None:
    agent, _gateway = _agent(_reply(["Messenger/FrmMain.cs"]), _repo())
    with caplog.at_level(logging.WARNING, logger="asf.agents.task.repo_listing"):
        result = agent.execute(_request())
    artifact = result.artifacts[0]
    assert artifact.metadata["expectedFileWarnings"] == [
        {"task": "T1", "path": "Messenger/FrmMain.cs", "similarTo": "Messenger/frmMain.cs"}
    ]
    assert "Messenger/FrmMain.cs" in caplog.text


def test_task_listed_expected_file_earns_no_warning() -> None:
    agent, _gateway = _agent(_reply(["Messenger/frmMain.cs"]), _repo())
    result = agent.execute(_request())
    assert "expectedFileWarnings" not in result.artifacts[0].metadata


def test_task_without_repository_has_no_listing_and_no_warnings() -> None:
    agent, gateway = _agent(_reply(["Messenger/FrmMain.cs"]), None)
    result = agent.execute(_request())
    assert "## Repository files" not in gateway.requests[0].messages[1].content
    assert "expectedFileWarnings" not in result.artifacts[0].metadata
