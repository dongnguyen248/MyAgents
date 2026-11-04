from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from asf.agents._shared.codegen import FixContext
from asf.contracts.models import AgentRequest, ModelMessage


@dataclass(frozen=True)
class FixPrompts:
    system: str


def build_fix_messages(
    prompts: FixPrompts, request: AgentRequest, context: FixContext
) -> list[ModelMessage]:
    system = prompts.system
    project = request.context.get("project")
    if isinstance(project, str):
        project = json.loads(project)
    if isinstance(project, dict):
        skills = project.get("enabledSkills", [])
        if isinstance(skills, list) and all(isinstance(skill, str) for skill in skills):
            system += "\nEnabled skills: " + ", ".join(skills)
    payload: dict[str, Any] = {
        "taskItemId": context.task_id,
        "baseRef": request.input["ref"],
        "expectedFiles": context.expected_files,
        "baseFiles": context.existing_files,
        "artifacts": [artifact.to_contract() for artifact in request.artifacts],
    }
    return [
        ModelMessage(role="system", content=system),
        ModelMessage(role="user", content=json.dumps(payload, ensure_ascii=True)),
    ]
