"""Structured PR/MR descriptions for change requests ASF opens.

Implements the repo's PR/MR description rule (see the "Pull
Request / Merge Request description" section of the root
``AGENTS.md``): a description is built from structured fields by
``render_description`` and checked by the pure
``validate_description`` before anything is opened. A description
with problems must never reach the provider.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from asf.tools.changeset import ChangeSet

__all__ = [
    "SECTION_HEADINGS",
    "ChangeRequestDescription",
    "ChangeRequestInfo",
    "build_change_request_text",
    "change_request_description",
    "render_description",
    "test_commands_of",
    "validate_description",
]

SECTION_HEADINGS = (
    "## What",
    "## Why",
    "## How",
    "## Verification",
    "## Risk & Rollback",
    "## Context",
)

_HEADING_PREFIX = "## "
_PLACEHOLDER_TOKENS = ("TODO", "TBD")
_GROUP_HOW_THRESHOLD = 20
_OPERATION_VERBS = {"create": "created", "modify": "modified", "delete": "deleted"}


@dataclass(frozen=True)
class ChangeRequestDescription:
    """The structured fields a PR/MR description is rendered from."""

    summary: str
    changes: tuple[str, ...]
    why: str
    how: tuple[str, ...]
    verification: tuple[str, ...]
    risk: str
    blast_radius: str
    rollback: str
    resolves: str = "None"
    relates_to: str = "None"
    adr: str = "None"


@dataclass(frozen=True)
class ChangeRequestInfo:
    """What the hosting action knows when it opens a change request."""

    title: str
    task_id: str
    run_id: str
    branch: str
    base_branch: str
    test_commands: tuple[str, ...] = ()


def render_description(fields: ChangeRequestDescription) -> str:
    """Render the six required sections, in the required order."""
    lines = [
        "## What",
        fields.summary,
        "",
        *_bullets(fields.changes),
        "",
        "## Why",
        fields.why,
        "",
        "## How",
        *_bullets(fields.how),
        "",
        "## Verification",
        *_bullets(fields.verification),
        "",
        "## Risk & Rollback",
        fields.risk,
        "",
        f"Blast radius: {fields.blast_radius}",
        "",
        f"Rollback: {fields.rollback}",
        "",
        "## Context",
        f"Resolves: {fields.resolves}",
        f"Relates to: {fields.relates_to}",
        f"ADR/RFC: {fields.adr}",
    ]
    return "\n".join(lines) + "\n"


def _bullets(lines: tuple[str, ...]) -> list[str]:
    return [f"- {line}" for line in lines]


def validate_description(text: str) -> list[str]:
    """Return the description's problems ([] means it may be opened).

    Pure and deterministic: heading presence, duplication and
    order; empty sections; leftover placeholders or HTML comments;
    TODO/TBD; a Verification section that neither quotes a command
    nor states what was not run; and any other level-2 heading
    (bot-summary sections are not allowed).
    """
    problems: list[str] = []
    headings = _headings(text)
    problems.extend(_heading_problems(headings))
    problems.extend(_section_problems(text, headings))
    if "<!--" in text:
        problems.append("leftover HTML comment")
    for token in _PLACEHOLDER_TOKENS:
        if re.search(rf"\b{token}\b", text):
            problems.append(f"leftover placeholder: {token}")
    return problems


def _headings(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.startswith(_HEADING_PREFIX)]


def _heading_problems(headings: list[str]) -> list[str]:
    problems: list[str] = []
    for heading in SECTION_HEADINGS:
        count = headings.count(heading)
        if count == 0:
            problems.append(f"missing heading: {heading}")
        elif count > 1:
            problems.append(f"duplicated heading: {heading}")
    for heading in headings:
        if heading not in SECTION_HEADINGS:
            problems.append(f"unexpected heading (bot-summary sections are not allowed): {heading}")
    return problems + _order_problems(headings)


def _order_problems(headings: list[str]) -> list[str]:
    present = [heading for heading in headings if heading in SECTION_HEADINGS]
    expected = [heading for heading in SECTION_HEADINGS if heading in present]
    return ["headings out of order"] if present != expected else []


def _section_problems(text: str, headings: list[str]) -> list[str]:
    problems: list[str] = []
    bodies = _section_bodies(text)
    for heading in SECTION_HEADINGS:
        if heading in headings and not bodies.get(heading, "").strip():
            problems.append(f"empty section: {heading}")
    verification = bodies.get("## Verification", "")
    if verification.strip() and not _verification_ok(verification):
        problems.append("Verification lists no command and does not state what was not run")
    return problems


def _section_bodies(text: str) -> dict[str, str]:
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith(_HEADING_PREFIX):
            current = line.rstrip()
            bodies.setdefault(current, [])
        elif current is not None:
            bodies[current].append(line)
    return {heading: "\n".join(lines) for heading, lines in bodies.items()}


def _verification_ok(body: str) -> bool:
    if "not run" in body.lower():
        return True
    return any(" " in span for span in re.findall(r"`([^`]+)`", body))


def change_request_description(
    info: ChangeRequestInfo, changes: ChangeSet
) -> ChangeRequestDescription:
    """Build the fields for a change request ASF opens for a task run.

    Everything stated comes from the run itself: the change set,
    the task and run ids, the branches, and the project's own test
    commands. The run reaches the CI step only after its test step
    has passed, so configured test commands are reported as passed
    in this run; a project without test commands gets an explicit
    "not run" line instead of an invented result.
    """
    counts = _operation_counts(changes)
    return ChangeRequestDescription(
        summary=info.title.strip() or info.task_id,
        changes=(
            f"Change set for task {info.task_id} (run {info.run_id}): "
            f"{counts} across {len(changes.changes)} file(s).",
            "Produced by the AI Software Agents implement step; no human has edited these files.",
        ),
        why=_why_text(info),
        how=tuple(_how_lines(changes)),
        verification=tuple(_verification_lines(info)),
        risk=_RISK_TEXT,
        blast_radius=(
            f"only branch `{info.branch}` and this change request. "
            f"The base branch `{info.base_branch}` is explicitly untouched until merge."
        ),
        rollback=(
            f"close this change request and delete the branch: "
            f"`git push origin --delete {info.branch}`. "
            "If it was already merged, revert the merge commit."
        ),
        relates_to=f"task {info.task_id} (run {info.run_id})",
    )


_RISK_TEXT = (
    "Two-way door: opening this change request changes nothing on the "
    "base branch; a human decides whether it merges, and the branch "
    "can be deleted without side effects."
)


def _why_text(info: ChangeRequestInfo) -> str:
    return (
        f"Task {info.task_id} was implemented by an AI agent run. The change "
        "set needs the project's pipeline checks and a human merge decision "
        "before it lands; the project maintainers are the reviewers."
    )


def build_change_request_text(info: ChangeRequestInfo, changes: ChangeSet) -> str:
    """Compose the builder and the renderer: fields in, markdown out."""
    return render_description(change_request_description(info, changes))


def test_commands_of(profile: Mapping[str, Any]) -> tuple[str, ...]:
    """The profile's `configuration.testCommands` as display strings."""
    configuration = profile.get("configuration")
    raw = configuration.get("testCommands") if isinstance(configuration, Mapping) else None
    if not isinstance(raw, list):
        return ()
    return tuple(
        " ".join(item)
        for item in raw
        if isinstance(item, list) and all(isinstance(part, str) for part in item)
    )


