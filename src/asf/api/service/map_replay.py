"""JSONL persistence for live-map replays: one file per run.

The hub feeds every pulse to :class:`MapReplayStore` as a sink. The
sink only enqueues; a single daemon writer thread owns all disk I/O,
so the tap stays non-blocking and a disk failure can never reach an
agent - it disables the writer, logs once, and the run continues.

Layout: ``<data_dir>/map-runs/<run_id>.jsonl`` - one JSON pulse per
line (the same contract dict the snapshot serves), then, when the
hub marks the run closed, one footer line with the hub's cumulative
counters, the budget and a ``truncated`` flag. A run that dies
mid-flight simply has no footer, which the UI reports as incomplete.
Files are capped per run (event count and bytes); past the cap only
the footer is still written, carrying the true totals. Retention is
swept at startup: files older than 7 days or beyond the newest 50
runs are deleted. Files are owner-only (0600).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue
from typing import Any, TextIO

from asf.api.service.map_hub import MapHub
from asf.contracts.map_events import MapEvent

__all__ = [
    "MAX_BYTES_PER_RUN",
    "MAX_EVENTS_PER_RUN",
    "MapReplayStore",
    "active_replay_store",
    "set_active_replay_store",
    "valid_run_id",
]

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_RUN = 2000
MAX_BYTES_PER_RUN = 1_000_000
RETENTION_DAYS = 7
RETENTION_RUNS = 50
_FILE_SUFFIX = ".jsonl"
_FOOTER_TYPE = "footer"
_DIR_MODE = 0o700
_FILE_MODE = 0o600

# Run ids become file names, so the shape is deliberately tight:
# no dots, no separators, no way to climb out of the directory.
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def valid_run_id(run_id: str) -> bool:
    return bool(_RUN_ID.match(run_id))


class _RunFile:
    """Writer-thread state for one run's open file."""

    def __init__(self, handle: TextIO) -> None:
        self.handle = handle
        self.events = 0
        self.bytes_written = 0
        self.truncated = False


class _Caps:
    """Per-run file caps: past either one, only the footer is written."""

    def __init__(self, max_events: int, max_bytes: int) -> None:
        self.max_events = max_events
        self.max_bytes = max_bytes


