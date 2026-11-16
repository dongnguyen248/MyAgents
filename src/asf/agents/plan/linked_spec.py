"""The Linked SPEC section of a plan reply: validation and stamping.

The section is traceability metadata the platform already knows (the
input SPEC artifact's id and version), so the agent stamps it into
the reply itself instead of failing the run when a model paraphrases
or omits the two lines - the same pattern as the Task agent's
deterministic markdown rendering. A reply whose section is already
correct is returned unchanged.
"""

from __future__ import annotations

from asf.contracts.models import Artifact

_HEADING = "## Linked SPEC"


def linked_spec_issues(reply: str, spec_art: Artifact) -> list[str]:
    found_section, found_id, found_version = _linked_spec_values(reply)
    if not found_section:
        return ["Missing '## Linked SPEC' section"]
    issues: list[str] = []
    if found_id is None:
        issues.append("Linked SPEC section missing 'ID:' line")
    elif found_id != spec_art.id:
        issues.append(
            f"Linked SPEC ID '{found_id}' does not match input SPEC artifact ID '{spec_art.id}'"
        )
    if found_version is None:
        issues.append("Linked SPEC section missing 'Version:' line")
    elif found_version != spec_art.version:
        issues.append(
            f"Linked SPEC version '{found_version}' does not match "
            f"input SPEC artifact version '{spec_art.version}'"
        )
    return issues


def stamp_linked_spec(reply: str, spec_art: Artifact) -> str:
    if not linked_spec_issues(reply, spec_art):
        return reply
    lines = reply.split("\n")
    stamped = [f"ID: {spec_art.id}", f"Version: {spec_art.version}"]
    heading_at = _heading_index(lines)
    if heading_at is None:
        return "\n".join(_inserted(lines, stamped))
    end = _section_end(lines, heading_at)
    body = [*stamped, ""] if end < len(lines) else stamped
    return "\n".join([*lines[: heading_at + 1], *body, *lines[end:]])


def _linked_spec_values(reply: str) -> tuple[bool, str | None, str | None]:
    found_section = False
    found_id: str | None = None
    found_version: str | None = None
    for line in reply.splitlines():
        stripped = line.strip()
        if stripped == _HEADING:
            found_section = True
            continue
        if not found_section:
            continue
        if stripped.startswith("## "):
            break
        if stripped.startswith("ID:"):
            found_id = stripped[3:].strip()
        elif stripped.startswith("Version:"):
            found_version = stripped[8:].strip()
    return found_section, found_id, found_version


def _heading_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == _HEADING:
            return index
    return None


def _section_end(lines: list[str], heading_at: int) -> int:
    for index in range(heading_at + 1, len(lines)):
        if lines[index].strip().startswith("## "):
            return index
    return len(lines)


def _inserted(lines: list[str], stamped: list[str]) -> list[str]:
    title_at = 1 if lines and lines[0].startswith("# ") else 0
    section = [_HEADING, *stamped, ""]
    return [*lines[:title_at], *section, *lines[title_at:]]
