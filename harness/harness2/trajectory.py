"""Trajectories for single-shot agents: recording, persistence, rendering.

A trajectory is the ordered record of one rollout: every model call
(request messages, system prompt included), every reply, repair and
validator events, and the final artifact or error. It is captured by
`RecordingGateway`, a decorator around the solver's `ModelGateway`,
plus result events the adapter appends after execution. Events are
persisted as JSONL in the run directory and rendered in one grammar
(`[ACTION]` / `[OBSERVATION]` / `[ERROR]`).

Truncation is explicit and floored: an observation budget below
`MIN_OBSERVATION_CHARS` is rejected outright, because clipping
harder than that would fabricate defects the run never showed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asf.contracts.models import ModelRequest, ModelResponse

__all__ = [
    "MIN_OBSERVATION_CHARS",
    "RecordingGateway",
    "TrajectoryRecorder",
    "load_events",
    "render_trajectory",
    "save_events",
]

MIN_OBSERVATION_CHARS = 10_000

Event = dict[str, Any]


class TrajectoryRecorder:
    """Collects the events of one rollout, in order."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def record_call(self, request: ModelRequest) -> None:
        self.events.append(
            {
                "kind": "call",
                "model": request.model,
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in request.messages
                ],
            }
        )

    def record_reply(self, response: ModelResponse) -> None:
        self.events.append({"kind": "reply", "model": response.model, "content": response.content})

    def record_error(self, stage: str, message: str) -> None:
        self.events.append({"kind": "error", "stage": stage, "message": message})

    def record_issues(self, text: str) -> None:
        self.events.append({"kind": "issues", "text": text})

    def record_artifact(
        self, artifact_type: str, artifact_id: str, version: str, text: str
    ) -> None:
        self.events.append(
            {
                "kind": "artifact",
                "type": artifact_type,
                "id": artifact_id,
                "version": version,
                "text": text,
            }
        )


class RecordingGateway:
    """ModelGateway decorator that records every call into a recorder."""

    def __init__(self, inner: Any, recorder: TrajectoryRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def complete(self, request: ModelRequest) -> ModelResponse:
        self._recorder.record_call(request)
        try:
            response = self._inner.complete(request)
        except Exception as error:
            self._recorder.record_error("model", f"{type(error).__name__}: {error}")
            raise
        self._recorder.record_reply(response)
        return response


def save_events(path: Path, events: list[Event]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event, ensure_ascii=True) for event in events]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def load_events(path: Path) -> list[Event]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _clip(text: str, obs_trunc: int) -> str:
    if obs_trunc < MIN_OBSERVATION_CHARS:
        raise ValueError(
            f"observation truncation of {obs_trunc} chars is below the "
            f"{MIN_OBSERVATION_CHARS}-char floor; it would fabricate defects"
        )
    if len(text) <= obs_trunc:
        return text
    return text[:obs_trunc] + f"\n[TRUNCATED {len(text) - obs_trunc} chars]"


def _render_call(event: Event, obs_trunc: int) -> list[str]:
    lines = [f"[ACTION] model call (model={event.get('model')})"]
    for message in event.get("messages", []):
        lines.append(f"[OBSERVATION] message/{message['role']}:")
        lines.append(_clip(str(message["content"]), obs_trunc))
    return lines


def _render_event(event: Event, obs_trunc: int) -> list[str]:
    kind = event.get("kind")
    if kind == "call":
        return _render_call(event, obs_trunc)
    if kind == "reply":
        return ["[OBSERVATION] reply:", _clip(str(event.get("content", "")), obs_trunc)]
    if kind == "error":
        return [f"[ERROR] {event.get('stage')}: {event.get('message')}"]
    if kind == "issues":
        return [f"[OBSERVATION] validator issues: {event.get('text')}"]
    if kind == "artifact":
        header = (
            f"[OBSERVATION] artifact {event.get('type')} {event.get('id')} v{event.get('version')}:"
        )
        return [header, _clip(str(event.get("text", "")), obs_trunc)]
    return [f"[OBSERVATION] {kind}: {event}"]


def render_trajectory(events: list[Event], *, obs_trunc: int) -> str:
    """Render recorded events in the [ACTION]/[OBSERVATION]/[ERROR] grammar."""
    if obs_trunc < MIN_OBSERVATION_CHARS:
        raise ValueError(
            f"observation truncation of {obs_trunc} chars is below the "
            f"{MIN_OBSERVATION_CHARS}-char floor; it would fabricate defects"
        )
    lines: list[str] = []
    for event in events:
        lines.extend(_render_event(event, obs_trunc))
    return "\n".join(lines)
