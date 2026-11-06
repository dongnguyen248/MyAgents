"""Round-trip wiring: every harness component reaches the default path.

For each agent, a harness Tree is written into a temp copy of the
agent's package; the prompts are then loaded from that copy through
the same loader helpers the runtime uses and assembled with no
override (the default path). The assembled messages and the
fingerprint must equal those of the override path built from the
same tree, for the unmodified tree and for a tree with any single
component mutated — proving no component is silently dropped or
read from anywhere else (the pre-H3 tool-guidance defect).
"""

from __future__ import annotations

import importlib
import importlib.resources
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from asf.agents._shared.codegen import FixContext
from asf.agents._shared.harness import HarnessComponents, fingerprint
from asf.agents.fix.prompts import FixMessageOptions, FixPrompts, build_fix_messages
from asf.agents.implement.prompts import (
    ImplementPromptContext,
    ImplementPrompts,
    build_implement_messages,
)
from asf.agents.loading import (
    _load_agent_prompts,
    _load_prompt_pair,
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
from asf.agents.plan.prompts import PlanPromptContext, PlanPrompts, build_plan_messages
from asf.agents.review.prompts import ReviewPrompts, build_review_messages
from asf.agents.spec.prompts import SpecPromptContext, SpecPrompts, build_spec_messages
from asf.agents.task.prompts import TaskPromptContext, TaskPrompts, build_task_messages
from asf.contracts.models import AgentRequest, Artifact
from harness.harness2.bundle import (
    AGENT_PACKAGES,
    default_tree,
    load_default_components,
    tree_to_components,
)
from harness.harness2.surface import REVISION_PATH, Tree, write_tree
from tests.unit.test_harness_prompt_goldens import PLAN_ARTIFACT, SPEC_ARTIFACT, TASK_ARTIFACT

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "templates"
NOW = datetime(2026, 11, 2, tzinfo=UTC)
MARKER = "WIRING PROBE MARKER"
PROBE_SKILL_PATH = "skills/probe/SKILL.md"
AGENTS = sorted(AGENT_PACKAGES)

PUBLIC_LOADERS = {
    "spec": load_spec_prompts,
    "plan": load_plan_prompts,
    "task": load_task_prompts,
    "implement": load_implement_prompts,
    "review": load_review_prompts,
    "fix": load_fix_prompts,
}


def _load_from_package(agent: str, package: str) -> Any:
    if agent == "spec":
        return _load_prompt_pair(package, agent, SpecPrompts)
    if agent == "plan":
        return _load_prompt_pair(package, agent, PlanPrompts)
    if agent == "task":
        return _load_prompt_pair(package, agent, TaskPrompts)
    if agent == "implement":
        return _load_agent_prompts(
            package, agent, strict=False, tool_guidance=True, build=ImplementPrompts
        )
    if agent == "review":
        return _load_agent_prompts(
            package, agent, strict=True, tool_guidance=False, build=ReviewPrompts
        )
    return _load_agent_prompts(package, agent, strict=True, tool_guidance=True, build=FixPrompts)


def _load_from_tree(root: Path, monkeypatch: pytest.MonkeyPatch, agent: str, tree: Tree) -> Any:
    source = Path(str(importlib.resources.files(AGENT_PACKAGES[agent])))
    module_name = f"tmp_harness_{agent}"
    target = root / module_name
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    write_tree(target, tree)
    monkeypatch.syspath_prepend(str(root))
    sys.modules.pop(module_name, None)
    importlib.import_module(module_name)
    try:
        return _load_from_package(agent, module_name)
    finally:
        sys.modules.pop(module_name, None)


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
                "changes": [{"path": "src/unit.py", "operation": "create", "content": "value = 1\n"}]
            },
        ),
    ]


def _request(agent_id: str) -> AgentRequest:
    return AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id=agent_id,
        input={"taskItemId": "T1", "ref": "base-ref"},
        context={},
        artifacts=_review_artifacts(),
        feedback=[],
        metadata={"attempt": 1},
    )


def _fix_context() -> FixContext:
    return FixContext(
        task_id="T1",
        spec_summary="spec",
        plan_summary="plan",
        task_summary="task",
        expected_files=("src/unit.py",),
        existing_files={},
        review_findings=(),
        previous_changeset=None,
    )


