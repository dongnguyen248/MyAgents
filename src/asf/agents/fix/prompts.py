from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from asf.agents._shared.codegen import FixContext
from asf.agents._shared.harness import (
    HarnessComponents,
    agent_skills_section,
    assemble_base_prompt,
    guardrails_memory_section,
)
from asf.agents._shared.rules import rules_section
from asf.agents._shared.skills import skills_section
from asf.contracts.models import AgentRequest, ModelMessage
from asf.tools.edit_blocks import BLOCKS_FORMAT_INSTRUCTIONS


@dataclass(frozen=True)
class FixPrompts:
    system: str
    contract: str = ""
    tool_guidance: str = ""
    guardrails: str = ""
    memory: str = ""
    skills: Mapping[str, str] = field(default_factory=dict)

    def to_components(self) -> HarnessComponents:
        """The harness these loaded prompt files represent on their own."""
        return HarnessComponents(
            contract=self.contract,
            system=self.system,
            guardrails=self.guardrails,
            memory=self.memory,
            tool_guidance=self.tool_guidance,
            skills=self.skills,
        )


_RULES_INTRO = (
    "Project development rules — the standards this project's code"
    " must follow. Write the fix so the resulting code complies with"
    " them; where they conflict with the output contract above, the"
    " output contract wins:"
)


@dataclass(frozen=True)
class FixMessageOptions:
    edit_format: str = "blocks"
    harness: HarnessComponents | None = None


def build_fix_messages(
    prompts: FixPrompts,
    request: AgentRequest,
    context: FixContext,
    options: FixMessageOptions | None = None,
) -> list[ModelMessage]:
    opts = options if options is not None else FixMessageOptions()
    components = _components(prompts, opts.harness)
    payload = _payload(request, context, opts.edit_format, components.tool_guidance)
    return [
        ModelMessage(role="system", content=_system_message(prompts, request, opts.harness)),
        ModelMessage(role="user", content=json.dumps(payload, ensure_ascii=True)),
    ]


def _components(prompts: FixPrompts, harness: HarnessComponents | None) -> HarnessComponents:
    if harness is not None:
        return harness
    return prompts.to_components()


def _system_message(
    prompts: FixPrompts,
    request: AgentRequest,
    harness: HarnessComponents | None = None,
) -> str:
    components = _components(prompts, harness)
    system = assemble_base_prompt(components)
    project = request.context.get("project")
    if isinstance(project, str):
        project = json.loads(project)
    if isinstance(project, dict):
        skills = project.get("enabledSkills", [])
        if isinstance(skills, list) and all(isinstance(skill, str) for skill in skills):
            system += "\nEnabled skills: " + ", ".join(skills)
    system += rules_section(project, _RULES_INTRO)
    system += guardrails_memory_section(components)
    system += skills_section(project, "fix")
    system += agent_skills_section(components)
    return system


def _payload(
    request: AgentRequest,
    context: FixContext,
    edit_format: str,
    tool_guidance: str,
) -> dict[str, Any]:
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
        payload["formatInstructions"] = BLOCKS_FORMAT_INSTRUCTIONS + tool_guidance
    return payload
