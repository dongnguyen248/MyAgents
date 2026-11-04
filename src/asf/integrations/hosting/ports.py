"""Provider-neutral contract for git hosting + CI (Phase 8).

One port covers what the workflow's integration steps need from a code
host: push a change set to a branch, open (or find) the change request
for that branch, and read CI pipeline status. GitLab and GitHub have
adapters; the workflow engine only ever sees this contract, so the
host stays a swappable assembly choice — exactly like approvals.

Statuses are normalized across providers: pipelines report
PASS / FAIL / RUNNING / UNKNOWN and change requests are
open / merged / closed, whatever the provider calls them natively.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from asf.tools.changeset import ChangeSet

__all__ = [
    "ChangeRequestRef",
    "PipelineRef",
    "PushResult",
    "HostingError",
    "HostingProvider",
]


@dataclass(frozen=True)
class PushResult:
    branch: str
    commit_sha: str


@dataclass(frozen=True)
class ChangeRequestRef:
    id: str
    url: str
    state: str  # "open" | "merged" | "closed"
    branch: str


@dataclass(frozen=True)
class PipelineRef:
    id: str
    status: str  # "PASS" | "FAIL" | "RUNNING" | "UNKNOWN"
    url: str


class HostingError(Exception):
    """A hosting provider call failed.

    ``retryable`` marks transient failures (5xx, 429, transport errors)
    that a later attempt may succeed at; configuration and 4xx problems
    are not retryable.
    """

    def __init__(
        self, message: str, *, status: int | None = None, retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class HostingProvider(Protocol):
    """The operations the CI / merge workflow steps need from a host."""

    def push_changeset(
        self, *, branch: str, base_branch: str, changes: ChangeSet, message: str,
    ) -> PushResult:
        """Commit the change set onto ``branch`` (created from
        ``base_branch`` when missing; appended to when it exists)."""
        ...

    def open_change_request(
        self, *, branch: str, base_branch: str, title: str, description: str,
    ) -> ChangeRequestRef:
        """Return the open change request for ``branch``, creating it
        against ``base_branch`` when none is open."""
        ...

    def change_request(self, *, branch: str) -> ChangeRequestRef | None:
        """The most recent change request for ``branch``, any state."""
        ...

    def pipeline_status(
        self, *, branch: str,
    ) -> PipelineRef | None:
        """The latest CI pipeline for ``branch``; None when the project
        has no pipeline for it (e.g. no CI configured)."""
        ...
