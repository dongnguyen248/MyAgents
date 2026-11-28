"""Filesystem-backed skill catalogue for the dashboard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from asf.agents._shared.skills import _STACK_SKILLS, SKILL_AGENTS

MAX_FILE_BYTES = 1024 * 1024


class SkillFileUpdate(BaseModel):
    content: str


def _validate_path(skill_id: str, relative: str) -> tuple[str, ...]:
    parts = Path(relative).parts
    if not skill_id or skill_id in {".", ".."} or "/" in skill_id or "\\" in skill_id:
        raise HTTPException(400, "Invalid skill name")
    if not parts or Path(relative).is_absolute() or any(p in {".", ".."} for p in parts):
        raise HTTPException(400, "Invalid file path")
    return parts


def _file_path(root: Path, skill_id: str, relative: str) -> Path:
    parts = _validate_path(skill_id, relative)
    current = root / skill_id
    definition = current / "SKILL.md"
    if current.is_symlink() or definition.is_symlink() or not definition.is_file():
        raise HTTPException(404, "Skill not found")
    for part in parts:
        if current.is_symlink():
            raise HTTPException(404, "File not found")
        current = current / part
    if current.is_symlink() or not current.is_file():
        raise HTTPException(404, "File not found")
    return current


def _read_text(path: Path) -> str:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(413, "File is too large to edit")
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeError, OSError) as error:
        raise HTTPException(400, "File is not readable UTF-8 text") from error


def _metadata(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        value = yaml.safe_load("\n".join(lines[1:end]))
    except (StopIteration, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def _files(directory: Path) -> list[str]:
    result: list[str] = []
    for current, dirs, files in os.walk(directory, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink())
        result.extend((base / name).relative_to(directory).as_posix() + "/" for name in dirs)
        result.extend(
            (base / name).relative_to(directory).as_posix()
            for name in sorted(files)
            if not (base / name).is_symlink() and (base / name).is_file()
        )
    return sorted(result)


def _skill(directory: Path, overrides: dict[str, list[str]] | None = None) -> dict[str, Any]:
    try:
        metadata = _metadata(_read_text(directory / "SKILL.md"))
    except HTTPException:
        metadata = {}
    skill_id = directory.name
    agents = set(SKILL_AGENTS.get(skill_id, frozenset()))
    for agent, skills in (overrides or {}).items():
        agents.discard(agent)
        if skill_id in skills:
            agents.add(agent)
    return {
        "id": skill_id,
        "name": str(metadata.get("name") or skill_id),
        "description": str(metadata.get("description") or "No description in SKILL.md."),
        "digest": str(metadata.get("digest") or ""),
        "appliesTo": sorted(agents),
        "stackOnly": skill_id in _STACK_SKILLS,
        "path": f"skills/{skill_id}/SKILL.md",
        "files": _files(directory),
    }


def list_skill_catalogue(
    directory: Path, overrides: dict[str, list[str]] | None = None
) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    return [
        _skill(path, overrides)
        for path in sorted(directory.iterdir())
        if path.is_dir()
        and not path.is_symlink()
        and (path / "SKILL.md").is_file()
        and not (path / "SKILL.md").is_symlink()
    ]


def skill_router(root: Path | None = None, settings: Any = None) -> APIRouter:
    directory = root if root is not None else Path(__file__).resolve().parents[3] / "skills"
    router = APIRouter()

    @router.get("/skills")
    def list_skills() -> list[dict[str, Any]]:
        overrides = settings.snapshot() if settings is not None else None
        return list_skill_catalogue(directory, overrides)

    @router.get("/skills/{skill_id}/files/{file_path:path}")
    def read_file(skill_id: str, file_path: str) -> dict[str, str]:
        return {"content": _read_text(_file_path(directory, skill_id, file_path))}

    @router.put("/skills/{skill_id}/files/{file_path:path}")
    def write_file(skill_id: str, file_path: str, update: SkillFileUpdate) -> dict[str, str]:
        path = _file_path(directory, skill_id, file_path)
        _read_text(path)
        if len(update.content.encode("utf-8")) > MAX_FILE_BYTES:
            raise HTTPException(413, "File is too large to edit")
        path.write_text(update.content, encoding="utf-8")
        return {"content": update.content}

    return router
