"""Rollout / improver-session accounting with the Harness² budget identity.

Per task, a full Parallel(k) or Sequential(k) run costs exactly
R = 4k rollouts (k base + 2k candidate probes + k finals) and
P = 3k improver sessions (k INV + k DOM + k compositions). The
ledger records what actually happened — including dead rollouts,
which are recorded, never raised — and `assert_identity` proves the
run kept the budget shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Ledger", "expected_rollouts", "expected_sessions"]


def expected_rollouts(k: int) -> int:
    return 4 * k


def expected_sessions(k: int) -> int:
    return 3 * k


@dataclass
class Ledger:
    """Labels of every rollout and improver session of one task run."""

    rollouts: list[str] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)
    dead_rollouts: list[str] = field(default_factory=list)

    def record_rollout(self, label: str) -> None:
        self.rollouts.append(label)

    def record_session(self, label: str) -> None:
        self.sessions.append(label)

    def record_dead_rollout(self, label: str) -> None:
        self.dead_rollouts.append(label)

    def assert_identity(self, k: int) -> None:
        """Raise AssertionError unless R == 4k and P == 3k exactly."""
        if len(self.rollouts) != expected_rollouts(k):
            raise AssertionError(
                f"rollout identity broken: {len(self.rollouts)} rollouts, "
                f"expected {expected_rollouts(k)} for k={k}"
            )
        if len(self.sessions) != expected_sessions(k):
            raise AssertionError(
                f"session identity broken: {len(self.sessions)} sessions, "
                f"expected {expected_sessions(k)} for k={k}"
            )
