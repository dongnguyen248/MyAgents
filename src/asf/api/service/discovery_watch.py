"""Make a mis-pointed run store loud instead of silently empty.

Discovery treats a broken or wrong store exactly like an empty
one: per-project and per-run failures are logged and skipped, so a
backend pointed at the wrong MariaDB (or started without its .env)
serves an empty task list that looks like a genuinely empty
system. This mixin adds the aggregate signal: the store label is
logged once, and a discovery that finds zero runs across a
non-empty registry warns once, naming the store and — when the
store can say so — the projects it holds that nobody registered.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from asf.orchestrator.execution import WorkflowExecution

logger = logging.getLogger("asf.api.service")

_MAX_ORPHAN_IDS = 3


def store_label(store: Any) -> str:
    """A credential-free name for a store: host:port/database.

    Stores that carry a connection config (the MariaDB store) are
    named by it — host, port and database only, never the user or
    password; anything else is named by its class.
    """
    config = getattr(store, "config", None) or getattr(store, "_config", None)
    host = getattr(config, "host", None)
    port = getattr(config, "port", None)
    database = getattr(config, "database", None)
    if host is not None and port is not None and database is not None:
        return f"{host}:{port}/{database}"
    return type(store).__name__


class DiscoveryWatchMixin:
    _store: Any
    _projects: dict[str, dict[str, Any]]
    _store_runs: dict[str, WorkflowExecution]

    _store_label_logged: bool = False
    _empty_store_warned: bool = False

    def _begin_discovery(self) -> bool:
        """Gate discovery on a store existing; log its label once."""
        if self._store is None:
            return False
        if not self._store_label_logged:
            self._store_label_logged = True
            logger.info("Run store: %s", store_label(self._store))
        return True

    def _note_discovery_result(self) -> None:
        """Warn once when discovery across the registry found nothing."""
        if self._store_runs:
            self._empty_store_warned = False
            return
        if not self._projects or self._empty_store_warned:
            return
        self._empty_store_warned = True
        logger.warning(
            "Run discovery found no runs in store %s across %d registered"
            " project(s); the task list will look empty. Check the MariaDB"
            " host/port and that .env was loaded from the repo root.%s",
            store_label(self._store),
            len(self._projects),
            self._orphan_clause(),
        )

    def _orphan_clause(self) -> str:
        """Name store projects the registry does not know, if cheap.

        Reuses the store's existing summary listing with no project
        filter; any failure (including the broken store that made
        discovery empty in the first place) just drops the clause.
        """
        summaries = getattr(self._store, "list_execution_summaries", None)
        if not callable(summaries):
            return ""
        try:
            rows = summaries(None)
        except Exception:
            return ""
        unknown: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            project_id = row.get("projectId")
            if isinstance(project_id, str) and project_id not in self._projects:
                unknown.add(project_id)
        if not unknown:
            return ""
        ordered = sorted(unknown)
        named = ", ".join(ordered[:_MAX_ORPHAN_IDS])
        return f" The store holds executions for {len(ordered)} unregistered project(s): {named}."
