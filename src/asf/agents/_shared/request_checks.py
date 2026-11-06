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
