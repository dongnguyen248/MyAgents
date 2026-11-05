from __future__ import annotations

import importlib.resources
from pathlib import Path

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


def load_spec_prompts() -> SpecPrompts:
    """Loads system and revision prompts from package resources."""
    try:
        traversable = importlib.resources.files("asf.agents.spec").joinpath("prompts")
        sys_resource = traversable.joinpath("system.md")
        rev_resource = traversable.joinpath("revision.md")

        system_text = sys_resource.read_text(encoding="utf-8")
        revision_text = rev_resource.read_text(encoding="utf-8")
        return SpecPrompts(system=system_text, revision=revision_text)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load spec prompts from package: {exc}",
            source="asf.agents.spec.prompts",
        ) from exc


def load_spec_template(templates_dir: Path) -> SpecTemplate:
    """Loads SPEC artifact template from the specified templates directory."""
    template_path = templates_dir / "spec" / "SPEC.md"
    try:
        text = template_path.read_text(encoding="utf-8")
        return SpecTemplate.from_text(text)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load spec template from '{template_path}': {exc}",
            source=str(template_path),
        ) from exc


def load_plan_prompts() -> PlanPrompts:
    """Loads system and revision prompts from package resources."""
    try:
        traversable = importlib.resources.files("asf.agents.plan").joinpath("prompts")
        sys_resource = traversable.joinpath("system.md")
        rev_resource = traversable.joinpath("revision.md")

        system_text = sys_resource.read_text(encoding="utf-8")
        revision_text = rev_resource.read_text(encoding="utf-8")
        return PlanPrompts(system=system_text, revision=revision_text)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load plan prompts from package: {exc}",
            source="asf.agents.plan.prompts",
        ) from exc


def load_plan_template(templates_dir: Path) -> PlanTemplate:
    """Loads PLAN artifact template from the specified templates directory."""
    template_path = templates_dir / "plan" / "PLAN.md"
    try:
        text = template_path.read_text(encoding="utf-8")
        return PlanTemplate.from_text(text)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load plan template from '{template_path}': {exc}",
            source=str(template_path),
        ) from exc


def load_task_prompts() -> TaskPrompts:
    """Loads system and revision prompts from package resources."""
    try:
        traversable = importlib.resources.files("asf.agents.task").joinpath("prompts")
        sys_resource = traversable.joinpath("system.md")
        rev_resource = traversable.joinpath("revision.md")

        system_text = sys_resource.read_text(encoding="utf-8")
        revision_text = rev_resource.read_text(encoding="utf-8")
        return TaskPrompts(system=system_text, revision=revision_text)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load task prompts from package: {exc}",
            source="asf.agents.task.prompts",
        ) from exc


def load_task_template(templates_dir: Path) -> TaskTemplate:
    """Loads TASK artifact template from the specified templates directory."""
    template_path = templates_dir / "task" / "TASK.md"
    try:
        text = template_path.read_text(encoding="utf-8")
        return TaskTemplate.from_text(text)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load task template from '{template_path}': {exc}",
            source=str(template_path),
        ) from exc


def load_implement_prompts() -> ImplementPrompts:
    """Loads system prompt from package resources."""
    try:
        traversable = importlib.resources.files("asf.agents.implement").joinpath("prompts")
        sys_resource = traversable.joinpath("system.md")

        system_text = sys_resource.read_text(encoding="utf-8")
        return ImplementPrompts(system=system_text)
    except Exception as exc:
        raise ConfigError(
            f"Failed to load implement prompts from package: {exc}",
            source="asf.agents.implement.prompts",
        ) from exc


def load_review_prompts() -> ReviewPrompts:
    try:
        resource = importlib.resources.files("asf.agents.review").joinpath("prompts", "system.md")
        return ReviewPrompts(system=resource.read_text(encoding="utf-8"))
    except (OSError, ModuleNotFoundError) as exc:
        raise ConfigError(
            "Failed to load review prompts", source="asf.agents.review.prompts"
        ) from exc


def load_fix_prompts() -> FixPrompts:
    try:
        resource = importlib.resources.files("asf.agents.fix").joinpath("prompts", "system.md")
        return FixPrompts(system=resource.read_text(encoding="utf-8"))
    except (OSError, ModuleNotFoundError) as exc:
        raise ConfigError("Failed to load fix prompts", source="asf.agents.fix.prompts") from exc
