from __future__ import annotations

import importlib.resources
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

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
]

T = TypeVar("T")


def _load_prompt_pair(
    package: str, agent: str, build: Callable[..., T]
) -> T:
    try:
        traversable = importlib.resources.files(package).joinpath("prompts")
        system_text = traversable.joinpath("system.md").read_text(encoding="utf-8")
        revision_text = traversable.joinpath("revision.md").read_text(encoding="utf-8")
        return build(system=system_text, revision=revision_text)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load {agent} prompts from package: {exc}",
            source=f"{package}.prompts",
        ) from exc


def _load_system_prompt(package: str, agent: str) -> str:
    try:
        resource = importlib.resources.files(package).joinpath("prompts", "system.md")
        return resource.read_text(encoding="utf-8")
    except Exception as exc:
        raise ConfigError(
            f"Failed to load {agent} prompts from package: {exc}",
            source=f"{package}.prompts",
        ) from exc


def _load_system_prompt_strict(package: str, agent: str) -> str:
    try:
        resource = importlib.resources.files(package).joinpath("prompts", "system.md")
        return resource.read_text(encoding="utf-8")
    except (OSError, ModuleNotFoundError) as exc:
        raise ConfigError(
            f"Failed to load {agent} prompts", source=f"{package}.prompts"
        ) from exc


def _load_template(
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
    system = _load_system_prompt("asf.agents.implement", "implement")
    return ImplementPrompts(system=system)


def load_review_prompts() -> ReviewPrompts:
    return ReviewPrompts(system=_load_system_prompt_strict("asf.agents.review", "review"))


def load_fix_prompts() -> FixPrompts:
    return FixPrompts(system=_load_system_prompt_strict("asf.agents.fix", "fix"))
