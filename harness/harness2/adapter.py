"""The TaskAdapter protocol: what the Harness² loop drives an agent through.

An adapter owns one agent type over a fixed task set. It builds the
frozen task inputs, executes one rollout under a given harness tree
(`None` = the agent's default harness), and answers the loop's
questions about the run directory it produced. `score` is the only
method whose result may carry quality information, and the loop
calls it only after selection is committed (design D6) — in H2 it
exists for shape only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from asf.contracts.models import AgentRequest
from harness.harness2.surface import Tree

__all__ = ["TaskAdapter"]


@runtime_checkable
class TaskAdapter(Protocol):
    """One agent type over a fixed task set, drivable by the loop."""

    agent_type: str

    def tasks(self) -> list[str]:
        """Task ids in stable order."""
        ...

    def domain_of(self, task_id: str) -> str:
        """The library grouping unit for a task (project profile / stack)."""
        ...

    def task_input(self, task_id: str) -> AgentRequest:
        """The frozen upstream inputs for a task, as an agent request."""
        ...

    def execute(self, task_id: str, harness: Tree | None, run_id: str) -> Path:
        """Run one rollout and return its run directory. Idempotent by run_id."""
        ...

    def delivered(self, run_dir: Path) -> bool:
        """Whether the rollout produced its deliverable artifact."""
        ...

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        """The rollout's rendered trajectory."""
        ...

    def deliverable_text(self, run_dir: Path) -> str:
        """The deliverable artifact's text ('' when not delivered)."""
        ...

    def base_harness(self) -> Tree:
        """The agent's default harness as a Tree."""
        ...

    def validate_tree(self, tree: Tree) -> None:
        """Raise ValueError, in actionable prose, for an invalid tree."""
        ...

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        """Post-selection scoring only; None means the judge failed."""
        ...
