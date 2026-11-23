"""Live map events: display-only pulses for the dashboard map.

Design inspired by lot-map (MIT, (c) Aleksei Volodin): a label holds
a name, never content. A map event therefore carries only metadata -
ids, a station, a status and a short sanitized label (a file name, a
command name, a host). Prompts, results and secrets never enter one.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field

from asf.contracts.models import ContractModel

__all__ = [
    "MAX_LABEL_CHARS",
    "MapEvent",
    "MapEventType",
    "MapPhase",
    "MapStation",
    "MapStatus",
    "clean_label",
    "host_label",
    "path_label",
    "shell_label",
]

MAX_LABEL_CHARS = 120

MapStation = Literal[
    "core",
    "operator",
    "model",
    "files",
    "shell",
    "network",
    "agents",
    "skills",
    "store",
    "gates",
]
MapEventType = Literal["agent", "model", "step", "gate", "run", "tool"]
MapPhase = Literal["start", "end", "moment"]
MapStatus = Literal["running", "ok", "error", "blocked"]


class MapEvent(ContractModel):
    """One pulse on the live map: a start, an end, or a moment."""

    id: str = Field(min_length=1)
    ts: AwareDatetime
    run_id: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    type: MapEventType
    station: MapStation
    phase: MapPhase
    status: MapStatus
    label: str = Field(max_length=MAX_LABEL_CHARS)
    task_id: str | None = None
    project_id: str | None = None
    agent_id: str | None = None
    parent_id: str | None = None
    step_id: str | None = None
    model: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    error_code: str | None = None


_KEPT_CATEGORIES = frozenset(
    [
        "Lu",
        "Ll",
        "Lt",
        "Lm",
        "Lo",
        "Mn",
        "Mc",
        "Me",
        "Nd",
        "Nl",
        "No",
        "Pc",
        "Pd",
        "Ps",
        "Pe",
        "Pi",
        "Pf",
        "Po",
        "Sm",
        "Sc",
        "Sk",
        "So",
        "Zs",
    ]
)
_JOINERS = frozenset({"\u200d", "\u200c"})


def _readable(char: str) -> bool:
    if char in _JOINERS:
        return True
    return unicodedata.category(char) in _KEPT_CATEGORIES


def clean_label(text: str, max_chars: int = MAX_LABEL_CHARS) -> str:
    """A label as it may be shown: names only, no control characters.

    Characters that take no room or steer a terminal (controls,
    format marks, line/paragraph separators) become spaces, runs of
    spaces collapse, and the result is cut to ``max_chars`` whole
    characters with an ellipsis.
    """
    spaced = "".join(char if _readable(char) else " " for char in text)
    collapsed = re.sub(r" {2,}", " ", spaced).strip()
    chars = list(collapsed)
    if len(chars) <= max_chars:
        return collapsed
    return "".join(chars[: max_chars - 1]) + "…"


def shell_label(command: str) -> str:
    """The name a shell pulse may show: the command, never its arguments."""
    first = command.strip().split(maxsplit=1)[0] if command.strip() else ""
    return clean_label(PurePath(first).name if first else "", 80)


def host_label(url: str) -> str:
    """The host a network pulse may show: no login, path or query."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return clean_label(url.strip().split(":", 1)[0], 40)
    if parts.hostname:
        return clean_label(parts.hostname, 40)
    return clean_label(parts.scheme or "", 40)


_PATH_SEPARATORS = re.compile(r"[/\\]+")


def path_label(path: str) -> str:
    """The path a files pulse may show: the last two levels only.

    Folder depth is the sensitive part of a path (drive, user home,
    project root), so a pulse keeps just ``parent/name`` - enough to
    recognise the file, never enough to locate the machine's layout.
    """
    parts = [part for part in _PATH_SEPARATORS.split(path.strip()) if part and part != "."]
    return clean_label("/".join(parts[-2:]), 80)
