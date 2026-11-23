"""Live map wrappers for the tool ports: files, shell, network.

Assembly wraps the real RepositoryPort, SandboxPort and hosting
Transport with these when the live map is enabled, so every file
read, command run and HTTP call reports a pulse pair to the map.
A pulse carries a sanitized label only - the last two path levels,
the command name without arguments, the URL's host - never content,
arguments, headers or bodies, so a token riding in any of those can
never reach the map. Reporting is fail-safe: it resolves its
attribution from the ambient map context (an agent execution, a
wrapped workflow action) or the workspace binding, stays silent
when neither names a run, and can never change the wrapped call's
result, timing contract or exceptions.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter

from asf.contracts.map_events import (
    MapEvent,
    MapPhase,
    MapStation,
    MapStatus,
    host_label,
    path_label,
    shell_label,
)
from asf.integrations.hosting.http import HttpResponse, Transport
from asf.models.map_tap import current_map_context, default_map_tap, emit_safely
from asf.tools.changeset import ChangeSet
from asf.tools.ports import CommandResult, CommandSpec, RepositoryPort, SandboxPort, SandboxResult

__all__ = ["MapRepository", "MapSandbox", "MapTransport"]

BoundValue = Callable[[], str | None]


@dataclass(frozen=True)
class _Outcome:
    error_code: str | None = None
    duration_ms: int | None = None


@dataclass
class _Span:
    span_id: str
    run_id: str
    station: MapStation
    label: str
    task_id: str | None
    project_id: str | None
    agent_id: str | None
    parent_id: str | None
    started_at: datetime
    started_perf: float


class _Reporter:
    """Emits pulse pairs attributed to the current execution."""

    def __init__(self, bound_run: BoundValue | None, bound_project: BoundValue | None) -> None:
        self._bound_run = bound_run
        self._bound_project = bound_project
        self._counter = itertools.count(1)

    def start(self, station: MapStation, label: str, at: datetime | None = None) -> _Span | None:
        tap = default_map_tap()
        if tap is None:
            return None
        span = self._attributed_span(station, label, at)
        if span is None:
            return None
        emit_safely(tap, self._event(span, "start", "running", _Outcome()))
        return span

    def end(
        self,
        span: _Span | None,
        status: MapStatus,
        error_code: str | None = None,
        duration_ms: int | None = None,
    ) -> datetime | None:
        if span is None:
            return None
        tap = default_map_tap()
        if tap is None:
            return None
        if duration_ms is None:
            duration_ms = int((perf_counter() - span.started_perf) * 1000)
        emit_safely(tap, self._event(span, "end", status, _Outcome(error_code, duration_ms)))
        return span.started_at + timedelta(milliseconds=duration_ms)

    def _attributed_span(
        self, station: MapStation, label: str, at: datetime | None
    ) -> _Span | None:
        ctx = current_map_context()
        if ctx is not None:
            ctx.tool_calls += 1
            return _Span(
                span_id=f"{ctx.request_id}:tool:{ctx.tool_calls}",
                run_id=ctx.run_id,
                station=station,
                label=label,
                task_id=ctx.task_id,
                project_id=None,
                agent_id=ctx.agent_id,
                parent_id=ctx.request_id,
                started_at=at or datetime.now(UTC),
                started_perf=perf_counter(),
            )
        return self._bound_span(station, label, at)

    def _bound_span(self, station: MapStation, label: str, at: datetime | None) -> _Span | None:
        run_id = self._bound_run() if self._bound_run is not None else None
        if not run_id:
            return None
        return _Span(
            span_id=f"run:{run_id}:tool:{next(self._counter)}",
            run_id=run_id,
            station=station,
            label=label,
            task_id=None,
            project_id=self._bound_project() if self._bound_project is not None else None,
            agent_id=None,
            parent_id=None,
            started_at=at or datetime.now(UTC),
            started_perf=perf_counter(),
        )

    def _event(
        self, span: _Span, phase: MapPhase, status: MapStatus, outcome: _Outcome
    ) -> MapEvent:
        ts = span.started_at
        if phase == "end" and outcome.duration_ms is not None:
            ts = ts + timedelta(milliseconds=outcome.duration_ms)
        return MapEvent(
            id=f"{span.span_id}:{phase}",
            ts=ts,
            run_id=span.run_id,
            span_id=span.span_id,
            type="tool",
            station=span.station,
            phase=phase,
            status=status,
            label=span.label,
            task_id=span.task_id,
            project_id=span.project_id,
            agent_id=span.agent_id,
            parent_id=span.parent_id,
            duration_ms=outcome.duration_ms,
            error_code=outcome.error_code,
        )


class MapRepository:
    """RepositoryPort wrapper reporting one files pulse per call."""

    def __init__(
        self,
        inner: RepositoryPort,
        bound_run: BoundValue | None = None,
        bound_project: BoundValue | None = None,
    ) -> None:
        self._inner = inner
        self._reporter = _Reporter(bound_run, bound_project)

    def list_tree(self, ref: str, prefix: str = "") -> tuple[str, ...]:
        span = self._reporter.start("files", path_label(prefix) if prefix else "tree")
        try:
            result = self._inner.list_tree(ref, prefix)
        except Exception as error:
            self._reporter.end(span, "error", type(error).__name__)
            raise
        self._reporter.end(span, "ok")
        return result

    def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
        span = self._reporter.start("files", path_label(path))
        try:
            result = self._inner.read_file(path, ref, max_bytes)
        except Exception as error:
            self._reporter.end(span, "error", type(error).__name__)
            raise
        self._reporter.end(span, "ok")
        return result


class MapSandbox:
    """SandboxPort wrapper reporting one shell pulse per command.

    The port takes the whole batch at once, but the commands run
    sequentially inside it, so the pulses must not pretend they ran
    in parallel: only the first command's start is emitted up front.
    Each later start is emitted when the previous command's end is
    known, stamped with that end's timestamp and the command's own
    measured duration from its CommandResult - the emitted sequence
    is start, end, start, end, and at most one shell span is ever
    open at a time.
    """

    def __init__(
        self,
        inner: SandboxPort,
        bound_run: BoundValue | None = None,
        bound_project: BoundValue | None = None,
    ) -> None:
        self._inner = inner
        self._reporter = _Reporter(bound_run, bound_project)

    def run(
        self,
        commands: Sequence[CommandSpec],
        changes: ChangeSet,
        ref: str,
        *,
        fail_fast: bool = True,
    ) -> SandboxResult:
        spans: list[_Span | None] = []
        if commands:
            spans.append(self._reporter.start("shell", _command_label(commands[0])))
        try:
            result = self._inner.run(commands, changes, ref, fail_fast=fail_fast)
        except Exception as error:
            self._end_failed(spans, commands, error)
            raise
        self._end_sequence(spans, commands, result)
        return result

    def _end_sequence(
        self, spans: list[_Span | None], commands: Sequence[CommandSpec], result: SandboxResult
    ) -> None:
        at: datetime | None = None
        for index in range(len(commands)):
            span = spans[index] if index < len(spans) else None
            outcome = result.commands[index] if index < len(result.commands) else None
            if outcome is None:
                at = self._reporter.end(span, "blocked", None, 0)
            else:
                status, code = _command_status(outcome)
                at = self._reporter.end(span, status, code, outcome.duration_ms)
            if index + 1 < len(commands):
                spans.append(
                    self._reporter.start("shell", _command_label(commands[index + 1]), at=at)
                )

    def _end_failed(
        self, spans: list[_Span | None], commands: Sequence[CommandSpec], error: Exception
    ) -> None:
        at = self._reporter.end(spans[0] if spans else None, "error", type(error).__name__)
        for spec in commands[1:]:
            span = self._reporter.start("shell", _command_label(spec), at=at)
            at = self._reporter.end(span, "blocked", None, 0)


def _command_label(spec: CommandSpec) -> str:
    return shell_label(spec.argv[0]) if spec.argv else shell_label("")


def _command_status(outcome: CommandResult) -> tuple[MapStatus, str | None]:
    if outcome.skipped:
        return "blocked", None
    if outcome.timed_out:
        return "error", "TIMEOUT"
    if outcome.exit_code != 0:
        return "error", f"EXIT_{outcome.exit_code}"
    return "ok", None


class MapTransport:
    """Hosting Transport wrapper reporting one network pulse per call.

    Headers and body pass through untouched and are never read: the
    pulse label is the URL's host, nothing else about the request.
    """

    def __init__(
        self,
        inner: Transport,
        bound_run: BoundValue | None = None,
        bound_project: BoundValue | None = None,
    ) -> None:
        self._inner = inner
        self._reporter = _Reporter(bound_run, bound_project)

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse:
        span = self._reporter.start("network", host_label(url))
        try:
            response = self._inner(method, url, headers, body)
        except Exception as error:
            self._reporter.end(span, "error", type(error).__name__)
            raise
        if response.status >= 400:
            self._reporter.end(span, "error", f"HTTP_{response.status}")
        else:
            self._reporter.end(span, "ok")
        return response
