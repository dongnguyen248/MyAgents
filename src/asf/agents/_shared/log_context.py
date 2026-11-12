"""The log context: which run/task/agent/request a log line is for.

Pure (contextvars only). ``BaseAgent.execute`` wraps every
execution in :func:`log_context`, setting the fields from the
request it is executing (the engine stamps the run id into the
request metadata); the backend's logging setup reads the current
values back through :func:`log_context_values` and stamps them on
every emitted line, so a failure's log evidence names the run that
produced it. Fields that were never set read as ``-``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

__all__ = ["log_context", "log_context_values"]

ABSENT = "-"

_run_id: ContextVar[str] = ContextVar("asf_log_run_id", default=ABSENT)
_task: ContextVar[str] = ContextVar("asf_log_task", default=ABSENT)
_agent: ContextVar[str] = ContextVar("asf_log_agent", default=ABSENT)
_request_id: ContextVar[str] = ContextVar("asf_log_request_id", default=ABSENT)


@contextmanager
def log_context(
    *,
    run_id: object = None,
    task: object = None,
    agent: object = None,
    request_id: object = None,
) -> Iterator[None]:
    """Set the log-context fields for the enclosed work.

    Only fields given a truthy value are set; every set field is
    reset on exit, so nested executions restore the outer context.
    Values are stringified — callers pass ids straight from their
    request objects without converting.
    """
    given = ((run_id, _run_id), (task, _task), (agent, _agent), (request_id, _request_id))
    tokens: list[tuple[ContextVar[str], Token[str]]] = []
    for value, var in given:
        if value:
            tokens.append((var, var.set(str(value))))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def log_context_values() -> tuple[str, str, str, str]:
    """The current (run, task, agent, request) values, ``-`` when unset."""
    return (_run_id.get(), _task.get(), _agent.get(), _request_id.get())
