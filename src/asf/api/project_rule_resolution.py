"""Resolve selected global rules and legacy project-specific review rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from asf.api.rule_catalogue import read_rule, rule_root


def _legacy_rule(projects: Path | None, entry: str, project_id: str) -> str:
    if projects is None:
        raise ValueError(f"Project '{project_id}' has rulesFiles but no projects directory")
    path = (projects / entry).resolve()
    if not path.is_relative_to(projects.resolve()):
        raise ValueError(
            f"Review rules file '{entry}' for project '{project_id}' escapes the projects directory"
        )
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            raise ValueError(
                f"Review rules file '{entry}' for project '{project_id}' cannot be read: {error}"
            ) from error
    if entry.startswith("rules/"):
        try:
            return read_rule(rule_root(projects), entry.removeprefix("rules/")).strip()
        except ValueError:
            pass
    raise ValueError(f"Review rules file '{entry}' for project '{project_id}' cannot be read")


def _append_selected(
    parts: list[str], profile: dict[str, Any], project_id: str, root: Path
) -> None:
    selected = profile.get("enabledRules", [])
    if not isinstance(selected, list):
        return
    for rule_id in selected:
        try:
            text = read_rule(root, rule_id).strip()
        except (ValueError, TypeError) as error:
            raise ValueError(f"Project '{project_id}' rule '{rule_id}': {error}") from error
        if text and text not in parts:
            parts.append(text)


def _append_legacy(parts: list[str], review: Any, project_id: str, projects: Path | None) -> None:
    if not isinstance(review, dict):
        return
    files = review.get("rulesFiles")
    if isinstance(files, list):
        for entry in files:
            if not isinstance(entry, str) or not entry.strip():
                continue
            text = _legacy_rule(projects, entry, project_id)
            if text and text not in parts:
                parts.append(text)
    inline = review.get("rules")
    if isinstance(inline, str):
        _append_text(parts, inline)


def _append_text(parts: list[str], text: str) -> None:
    if text.strip() and text.strip() not in parts:
        parts.append(text.strip())


def project_rules_text(
    parts: list[str], profile: dict[str, Any], project_id: str, projects: Path | None
) -> str:
    _append_selected(parts, profile, project_id, rule_root(projects))
    configuration = profile.get("configuration")
    review = configuration.get("review") if isinstance(configuration, dict) else None
    _append_legacy(parts, review, project_id, projects)
    return "\n\n".join(parts)


def validate_project_rule_files(service: Any, profile: Any) -> None:
    if not hasattr(service, "_projects_dir"):
        return
    root = rule_root(service._projects_dir)
    for rule_id in profile.enabled_rules:
        try:
            read_rule(root, rule_id)
        except ValueError as error:
            raise ValueError(f"Project rule '{rule_id}': {error}") from error
