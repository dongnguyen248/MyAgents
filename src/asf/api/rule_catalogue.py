"""Project rule files available for operator-selected agent guidance."""

from __future__ import annotations

import os
from pathlib import Path

MAX_RULE_BYTES = 1024 * 1024


def rule_root(projects_dir: Path | None) -> Path:
    if projects_dir is None:
        return Path(__file__).resolve().parents[3] / "rules"
    return projects_dir.parent / "rules"


def _rule_parts(rule_id: str) -> tuple[str, ...]:
    parts = Path(rule_id).parts
    if not parts or Path(rule_id).is_absolute() or "\\" in rule_id:
        raise ValueError("Invalid rule path")
    if any(part in {".", ".."} for part in parts) or Path(rule_id).suffix.lower() != ".md":
        raise ValueError("Invalid rule path")
    return parts


def rule_path(root: Path, rule_id: str) -> Path:
    parts = _rule_parts(rule_id)
    current = root
    for part in parts:
        if current.is_symlink():
            raise ValueError("Rule file is not available")
        current = current / part
    if current.is_symlink() or not current.is_file():
        raise ValueError("Rule file is not available")
    return current


def read_rule(root: Path, rule_id: str) -> str:
    path = rule_path(root, rule_id)
    try:
        if path.stat().st_size > MAX_RULE_BYTES:
            raise ValueError("Rule file is too large")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("Rule file is not readable UTF-8 text") from error


def list_rules(root: Path) -> list[dict[str, str]]:
    if root.is_symlink() or not root.is_dir():
        return []
    result = []
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(name for name in dirs if not (base / name).is_symlink())
        for name in sorted(files):
            path = base / name
            if path.suffix.lower() != ".md" or path.is_symlink() or not path.is_file():
                continue
            rule_id = path.relative_to(root).as_posix()
            result.append({"id": rule_id, "name": path.stem, "path": f"rules/{rule_id}"})
    return sorted(result, key=lambda rule: rule["id"])


def resolve_agent_rules(
    root: Path, selections: dict[str, list[str]], project_rules: str
) -> dict[str, str]:
    result = {}
    for agent, ids in selections.items():
        texts = []
        for rule_id in ids:
            try:
                text = read_rule(root, rule_id).strip()
            except ValueError as error:
                raise ValueError(f"Agent '{agent}' rule '{rule_id}': {error}") from error
            if text and text not in project_rules and text not in texts:
                texts.append(text)
        if texts:
            result[agent] = "\n\n".join(texts)
    return result
