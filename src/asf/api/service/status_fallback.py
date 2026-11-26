"""Truthful workflow status when the engine cannot load a run.

A stored run whose definition or execution policy no longer matches
the engine's raises inside ``engine.workflow_run``. The view must say
so (``UNKNOWN``) instead of guessing ``RUNNING``: a terminal run
reported as running looks alive forever and poisons every consumer
that branches on status. The failure is logged once per
(run, exception type) because status is read on every request.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

_SEEN_CAP = 1024
_seen: OrderedDict[tuple[str, str], None] = OrderedDict()


def engine_status(engine: Any, run: Any) -> str:
    """The engine's status for ``run``, or UNKNOWN when it raises."""
    try:
        return str(engine.workflow_run(run.id)["status"])
    except Exception as error:
        _log_once(run.id, error)
        return "UNKNOWN"


def waiting_fallthrough(status: str) -> tuple[str, list[str]]:
    """Waiting kind/actions when no specific wait matched.

    Only a run known to be RUNNING may claim a step in flight;
    UNKNOWN (engine cannot load the run) claims neither.
    """
    if status == "RUNNING":
        return "STEP_RUNNING", ["cancel"]
    return "NONE", []


def _log_once(run_id: str, error: Exception) -> None:
    key = (run_id, type(error).__name__)
    if key in _seen:
        return
    _seen[key] = None
    while len(_seen) > _SEEN_CAP:
        _seen.popitem(last=False)
    logger.warning(
        "workflow status unavailable for run %s: %s: %s",
        run_id,
        type(error).__name__,
        error,
    )