class MapReplayStore:
    """Buffered JSONL writer plus the read side for replay routes."""

    def __init__(
        self,
        directory: Path,
        hub: MapHub,
        *,
        max_events: int = MAX_EVENTS_PER_RUN,
        max_bytes: int = MAX_BYTES_PER_RUN,
    ) -> None:
        self._directory = directory
        self._hub = hub
        self._caps = _Caps(max_events, max_bytes)
        self._queue: Queue[tuple[str, str, MapEvent | None]] = Queue()
        self._files: dict[str, _RunFile] = {}
        self._disabled = False
        self._logged = False

    def start(self) -> None:
        """Creates the directory, sweeps retention, starts the writer."""
        try:
            self._directory.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
            self.sweep()
        except OSError as error:
            self._disable(error)
            return
        thread = threading.Thread(target=self._run_loop, name="asf-map-replay", daemon=True)
        thread.start()

    def observe(self, event: MapEvent) -> None:
        """Hub sink: enqueue only. Never blocks, never raises."""
        if self._disabled or not valid_run_id(event.run_id):
            return
        with suppress(Exception):
            self._queue.put_nowait(("event", event.run_id, event))

    def close_run(self, run_id: str) -> None:
        """Hub close sink: queue the footer for a finished run."""
        if self._disabled or not valid_run_id(run_id):
            return
        with suppress(Exception):
            self._queue.put_nowait(("footer", run_id, None))

    def flush(self) -> None:
        """Blocks until the writer has drained the queue (tests)."""
        self._queue.join()

    def sweep(self) -> None:
        """Retention: drop files past the age limit or the run count."""
        files = self._run_files()
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        cutoff = time.time() - RETENTION_DAYS * 24 * 3600
        for index, path in enumerate(files):
            if index >= RETENTION_RUNS or path.stat().st_mtime < cutoff:
                with suppress(OSError):
                    path.unlink()

    def list_replays(self) -> list[dict[str, Any]]:
        """One summary per stored run, newest first, read from disk -
        so runs from before a backend restart are listed too."""
        summaries = [self._summarize(path) for path in self._run_files()]
        summaries.sort(key=lambda item: item["startedAt"] or "", reverse=True)
        return summaries

    def read_replay(self, run_id: str) -> dict[str, Any] | None:
        path = self._path_for(run_id)
        if path is None or not path.is_file():
            return None
        events: list[dict[str, Any]] = []
        footer: dict[str, Any] | None = None
        with suppress(OSError):
            for line in path.read_text(encoding="utf-8").splitlines():
                parsed = _parse_line(line)
                if parsed is None:
                    continue
                if parsed.get("type") == _FOOTER_TYPE:
                    footer = parsed
                else:
                    events.append(parsed)
        return _replay_payload(run_id, events, footer)

    def _run_files(self) -> list[Path]:
        if not self._directory.is_dir():
            return []
        return [
            path
            for path in self._directory.glob(f"*{_FILE_SUFFIX}")
            if valid_run_id(path.name[: -len(_FILE_SUFFIX)])
        ]

    def _path_for(self, run_id: str) -> Path | None:
        if not valid_run_id(run_id):
            return None
        path = self._directory / f"{run_id}{_FILE_SUFFIX}"
        if path.resolve().parent != self._directory.resolve():
            return None
        return path

    def _summarize(self, path: Path) -> dict[str, Any]:
        events, footer = self._scan(path)
        return {
            "runId": path.name[: -len(_FILE_SUFFIX)],
            "startedAt": _first_ts(path),
            "sizeBytes": path.stat().st_size,
            "events": footer.get("events", events) if footer else events,
            "complete": footer is not None,
            "truncated": bool(footer.get("truncated")) if footer else False,
        }

    def _scan(self, path: Path) -> tuple[int, dict[str, Any] | None]:
        count = 0
        footer: dict[str, Any] | None = None
        with suppress(OSError):
            for line in path.read_text(encoding="utf-8").splitlines():
                parsed = _parse_line(line)
                if parsed is None:
                    continue
                if parsed.get("type") == _FOOTER_TYPE:
                    footer = parsed
                else:
                    count += 1
        return count, footer

    def _run_loop(self) -> None:
        while True:
            kind, run_id, event = self._queue.get()
            try:
                self._dispatch(kind, run_id, event)
            except OSError as error:
                self._disable(error)
            finally:
                self._queue.task_done()

    def _dispatch(self, kind: str, run_id: str, event: MapEvent | None) -> None:
        if self._disabled:
            return
        if kind == "event" and event is not None:
            self._write_event(run_id, event)
        elif kind == "footer":
            self._write_footer(run_id)

    def _write_event(self, run_id: str, event: MapEvent) -> None:
        state = self._open(run_id)
        if state is None or state.truncated:
            return
        line = json.dumps(event.to_contract())
        if state.events >= self._caps.max_events or (
            state.bytes_written + len(line) + 1 > self._caps.max_bytes
        ):
            state.truncated = True
            return
        state.handle.write(line + "\n")
        state.handle.flush()
        state.events += 1
        state.bytes_written += len(line) + 1

    def _write_footer(self, run_id: str) -> None:
        state = self._files.pop(run_id, None)
        if state is None:
            return
        footer = {
            "type": _FOOTER_TYPE,
            "events": state.events,
            "truncated": state.truncated,
            "counters": self._hub.counters(run_id),
            "budget": self._hub.budget(run_id),
            "endedAt": datetime.now(UTC).isoformat(),
        }
        with suppress(OSError):
            state.handle.write(json.dumps(footer) + "\n")
            state.handle.close()

    def _open(self, run_id: str) -> _RunFile | None:
        state = self._files.get(run_id)
        if state is not None:
            return state
        path = self._path_for(run_id)
        if path is None:
            return None
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, _FILE_MODE)
        state = _RunFile(os.fdopen(descriptor, "a", encoding="utf-8"))
        self._files[run_id] = state
        return state

    def _disable(self, error: OSError) -> None:
        self._disabled = True
        for state in self._files.values():
            with suppress(OSError):
                state.handle.close()
        self._files.clear()
        if not self._logged:
            self._logged = True
            logger.error("Live map replay writer disabled after a disk error: %s", error)


def _parse_line(line: str) -> dict[str, Any] | None:
    with suppress(ValueError):
        parsed = json.loads(line)
        return parsed if isinstance(parsed, dict) else None
    return None


def _first_ts(path: Path) -> str | None:
    with suppress(OSError):
        with path.open(encoding="utf-8") as handle:
            parsed = _parse_line(handle.readline())
        ts = parsed.get("ts") if parsed else None
        return ts if isinstance(ts, str) else None
    return None


def _replay_payload(
    run_id: str, events: list[dict[str, Any]], footer: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "runId": run_id,
        "events": events,
        "counters": footer.get("counters") if footer else None,
        "budget": footer.get("budget") if footer else None,
        "complete": footer is not None,
        "truncated": bool(footer.get("truncated")) if footer else False,
    }


_active_store: MapReplayStore | None = None


def set_active_replay_store(store: MapReplayStore | None) -> None:
    global _active_store
    _active_store = store


def active_replay_store() -> MapReplayStore | None:
    return _active_store
