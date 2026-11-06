from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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


def task_items_from_content(content: Any) -> list[dict[str, Any]]:
    """The raw task-item dicts of a TASK artifact's content.

    The one place that knows the two storage shapes: an inline
    ``tasks`` list, or the rendered ``text`` carrying the same list
    as JSON. Raises ValueError on malformed shapes.
    """
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
    return [item for item in items if isinstance(item, dict)]


def task_items(task: Artifact) -> list[dict[str, Any]]:
    return task_items_from_content(task.content)


def task_item(task: Artifact, task_item_id: str) -> dict[str, Any]:
    matches = [item for item in task_items(task) if item.get("id") == task_item_id]
    if len(matches) != 1:
        raise ValueError("TASK must contain exactly one matching task item")
    return matches[0]


def code_changeset(code: Artifact) -> ChangeSet:
    if not isinstance(code.content, dict):
        raise ValueError("CODE must contain an inline mapping")
    return ChangeSet.model_validate(code.content.get("changeSet"))


@dataclass(frozen=True)
class CodeRequestRules:
    """Which artifacts and inputs a code agent's request must carry."""

    agent_id: str
    required: set[str]
    optional: set[str] = field(default_factory=set)
    require_ref: bool = False
    extra_input: set[str] = field(default_factory=set)


def check_code_request(request: AgentRequest, rules: CodeRequestRules) -> list[Issue]:
    issues, item_id = _header_issues(request, rules)
    issues.extend(_required_count_issues(request, rules.required))
    allowed = rules.required | rules.optional
    artifact_issues, total = _artifact_issues(request, allowed, item_id)
    issues.extend(artifact_issues)
    if total > MAX_CONTEXT_CHARS:
        issues.append(Issue("artifacts", "Artifact context exceeds the size limit"))
    issues.extend(_task_item_issue(request, item_id))
    if not issues:
        issues.extend(_traceability_issues(request))
    return issues


def _header_issues(request: AgentRequest, rules: CodeRequestRules) -> tuple[list[Issue], Any]:
    issues: list[Issue] = []
    if request.agent_id != rules.agent_id:
        issues.append(Issue("agentId", "agentId does not match this agent"))
    item_id = request.input.get("taskItemId")
    if not isinstance(item_id, str) or re.fullmatch(r"T[1-9][0-9]*", item_id) is None:
        issues.append(Issue("input.taskItemId", "taskItemId must match T[1-9][0-9]*"))
    allowed_input = {"taskItemId", "ref", "language"} | rules.extra_input
    if set(request.input) - allowed_input:
        issues.append(Issue("input", "Unsupported input fields"))
    issues.extend(_language_issue(request))
    if rules.require_ref:
        issues.extend(_ref_issue(request))
    if request.feedback:
        issues.append(Issue("feedback", "Use review/report artifacts, not feedback"))
    issues.extend(_attempt_issue(request))
    return issues, item_id


def _language_issue(request: AgentRequest) -> list[Issue]:
    if "language" not in request.input:
        return []
    language = request.input["language"]
    if not isinstance(language, str) or not language.strip():
        return [Issue("input.language", "language must be a non-empty string")]
    return []


def _ref_issue(request: AgentRequest) -> list[Issue]:
    ref = request.input.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        return [Issue("input.ref", "A non-empty base ref is required")]
    return []


def _attempt_issue(request: AgentRequest) -> list[Issue]:
    attempt = request.metadata.get("attempt", 1)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        return [Issue("metadata.attempt", "attempt must be an integer >= 1")]
    return []


