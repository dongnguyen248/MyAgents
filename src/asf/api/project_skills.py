"""Resolve project-enabled skills from the catalogue for a new run."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from asf.agents._shared.skills import extract_skill_digest


def resolve_project_skills(
    profile: dict[str, Any], project_id: str, root: Path, body_of: Callable[[str], str]
) -> list[dict[str, str]]:
    enabled = profile.get("enabledSkills")
    if not isinstance(enabled, list):
        return []
    resolved = []
    for entry in enabled:
        if not isinstance(entry, str) or not entry.strip():
            continue
        skill_id = entry.strip()
        path = root / skill_id / "SKILL.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(
                f"Project '{project_id}' enables skill '{skill_id}'"
                f" but {path} cannot be read: {error}",
            ) from error
        body = body_of(text)
        digest = extract_skill_digest(text)
        if body:
            item = {"id": skill_id, "content": body}
            if digest:
                item["digest"] = digest
            resolved.append(item)
    return resolved