def _operation_counts(changes: ChangeSet) -> str:
    counts = {operation: 0 for operation in _OPERATION_VERBS}
    for change in changes.changes:
        counts[change.operation] += 1
    parts = [
        f"{count} {_OPERATION_VERBS[operation]}" for operation, count in counts.items() if count
    ]
    return ", ".join(parts)


def _how_lines(changes: ChangeSet) -> list[str]:
    if len(changes.changes) <= _GROUP_HOW_THRESHOLD:
        return [
            f"`{change.path}` - {_OPERATION_VERBS[change.operation]} by the implement step"
            for change in changes.changes
        ]
    grouped: dict[str, list[str]] = {}
    for change in changes.changes:
        top = change.path.split("/", 1)[0] if "/" in change.path else change.path
        grouped.setdefault(top, []).append(_OPERATION_VERBS[change.operation])
    return [
        f"`{top}` - {len(verbs)} file(s): {', '.join(sorted(set(verbs)))}"
        for top, verbs in sorted(grouped.items())
    ]


def _verification_lines(info: ChangeRequestInfo) -> list[str]:
    lines: list[str] = []
    for command in info.test_commands:
        lines.append(f"`{command}` - passed in this run's test step, before this step")
    if not lines:
        lines.append("Automated tests: not run - the project profile configures no test commands")
    lines.append(
        f"Provider pipeline for branch `{info.branch}`: this step reads its "
        "status after opening and the run fails unless it passes"
    )
    lines.append(
        "Manual: not performed - the reviewer should read the change set "
        "diff and check the pipeline result before merging"
    )
    return lines
