"""Repository listing support for the Task agent.

The breakdown is written against a bounded tree listing of the run's
repository (built by the shared repo-map tree builder). The listing
also grounds an advisory check: an expectedFile that is absent from
the listing is usually a new file to create, but one whose basename
matches a listed file looks like a wrong folder or wrong case for
existing code — worth a warning, never an error.
"""

from __future__ import annotations

import logging

from asf.agents._shared.repomap import TreeListing, build_tree_listing
from asf.agents.task.items import TaskItem
from asf.tools.ports import RepositoryPort

logger = logging.getLogger(__name__)

__all__ = [
    "expected_file_warnings",
    "log_expected_file_warnings",
    "repository_listing",
]


def repository_listing(repository: RepositoryPort | None) -> TreeListing | None:
    """The run repository's tree listing, or None when there is none."""
    if repository is None:
        return None
    listing = build_tree_listing(repository, ref="HEAD")
    return listing if listing.paths else None


def expected_file_warnings(
    tasks: list[TaskItem], listing: TreeListing | None
) -> list[dict[str, str]]:
    """Flags expectedFiles that look like mis-named existing code."""
    if listing is None:
        return []
    listed = set(listing.paths)
    by_basename: dict[str, str] = {}
    for listed_path in listing.paths:
        by_basename.setdefault(listed_path.rsplit("/", 1)[-1].lower(), listed_path)
    warnings: list[dict[str, str]] = []
    for task in tasks:
        for path in task.expected_files:
            if path in listed:
                continue
            twin = by_basename.get(path.rsplit("/", 1)[-1].lower())
            if twin is not None:
                warnings.append({"task": task.id, "path": path, "similarTo": twin})
    return warnings


def log_expected_file_warnings(warnings: list[dict[str, str]]) -> None:
    for warning in warnings:
        logger.warning(
            "Task %s: expectedFile '%s' is not in the repository listing; "
            "a file with that name exists at '%s'",
            warning["task"],
            warning["path"],
            warning["similarTo"],
        )
