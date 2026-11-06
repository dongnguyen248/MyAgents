from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from asf.agents._shared.codegen import FixContext
from asf.agents._shared.rules import rules_section
from asf.agents._shared.skills import skills_section
from asf.contracts.models import AgentRequest, ModelMessage
from asf.tools.edit_blocks import BLOCKS_FORMAT_INSTRUCTIONS


@dataclass(frozen=True)
class FixPrompts:
    system: str


_RULES_INTRO = (
    "Project development rules — the standards this project's code"
    " must follow. Write the fix so the resulting code complies with"
    " them; where they conflict with the output contract above, the"
    " output contract wins:"
)

_BLOCKS_EXTRA = (
    "\n- Your blocks apply to the PREVIOUS GENERATED files"
    " (the base files with the previous change set applied),"
    " not to the raw base: SEARCH text must match the"
    " previous generated content where a file was changed"
    " before.\n"
    "- Files you do not mention keep their previous generated"
    " content — the replacement stays complete."
)


def build_fix_messages(
    prompts: FixPrompts,
    request: AgentRequest,
    context: FixContext,
    *,
    edit_format: str = "blocks",
) -> list[ModelMessage]:
    payload = _payload(request, context, edit_format)
    return [
        ModelMessage(role="system", content=_system_message(prompts, request)),
        ModelMessage(role="user", content=json.dumps(payload, ensure_ascii=True)),
    ]


def _system_message(prompts: FixPrompts, request: AgentRequest) -> str:
    system = prompts.system
    project = request.context.get("project")
    if isinstance(project, str):
        project = json.loads(project)
    if isinstance(project, dict):
        skills = project.get("enabledSkills", [])
        if isinstance(skills, list) and all(isinstance(skill, str) for skill in skills):
            system += "\nEnabled skills: " + ", ".join(skills)
    system += rules_section(project, _RULES_INTRO)
    system += skills_section(project, "fix")
    return system


def _payload(request: AgentRequest, context: FixContext, edit_format: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "taskItemId": context.task_id,
        "baseRef": request.input["ref"],
        "expectedFiles": context.expected_files,
        "baseFiles": context.existing_files,
        "artifacts": [artifact.to_contract() for artifact in request.artifacts],
    }
    if context.previous_error:
        # Why the previous fix attempt was rejected; the system prompt
        # tells the model to correct this specific failure.
        payload["previousAttemptError"] = context.previous_error
    if context.repo_map:
        payload["repoMap"] = context.repo_map
    payload["outputFormat"] = edit_format
    if edit_format == "blocks":
        payload["formatInstructions"] = BLOCKS_FORMAT_INSTRUCTIONS + _BLOCKS_EXTRA
    return payload
