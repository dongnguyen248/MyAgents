from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from asf.agents._shared.model_errors import invalid_response  # noqa: F401  (re-export for fix/review)
from asf.agents.base import Issue
from asf.contracts.models import AgentRequest, Artifact
from asf.tools.changeset import ChangeSet

MAX_CONTEXT_CHARS = 1_000_000
MAX_REPLY_CHARS = 500_000
MAX_TEXT_CHARS = 1_000_000


def artifact_of(request: AgentRequest, kind: str) -> Artifact:
    return next(artifact for artifact in request.artifacts if artifact.type == kind)


def task_item(task: Artifact, task_item_id: str) -> dict[str, Any]:
    content = task.content
    if not isinstance(content, dict):
        raise ValueError("TASK must contain an inline mapping")
    items = content.get("tasks")
    if items is None:
        parsed = json.loads(content.get("text", ""))
        if not isinstance(parsed, dict):
            raise ValueError("TASK text must contain an object")
        items = parsed.get("tasks")
    if not isinstance(items, list):
        raise ValueError("TASK must contain a tasks list")
    matches = [
        item for item in items
        if isinstance(item, dict) and item.get("id") == task_item_id
    ]
    if len(matches) != 1:
        raise ValueError("TASK must contain exactly one matching task item")
    return matches[0]


def code_changeset(code: Artifact) -> ChangeSet:
    if not isinstance(code.content, dict):
        raise ValueError("CODE must contain an inline mapping")
    return ChangeSet.model_validate(code.content.get("changeSet"))


def check_code_request(
    request: AgentRequest,
    agent_id: str,
    required: set[str],
    *,
    optional: set[str] | None = None,
    require_ref: bool = False,
    extra_input: set[str] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    if request.agent_id != agent_id:
        issues.append(Issue("agentId", "agentId does not match this agent"))
    item_id = request.input.get("taskItemId")
    if not isinstance(item_id, str) or re.fullmatch(r"T[1-9][0-9]*", item_id) is None:
        issues.append(Issue("input.taskItemId", "taskItemId must match T[1-9][0-9]*"))
    allowed_input = {"taskItemId", "ref", "language"} | (extra_input or set())
    if set(request.input) - allowed_input:
        issues.append(Issue("input", "Unsupported input fields"))
    if "language" in request.input:
        language = request.input["language"]
        if not isinstance(language, str) or not language.strip():
            issues.append(Issue("input.language", "language must be a non-empty string"))
    if require_ref:
        ref = request.input.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            issues.append(Issue("input.ref", "A non-empty base ref is required"))
    if request.feedback:
        issues.append(Issue("feedback", "Use review/report artifacts, not feedback"))
    attempt = request.metadata.get("attempt", 1)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        issues.append(Issue("metadata.attempt", "attempt must be an integer >= 1"))
    allowed = required | (optional or set())
    for kind in sorted(required):
        if sum(artifact.type == kind for artifact in request.artifacts) != 1:
            issues.append(Issue("artifacts", f"Exactly one {kind} artifact is required"))
    total = 0
    for index, artifact in enumerate(request.artifacts):
        path = f"artifacts[{index}]"
        if artifact.type not in allowed:
            issues.append(Issue(path, "Unsupported artifact type"))
        if re.fullmatch(r"[1-9][0-9]*", artifact.version) is None:
            issues.append(Issue(path + ".version", "Artifact version must be a positive integer"))
        if (
            not isinstance(artifact.content, dict)
            or not isinstance(artifact.content.get("text"), str)
            or not artifact.content["text"].strip()
        ):
            issues.append(Issue(path + ".content.text", "Non-empty inline text is required"))
        elif isinstance(artifact.content["text"], str):
            try:
                total += len(json.dumps(artifact.content, ensure_ascii=True))
            except (TypeError, ValueError):
                issues.append(
                    Issue(path + ".content", "Artifact content must be JSON serializable")
                )
        if artifact.type == "CODE":
            if artifact.metadata.get("taskItemId") != item_id:
                issues.append(Issue(path + ".metadata.taskItemId", "CODE task item does not match"))
            base_ref = artifact.metadata.get("baseRef")
            if not isinstance(base_ref, str) or not base_ref.strip():
                issues.append(Issue(path + ".metadata.baseRef", "CODE baseRef is required"))
            try:
                code_changeset(artifact)
            except (ValueError, ValidationError):
                issues.append(Issue(path + ".content.changeSet", "Invalid CODE ChangeSet"))
    if total > MAX_CONTEXT_CHARS:
        issues.append(Issue("artifacts", "Artifact context exceeds the size limit"))
    tasks = [artifact for artifact in request.artifacts if artifact.type == "TASK"]
    if len(tasks) == 1 and isinstance(item_id, str):
        try:
            task_item(tasks[0], item_id)
        except (ValueError, TypeError):
            issues.append(Issue("artifacts.TASK", "TASK has no unique matching task item"))
    if not issues:
        by_kind = {artifact.type: artifact for artifact in request.artifacts}
        task = by_kind.get("TASK")
        plan = by_kind.get("PLAN")
        spec = by_kind.get("SPEC")
        code = by_kind.get("CODE")
        links: dict[str, str] = {}
        if spec is not None:
            links.update(specArtifactId=spec.id, specVersion=spec.version)
        if plan is not None:
            links.update(planArtifactId=plan.id, planVersion=plan.version)
        if task is not None:
            links.update(taskArtifactId=task.id, taskVersion=task.version)
        for key, value in links.items():
            if code is not None and code.metadata.get(key) != value:
                issues.append(Issue("artifacts.CODE.metadata." + key, "Stale CODE traceability"))
        for downstream, upstream in ((task, spec), (task, plan), (plan, spec)):
            if downstream is not None and upstream is not None:
                prefix = upstream.type.lower()
                if (
                    downstream.metadata.get(prefix + "ArtifactId") != upstream.id
                    or downstream.metadata.get(prefix + "Version") != upstream.version
                ):
                    issues.append(Issue("artifacts", "Stale upstream traceability"))
    return issues


def linked_metadata(request: AgentRequest, code: Artifact) -> dict[str, Any]:
    metadata = {
        key: value for key, value in code.metadata.items()
        if key in {
            "specArtifactId", "specVersion", "planArtifactId", "planVersion",
            "taskArtifactId", "taskVersion", "taskItemId", "baseRef",
        }
    }
    metadata.update(codeArtifactId=code.id, codeVersion=code.version)
    return metadata