def _assemble(agent: str, prompts: Any, harness: HarnessComponents | None, revision: bool) -> str:
    builders = {
        "spec": _assemble_spec,
        "plan": _assemble_plan,
        "task": _assemble_task,
        "implement": _assemble_implement,
        "review": _assemble_review,
        "fix": _assemble_fix,
    }
    return builders[agent](prompts, harness, revision)


def _assemble_spec(prompts: Any, harness: HarnessComponents | None, revision: bool) -> str:
    context = SpecPromptContext(
        prompts=prompts,
        template=load_spec_template(TEMPLATES),
        requirement="Build a calculator",
        language="en",
        project_context=None,
        previous_spec=("1", "previous spec text") if revision else None,
        harness=harness,
    )
    return "\n".join(message.content for message in build_spec_messages(context))


def _assemble_plan(prompts: Any, harness: HarnessComponents | None, revision: bool) -> str:
    context = PlanPromptContext(
        prompts=prompts,
        template=load_plan_template(TEMPLATES),
        spec_artifact=SPEC_ARTIFACT,
        language="en",
        project_context=None,
        previous_plan=("1", "previous plan text") if revision else None,
        harness=harness,
    )
    return "\n".join(message.content for message in build_plan_messages(context))


def _assemble_task(prompts: Any, harness: HarnessComponents | None, revision: bool) -> str:
    context = TaskPromptContext(
        prompts=prompts,
        template=load_task_template(TEMPLATES),
        spec_artifact=SPEC_ARTIFACT,
        plan_artifact=PLAN_ARTIFACT,
        language="en",
        project_context=None,
        previous_task=("1", "previous task text") if revision else None,
        harness=harness,
    )
    return "\n".join(message.content for message in build_task_messages(context))


def _assemble_implement(prompts: Any, harness: HarnessComponents | None, revision: bool) -> str:
    context = ImplementPromptContext(
        prompts=prompts,
        spec_artifact=SPEC_ARTIFACT,
        plan_artifact=PLAN_ARTIFACT,
        task_artifact=TASK_ARTIFACT,
        task_item_id="T1",
        existing_files={},
        language="en",
        project_context=None,
        harness=harness,
    )
    return "\n".join(message.content for message in build_implement_messages(context))


def _assemble_review(prompts: Any, harness: HarnessComponents | None, revision: bool) -> str:
    messages = build_review_messages(
        prompts=prompts, request=_request("agent-review"), harness=harness
    )
    return "\n".join(message.content for message in messages)


def _assemble_fix(prompts: Any, harness: HarnessComponents | None, revision: bool) -> str:
    options = FixMessageOptions(harness=harness)
    messages = build_fix_messages(prompts, _request("agent-fix"), _fix_context(), options)
    return "\n".join(message.content for message in messages)


@pytest.mark.parametrize("agent", AGENTS)
def test_default_path_matches_override_path(agent: str) -> None:
    tree = default_tree(agent)
    components = tree_to_components(tree, agent)
    prompts = PUBLIC_LOADERS[agent]()
    assert prompts.to_components() == components
    assert prompts.to_components() == load_default_components(agent)
    assert fingerprint(prompts.to_components()) == fingerprint(components)
    for revision in (False, True):
        default_text = _assemble(agent, prompts, None, revision)
        override_text = _assemble(agent, prompts, components, revision)
        assert default_text == override_text


@pytest.mark.parametrize("agent", AGENTS)
def test_every_component_round_trips_through_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: str
) -> None:
    base_tree = default_tree(agent)
    base_fingerprint = fingerprint(tree_to_components(base_tree, agent))
    for index, path in enumerate([*sorted(base_tree), PROBE_SKILL_PATH]):
        tree = dict(base_tree)
        tree[path] = tree.get(path, "") + f"\n{MARKER}\n"
        prompts = _load_from_tree(tmp_path / f"case{index}", monkeypatch, agent, tree)
        components = tree_to_components(tree, agent)
        assert fingerprint(prompts.to_components()) == fingerprint(components), path
        assert fingerprint(prompts.to_components()) != base_fingerprint, path
        revision = path == REVISION_PATH
        default_text = _assemble(agent, prompts, None, revision)
        override_text = _assemble(agent, prompts, components, revision)
        assert default_text == override_text, path
        assert MARKER in default_text, path
