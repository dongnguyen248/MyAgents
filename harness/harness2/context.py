"""Evidence bundles: the budgeted digest an improver session sees (D4, D6).

Evidence is behavioral only: trajectories, `delivered` flags and
contract-validation outcomes. Scores, verdict artifacts and rubric
material never enter a bundle — the leak tripwire refuses them by
content marker and by source path. Truncation is explicit: every
clipped item is named in the bundle's `truncated` list and marked
inline, and the per-item budget is floored at the trajectory
grammar's 10,000-char observation minimum.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.harness2.surface import LEAK_MARKERS
from harness.harness2.trajectory import MIN_OBSERVATION_CHARS

__all__ = [
    "DEFAULT_PER_ITEM_CHARS",
    "EvidenceBundle",
    "EvidenceItem",
    "LeakTripwireError",
    "assert_source_allowed",
    "build_evidence",
]

DEFAULT_PER_ITEM_CHARS = 20_000
_RUBRIC_PATH_PREFIX = "rubric"


class LeakTripwireError(ValueError):
    """Raised when score material is offered as evidence."""


@dataclass(frozen=True)
class EvidenceItem:
    """One rollout's evidence: its label, trajectory text, outcome."""

    label: str
    trajectory: str
    delivered: bool


@dataclass(frozen=True)
class EvidenceBundle:
    """A task's evidence digest for one improver session."""

    task_id: str
    entries: tuple[EvidenceItem, ...]
    truncated: tuple[str, ...] = ()

    def render(self) -> str:
        blocks = [f"Evidence for task '{self.task_id}' ({len(self.entries)} rollouts)"]
        for entry in self.entries:
            outcome = "delivered" if entry.delivered else "not delivered"
            blocks.append(f"## rollout {entry.label} — {outcome}\n{entry.trajectory}")
        if self.truncated:
            blocks.append("Truncated items: " + ", ".join(self.truncated))
        return "\n\n".join(blocks)


def assert_source_allowed(path: Path) -> None:
    """Refuse rubric files as evidence sources, by path (D6)."""
    parts = [part.lower() for part in path.parts]
    if any(part.startswith(_RUBRIC_PATH_PREFIX) for part in parts):
        raise LeakTripwireError(f"rubric material is not evidence: {path}")


def _check_content(text: str, label: str) -> None:
    for marker in LEAK_MARKERS:
        if marker in text:
            raise LeakTripwireError(
                f"evidence for '{label}' contains the score marker '{marker}'; "
                "scores and verdict artifacts never enter evidence"
            )


def _clip_item(item: EvidenceItem, per_item_chars: int) -> tuple[EvidenceItem, bool]:
    if len(item.trajectory) <= per_item_chars:
        return item, False
    clipped = item.trajectory[:per_item_chars]
    clipped += f"\n[TRUNCATED {len(item.trajectory) - per_item_chars} chars]"
    return EvidenceItem(label=item.label, trajectory=clipped, delivered=item.delivered), True


def build_evidence(
    task_id: str,
    items: list[EvidenceItem],
    *,
    per_item_chars: int = DEFAULT_PER_ITEM_CHARS,
) -> EvidenceBundle:
    """Build a bundle, tripping on score markers and clipping openly."""
    if per_item_chars < MIN_OBSERVATION_CHARS:
        raise ValueError(
            f"per-item evidence budget of {per_item_chars} chars is below the "
            f"{MIN_OBSERVATION_CHARS}-char floor"
        )
    entries: list[EvidenceItem] = []
    truncated: list[str] = []
    for item in items:
        _check_content(item.trajectory, item.label)
        clipped, was_clipped = _clip_item(item, per_item_chars)
        entries.append(clipped)
        if was_clipped:
            truncated.append(item.label)
    return EvidenceBundle(task_id=task_id, entries=tuple(entries), truncated=tuple(truncated))
