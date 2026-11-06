from __future__ import annotations

import re
from dataclasses import dataclass


class MilestoneValidationError(Exception):
    """Raised when milestone validation fails."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("\n".join(issues))


__all__ = [
    "Milestone",
    "MAX_MILESTONES",
    "parse_milestones",
    "milestone_ancestors",
    "milestone_number",
    "MilestoneValidationError",
]

MAX_MILESTONES: int = 20


@dataclass(frozen=True)
class Milestone:
    """Parsed milestone from a PLAN artifact."""

    id: str  # e.g., "M1"
    name: str  # e.g., "Setup"
    deliverables: str
    acceptance_criteria: str
    depends_on: tuple[str, ...]  # empty tuple for "none"


def milestone_number(mid: str) -> int:
    """Extract numeric part from milestone/task ID (M10 -> 10, T5 -> 5)."""
    return int(mid[1:])


_HEADING_PATTERN = re.compile(r"^###\s+(M\d+):\s*(.+)$", re.MULTILINE)

_NO_MILESTONES = "No milestones found (expected at least one '### M1: ...' heading)"


@dataclass
class _MilestoneScan:
    issues: list[str]
    milestones: list[Milestone]
    seen_ids: set[str]
    expected_num: int = 1


def parse_milestones(plan_text: str) -> list[Milestone]:
    """Parses milestones from PLAN markdown and returns typed Milestone objects.

    Raises:
        MilestoneValidationError: If milestone structure is invalid.
    """
    matches = list(_HEADING_PATTERN.finditer(plan_text))
    if not matches:
        raise MilestoneValidationError([_NO_MILESTONES])
    scan = _MilestoneScan(issues=[], milestones=[], seen_ids=set())
    if len(matches) > MAX_MILESTONES:
        scan.issues.append(f"Too many milestones: {len(matches)} (maximum {MAX_MILESTONES})")
    for index, match in enumerate(matches):
        content = _milestone_block(plan_text, matches, index, match)
        _scan_milestone(scan, match, content)
    if scan.issues:
        raise MilestoneValidationError(scan.issues)
    return scan.milestones


@dataclass(frozen=True)
class _MilestoneFields:
    deliverables: str
    acceptance: str
    depends_raw: str


def _scan_milestone(
    scan: _MilestoneScan, match: re.Match[str], content: str
) -> None:
    mid = match.group(1).upper()
    fields = _milestone_fields(content)
    _scan_sequence(scan, mid)
    _scan_fields(scan, mid, fields)
    deps = _dependencies(fields.depends_raw)
    _scan_dependencies(scan, mid, deps)
    scan.milestones.append(
        Milestone(
            id=mid,
            name=match.group(2).strip(),
            deliverables=fields.deliverables,
            acceptance_criteria=fields.acceptance,
            depends_on=deps,
        )
    )


def _scan_sequence(scan: _MilestoneScan, mid: str) -> None:
    if milestone_number(mid) != scan.expected_num:
        scan.issues.append(
            f"Milestone IDs must be sequential: expected M{scan.expected_num}, got {mid}"
        )
    scan.expected_num += 1
    if mid in scan.seen_ids:
        scan.issues.append(f"Duplicate milestone ID: {mid}")
    scan.seen_ids.add(mid)


def _milestone_block(
    plan_text: str,
    matches: list[re.Match[str]],
    index: int,
    match: re.Match[str],
) -> str:
    has_next = index + 1 < len(matches)
    next_start = matches[index + 1].start() if has_next else len(plan_text)
    return plan_text[match.end() : next_start].strip()


_FIELD_PREFIXES = (
    ("- Deliverables:", "deliverables"),
    ("- Acceptance criteria:", "acceptance"),
    ("- Depends on:", "depends_raw"),
)


def _milestone_fields(content: str) -> _MilestoneFields:
    values = {"deliverables": "", "acceptance": "", "depends_raw": ""}
    for line in content.splitlines():
        _capture_field(values, line.strip())
    return _MilestoneFields(
        deliverables=values["deliverables"],
        acceptance=values["acceptance"],
        depends_raw=values["depends_raw"],
    )


def _capture_field(values: dict[str, str], stripped: str) -> None:
    for prefix, key in _FIELD_PREFIXES:
        if stripped.startswith(prefix):
            values[key] = stripped[len(prefix) :].strip()
            return


def _scan_fields(scan: _MilestoneScan, mid: str, fields: _MilestoneFields) -> None:
    if not fields.deliverables:
        scan.issues.append(f"Milestone {mid}: missing 'Deliverables' field")
    if not fields.acceptance:
        scan.issues.append(f"Milestone {mid}: missing 'Acceptance criteria' field")
    if not fields.depends_raw:
        scan.issues.append(f"Milestone {mid}: missing 'Depends on' field")


def _dependencies(depends_raw: str) -> tuple[str, ...]:
    if depends_raw and depends_raw.lower() != "none":
        return tuple(part.strip() for part in depends_raw.split(",") if part.strip())
    return ()


def _scan_dependencies(scan: _MilestoneScan, mid: str, deps: tuple[str, ...]) -> None:
    for dep in deps:
        if dep == mid:
            scan.issues.append(f"Milestone {mid}: self-dependency is not allowed")
        elif dep not in scan.seen_ids:
            scan.issues.append(
                f"Milestone {mid}: depends on later or non-existent milestone '{dep}'"
            )


def milestone_ancestors(milestones: list[Milestone]) -> dict[str, frozenset[str]]:
    """Compute transitive dependencies (ancestors) for each milestone.

    Returns a dict mapping milestone ID -> frozenset of all ancestor milestone IDs
    (transitive closure of depends_on). Milestones with no dependencies map to empty frozenset.
    """
    # Build adjacency list: milestone -> direct dependencies
    deps_map: dict[str, tuple[str, ...]] = {m.id: m.depends_on for m in milestones}

    # Compute transitive closure for each milestone
    result: dict[str, frozenset[str]] = {}

    def get_ancestors(mid: str, visited: set[str] | None = None) -> frozenset[str]:
        if visited is None:
            visited = set()
        visited.add(mid)
        ancestors: set[str] = set()
        for dep in deps_map.get(mid, ()):
            ancestors.add(dep)
            ancestors.update(get_ancestors(dep, visited))
        return frozenset(ancestors)

    for m in milestones:
        result[m.id] = get_ancestors(m.id)

    return result