def _required_count_issues(request: AgentRequest, required: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    for kind in sorted(required):
        if sum(artifact.type == kind for artifact in request.artifacts) != 1:
            issues.append(Issue("artifacts", f"Exactly one {kind} artifact is required"))
    return issues


def _artifact_issues(
    request: AgentRequest, allowed: set[str], item_id: Any
) -> tuple[list[Issue], int]:
    issues: list[Issue] = []
    total = 0
    for index, artifact in enumerate(request.artifacts):
        artifact_issues, size = _single_artifact_issues(artifact, index, allowed, item_id)
        issues.extend(artifact_issues)
        total += size
    return issues, total


def _single_artifact_issues(
    artifact: Artifact, index: int, allowed: set[str], item_id: Any
) -> tuple[list[Issue], int]:
    path = f"artifacts[{index}]"
    issues: list[Issue] = []
    if artifact.type not in allowed:
        issues.append(Issue(path, "Unsupported artifact type"))
    if re.fullmatch(r"[1-9][0-9]*", artifact.version) is None:
        issues.append(Issue(path + ".version", "Artifact version must be a positive integer"))
    text_issues, size = _text_size(artifact, path)
    issues.extend(text_issues)
    if artifact.type == "CODE":
        issues.extend(_code_artifact_issues(artifact, path, item_id))
    return issues, size


def _text_size(artifact: Artifact, path: str) -> tuple[list[Issue], int]:
    content = artifact.content
    if (
        not isinstance(content, dict)
        or not isinstance(content.get("text"), str)
        or not content["text"].strip()
    ):
        return [Issue(path + ".content.text", "Non-empty inline text is required")], 0
    try:
        return [], len(json.dumps(content, ensure_ascii=True))
    except (TypeError, ValueError):
        return [Issue(path + ".content", "Artifact content must be JSON serializable")], 0


def _code_artifact_issues(artifact: Artifact, path: str, item_id: Any) -> list[Issue]:
    issues: list[Issue] = []
    if artifact.metadata.get("taskItemId") != item_id:
        issues.append(Issue(path + ".metadata.taskItemId", "CODE task item does not match"))
    base_ref = artifact.metadata.get("baseRef")
    if not isinstance(base_ref, str) or not base_ref.strip():
        issues.append(Issue(path + ".metadata.baseRef", "CODE baseRef is required"))
    try:
        code_changeset(artifact)
    except (ValueError, ValidationError):
        issues.append(Issue(path + ".content.changeSet", "Invalid CODE ChangeSet"))
    return issues


def _task_item_issue(request: AgentRequest, item_id: Any) -> list[Issue]:
    tasks = [artifact for artifact in request.artifacts if artifact.type == "TASK"]
    if len(tasks) != 1 or not isinstance(item_id, str):
        return []
    try:
        task_item(tasks[0], item_id)
    except (ValueError, TypeError):
        return [Issue("artifacts.TASK", "TASK has no unique matching task item")]
    return []


def _traceability_issues(request: AgentRequest) -> list[Issue]:
    by_kind = {artifact.type: artifact for artifact in request.artifacts}
    issues = _code_link_issues(by_kind)
    issues.extend(_upstream_link_issues(by_kind))
    return issues


def _code_link_issues(by_kind: dict[str, Artifact]) -> list[Issue]:
    code = by_kind.get("CODE")
    if code is None:
        return []
    issues: list[Issue] = []
    for key, value in _links(by_kind).items():
        if code.metadata.get(key) != value:
            issues.append(Issue("artifacts.CODE.metadata." + key, "Stale CODE traceability"))
    return issues


def _links(by_kind: dict[str, Artifact]) -> dict[str, str]:
    links: dict[str, str] = {}
    spec = by_kind.get("SPEC")
    if spec is not None:
        links.update(specArtifactId=spec.id, specVersion=spec.version)
    plan = by_kind.get("PLAN")
    if plan is not None:
        links.update(planArtifactId=plan.id, planVersion=plan.version)
    task = by_kind.get("TASK")
    if task is not None:
        links.update(taskArtifactId=task.id, taskVersion=task.version)
    return links


def _upstream_link_issues(by_kind: dict[str, Artifact]) -> list[Issue]:
    pairs = (
        (by_kind.get("TASK"), by_kind.get("SPEC")),
        (by_kind.get("TASK"), by_kind.get("PLAN")),
        (by_kind.get("PLAN"), by_kind.get("SPEC")),
    )
    issues: list[Issue] = []
    for downstream, upstream in pairs:
        if downstream is None or upstream is None:
            continue
        prefix = upstream.type.lower()
        if (
            downstream.metadata.get(prefix + "ArtifactId") != upstream.id
            or downstream.metadata.get(prefix + "Version") != upstream.version
        ):
            issues.append(Issue("artifacts", "Stale upstream traceability"))
    return issues


def linked_metadata(request: AgentRequest, code: Artifact) -> dict[str, Any]:
    metadata = {
        key: value
        for key, value in code.metadata.items()
        if key
        in {
            "specArtifactId",
            "specVersion",
            "planArtifactId",
            "planVersion",
            "taskArtifactId",
            "taskVersion",
            "taskItemId",
            "baseRef",
        }
    }
    metadata.update(codeArtifactId=code.id, codeVersion=code.version)
    return metadata
