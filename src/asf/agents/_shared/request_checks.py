"""Request validators shared by the agents.

Each agent's ``_check`` is a composition of small validators that
each return ``list[Issue]`` for one concern. The validators whose
logic is identical across agents live here; the message text is
passed in where agents word the same failure differently, so no
agent's observable validation output changes. (The sibling
``validation`` module holds the pydantic field validators.)
"""

from __future__ import annotations

import re
from typing import Any

from asf.agents.base import Issue
from asf.contracts.models import AgentRequest, Artifact

TASK_ITEM_ID_PATTERN = re.compile(r"T[1-9][0-9]*")
POSITIVE_VERSION_PATTERN = re.compile(r"[1-9][0-9]*")


def is_task_item_id(value: Any) -> bool:
    return isinstance(value, str) and TASK_ITEM_ID_PATTERN.fullmatch(value) is not None


def is_positive_version(value: Any) -> bool:
    return isinstance(value, str) and POSITIVE_VERSION_PATTERN.fullmatch(value) is not None


def artifacts_of(request: AgentRequest, kind: str) -> list[Artifact]:
    return [artifact for artifact in request.artifacts if artifact.type == kind]


def artifact_has_text(artifact: Artifact) -> bool:
    if not isinstance(artifact.content, dict):
        return False
    text = artifact.content.get("text")
    return isinstance(text, str) and bool(text.strip())


def check_agent_id(request: AgentRequest, expected_id: str, message: str) -> list[Issue]:
    if request.agent_id == expected_id:
        return []
    return [Issue("agentId", message)]


def check_attempt(request: AgentRequest) -> list[Issue]:
    attempt = request.metadata.get("attempt", 1)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        return [Issue("metadata.attempt", "metadata.attempt must be an integer >= 1")]
    return []


def check_language(request: AgentRequest, message: str) -> list[Issue]:
    if "language" not in request.input:
        return []
    language = request.input["language"]
    if not isinstance(language, str) or not language.strip():
        return [Issue("input.language", message)]
    return []


def check_input_keys(request: AgentRequest, allowed: set[str], message: str) -> list[Issue]:
    if set(request.input) - allowed:
        return [Issue("input", message)]
    return []


def check_no_feedback(request: AgentRequest, message: str) -> list[Issue]:
    if request.feedback:
        return [Issue("feedback", message)]
    return []


def check_required_artifact(request: AgentRequest, kind: str) -> list[Issue]:
    arts = artifacts_of(request, kind)
    if len(arts) != 1:
        return [Issue("artifacts", f"Exactly one artifact of type {kind} is required")]
    index = request.artifacts.index(arts[0])
    return [
        *_artifact_text_issue(request, index, kind),
        *_artifact_version_issue(request, index, kind),
    ]


def check_revision_artifact(
    request: AgentRequest, kind: str, feedback_message: str
) -> list[Issue]:
    arts = artifacts_of(request, kind)
    if len(arts) > 1:
        return [Issue("artifacts", f"At most one artifact of type {kind} is permitted")]
    if not arts:
        return []
    index = request.artifacts.index(arts[0])
    issues: list[Issue] = []
    if not request.feedback:
        issues.append(Issue("feedback", feedback_message))
    issues.extend(_artifact_text_issue(request, index, kind))
    issues.extend(_artifact_version_issue(request, index, kind))
    return issues


def _artifact_text_issue(request: AgentRequest, index: int, kind: str) -> list[Issue]:
    if artifact_has_text(request.artifacts[index]):
        return []
    message = f"{kind} artifact must have inline content mapping with non-empty 'text'"
    return [Issue(f"artifacts[{index}].content.text", message)]


def _artifact_version_issue(request: AgentRequest, index: int, kind: str) -> list[Issue]:
    version = request.artifacts[index].version
    if is_positive_version(version):
        return []
    message = f"{kind} artifact version '{version}' must match '^[1-9][0-9]*$'"
    return [Issue(f"artifacts[{index}].version", message)]


def check_orphan_feedback(request: AgentRequest, kind: str) -> list[Issue]:
    if request.feedback and not artifacts_of(request, kind):
        message = f"feedback provided without a previous {kind} artifact to revise"
        return [Issue("artifacts", message)]
    return []


def check_artifact_types(request: AgentRequest, allowed: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    for index, artifact in enumerate(request.artifacts):
        if artifact.type not in allowed:
            message = f"Unknown artifact type '{artifact.type}'; allowed: {sorted(allowed)}"
            issues.append(Issue(f"artifacts[{index}].type", message))
    return issues


def check_text_size(
    request: AgentRequest, kinds: set[str], limit: int, message: str
) -> list[Issue]:
    total = 0
    for artifact in request.artifacts:
        if artifact.type not in kinds:
            continue
        if isinstance(artifact.content, dict) and isinstance(
            artifact.content.get("text"), str
        ):
            total += len(artifact.content["text"])
    if total > limit:
        return [Issue("artifacts", message)]
    return []
