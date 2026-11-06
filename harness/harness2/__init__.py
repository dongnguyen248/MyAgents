"""Harness²-style improvement loop for the ASF agents (offline, human-gated).

Implemented up to stage H2 — see `docs/architecture/harness2.md`.
The metrics trigger in `trigger.py` is not the method; it only decides
which agent deserves an improvement cycle.
"""

from harness.harness2.adapter import TaskAdapter
from harness.harness2.ledger import Ledger, expected_rollouts, expected_sessions
from harness.harness2.trigger import (
    ImprovementTrigger,
    MetricsImprovementTrigger,
    MetricsOverview,
    NullImprovementTrigger,
    Suggestion,
    default_trigger,
)

__all__ = [
    "ImprovementTrigger",
    "Ledger",
    "MetricsImprovementTrigger",
    "MetricsOverview",
    "NullImprovementTrigger",
    "Suggestion",
    "TaskAdapter",
    "default_trigger",
    "expected_rollouts",
    "expected_sessions",
]
