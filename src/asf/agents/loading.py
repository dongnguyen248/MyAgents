from __future__ import annotations

import importlib.resources
from pathlib import Path

from asf.agents.spec.prompts import SpecPrompts, SpecTemplate
from asf.configuration.errors import ConfigError

__all__ = ["load_spec_prompts", "load_spec_template"]


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
