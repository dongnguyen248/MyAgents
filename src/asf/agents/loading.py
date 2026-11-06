from __future__ import annotations

import importlib.resources
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asf.agents.artifact_review.prompts import ArtifactReviewPrompts
from asf.agents.fix.prompts import FixPrompts
from asf.agents.implement.prompts import ImplementPrompts
from asf.agents.plan.prompts import PlanPrompts, PlanTemplate
from asf.agents.review.prompts import ReviewPrompts
from asf.agents.spec.prompts import SpecPrompts, SpecTemplate
from asf.agents.task.prompts import TaskPrompts, TaskTemplate
from asf.configuration.errors import ConfigError

__all__ = [
    "load_spec_prompts",
    "load_spec_template",
    "load_plan_prompts",
    "load_plan_template",
    "load_task_prompts",
    "load_task_template",
    "load_implement_prompts",
    "load_review_prompts",
    "load_fix_prompts",
    "load_artifact_review_prompts",
]


def _read_optional(package: str, relative: str) -> str | None:
    traversable = importlib.resources.files(package)
    for part in relative.split("/"):
        traversable = traversable.joinpath(part)
    if not traversable.is_file():
        return None
    return traversable.read_text(encoding="utf-8")


def _load_skills(package: str) -> dict[str, str]:
    skills: dict[str, str] = {}
    skills_dir = importlib.resources.files(package).joinpath("skills")
    if not skills_dir.is_dir():
        return skills
    for entry in sorted(skills_dir.iterdir(), key=lambda item: item.name):
        if not entry.is_dir():
            continue
        text = _read_optional(package, f"skills/{entry.name}/SKILL.md")
        if text is not None:
            skills[entry.name] = text
    return skills


def _load_extras(package: str, *, tool_guidance: bool) -> dict[str, Any]:
    """The harness files beyond contract/system/revision (design D5).

    Guardrails, memory, agent-scoped skills and (for the code
    agents) tool guidance are read from the package exactly like the
    prompt files, so the default runtime path and the offline
    harness bundle see the same components.
    """
    extras: dict[str, Any] = {
        "guardrails": _read_optional(package, "instructions/guardrails.md") or "",
        "memory": _read_optional(package, "instructions/memory.md") or "",
        "skills": _load_skills(package),
    }
    if tool_guidance:
        extras["tool_guidance"] = _read_optional(package, "tools/tool_guidance.md") or ""
    return extras


def _load_prompt_pair[T](package: str, agent: str, build: Callable[..., T]) -> T:
    try:
        traversable = importlib.resources.files(package).joinpath("prompts")
        contract_text = traversable.joinpath("contract.md").read_text(encoding="utf-8")
        system_text = traversable.joinpath("system.md").read_text(encoding="utf-8")
        revision_text = traversable.joinpath("revision.md").read_text(encoding="utf-8")
        extras = _load_extras(package, tool_guidance=False)
        return build(system=system_text, revision=revision_text, contract=contract_text, **extras)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load {agent} prompts from package: {exc}",
            source=f"{package}.prompts",
        ) from exc


def _load_contract_and_system(package: str, agent: str, *, strict: bool) -> tuple[str, str]:
    try:
        traversable = importlib.resources.files(package).joinpath("prompts")
        contract = traversable.joinpath("contract.md").read_text(encoding="utf-8")
        system = traversable.joinpath("system.md").read_text(encoding="utf-8")
        return contract, system
    except (OSError, ModuleNotFoundError) as exc:
        if strict:
            raise ConfigError(
                f"Failed to load {agent} prompts", source=f"{package}.prompts"
            ) from exc
        raise ConfigError(
            f"Failed to load {agent} prompts from package: {exc}",
            source=f"{package}.prompts",
        ) from exc
    except Exception as exc:
        if strict:
            raise
        raise ConfigError(
            f"Failed to load {agent} prompts from package: {exc}",
            source=f"{package}.prompts",
        ) from exc


@dataclass(frozen=True)
class _PromptSource:
    package: str
    agent: str
    strict: bool
    tool_guidance: bool


def _load_agent_prompts[T](source: _PromptSource, build: Callable[..., T]) -> T:
    contract, system = _load_contract_and_system(source.package, source.agent, strict=source.strict)
    try:
        extras = _load_extras(source.package, tool_guidance=source.tool_guidance)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load {source.agent} harness files from package: {exc}",
            source=f"{source.package}",
        ) from exc
    return build(system=system, contract=contract, **extras)


def _load_template[T](
    templates_dir: Path, agent: str, filename: str, build: Callable[[str], T]
) -> T:
    template_path = templates_dir / agent / filename
    try:
        text = template_path.read_text(encoding="utf-8")
        return build(text)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load {agent} template from '{template_path}': {exc}",
            source=str(template_path),
        ) from exc


def load_spec_prompts() -> SpecPrompts:
    return _load_prompt_pair("asf.agents.spec", "spec", SpecPrompts)


def load_spec_template(templates_dir: Path) -> SpecTemplate:
    return _load_template(templates_dir, "spec", "SPEC.md", SpecTemplate.from_text)


def load_plan_prompts() -> PlanPrompts:
    return _load_prompt_pair("asf.agents.plan", "plan", PlanPrompts)


def load_plan_template(templates_dir: Path) -> PlanTemplate:
    return _load_template(templates_dir, "plan", "PLAN.md", PlanTemplate.from_text)


def load_task_prompts() -> TaskPrompts:
    return _load_prompt_pair("asf.agents.task", "task", TaskPrompts)


def load_task_template(templates_dir: Path) -> TaskTemplate:
    return _load_template(templates_dir, "task", "TASK.md", TaskTemplate.from_text)


def load_implement_prompts() -> ImplementPrompts:
    source = _PromptSource("asf.agents.implement", "implement", strict=False, tool_guidance=True)
    return _load_agent_prompts(source, ImplementPrompts)


def load_review_prompts() -> ReviewPrompts:
    source = _PromptSource("asf.agents.review", "review", strict=True, tool_guidance=False)
    return _load_agent_prompts(source, ReviewPrompts)


def load_fix_prompts() -> FixPrompts:
    source = _PromptSource("asf.agents.fix", "fix", strict=True, tool_guidance=True)
    return _load_agent_prompts(source, FixPrompts)


def _load_checklists(package: str) -> dict[str, str]:
    checklists: dict[str, str] = {}
    for stage in ("spec", "plan", "task"):
        text = _read_optional(package, f"instructions/checklist_{stage}.md")
        if text is not None:
            checklists[stage] = text
    return checklists


def load_artifact_review_prompts() -> ArtifactReviewPrompts:
    package = "asf.agents.artifact_review"
    source = _PromptSource(package, "artifact-review", strict=True, tool_guidance=False)

    def build(**kwargs: Any) -> ArtifactReviewPrompts:
        return ArtifactReviewPrompts(checklists=_load_checklists(package), **kwargs)

    return _load_agent_prompts(source, build)
