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


def parse_milestones(plan_text: str) -> list[Milestone]:
    """Parses milestones from PLAN markdown and returns typed Milestone objects.

    Raises:
        MilestoneValidationError: If milestone structure is invalid.
    """
    issues: list[str] = []
    milestones: list[Milestone] = []

    # Find all milestone headings (### M1: name, ### M2: name, etc.)
    milestone_pattern = re.compile(r"^###\s+(M\d+):\s*(.+)$", re.MULTILINE)
    matches = list(milestone_pattern.finditer(plan_text))

    if not matches:
        issues.append("No milestones found (expected at least one '### M1: ...' heading)")
    else:
        # Check max milestones
        if len(matches) > MAX_MILESTONES:
            issues.append(f"Too many milestones: {len(matches)} (maximum {MAX_MILESTONES})")

        # Check sequential IDs by numeric value
        expected_num = 1
        seen_ids: set[str] = set()

        for match in matches:
            mid = match.group(1).upper()  # M1, M2, etc.
            mname = match.group(2).strip()

            # Check sequential (numeric comparison)
            if milestone_number(mid) != expected_num:
                issues.append(
                    f"Milestone IDs must be sequential: expected M{expected_num}, got {mid}"
                )
            expected_num += 1

            # Check uniqueness
            if mid in seen_ids:
                issues.append(f"Duplicate milestone ID: {mid}")
            seen_ids.add(mid)

            # Extract the content until next milestone or end
            start = match.end()
            idx = matches.index(match)
            if idx + 1 < len(matches):
                next_start = matches[idx + 1].start()
            else:
                next_start = len(plan_text)
            content = plan_text[start:next_start].strip()

            # Parse fields
            deliverables = ""
            acceptance = ""
            depends_on_raw = ""

            for line in content.splitlines():
                line_stripped = line.strip()
                if line_stripped.startswith("- Deliverables:"):
                    deliverables = line_stripped[len("- Deliverables:") :].strip()
                elif line_stripped.startswith("- Acceptance criteria:"):
                    acceptance = line_stripped[len("- Acceptance criteria:") :].strip()
                elif line_stripped.startswith("- Depends on:"):
                    depends_on_raw = line_stripped[len("- Depends on:") :].strip()

            if not deliverables:
                issues.append(f"Milestone {mid}: missing 'Deliverables' field")
            if not acceptance:
                issues.append(f"Milestone {mid}: missing 'Acceptance criteria' field")
            if not depends_on_raw:
                issues.append(f"Milestone {mid}: missing 'Depends on' field")

            # Parse depends_on into tuple
            if depends_on_raw and depends_on_raw.lower() != "none":
                deps = tuple(d.strip() for d in depends_on_raw.split(",") if d.strip())
            else:
                deps = ()

            # Validate dependencies
            for dep in deps:
                if dep == mid:
                    issues.append(f"Milestone {mid}: self-dependency is not allowed")
                elif dep not in seen_ids:
                    issues.append(
                        f"Milestone {mid}: depends on later or non-existent milestone '{dep}'"
                    )

            milestones.append(
                Milestone(
                    id=mid,
                    name=mname,
                    deliverables=deliverables,
                    acceptance_criteria=acceptance,
                    depends_on=deps,
                )
            )

    if issues:
        raise MilestoneValidationError(issues)

    return milestones


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
