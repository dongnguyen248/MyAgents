"""Trimming test reports for model prompts.

The TEST_REPORT artifact keeps the FULL (redacted) command output
— up to 64KB per command — because it is the evidence record. But
feeding all of it into the fix/review prompts wastes most of the
context on passing-test noise. What a model needs from a failing
run is: the error lines, wherever they are, plus the tail of the
stream (where failures usually surface). This module extracts
exactly that, for prompts only; artifacts are never mutated.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

__all__ = ["DEFAULT_TAIL_LINES", "tail_artifact_for_prompt", "tail_text"]

DEFAULT_TAIL_LINES = 120

_ERROR_LINE = re.compile(
    r"FAIL|Error|Traceback|AssertionError|exit code|FAILED|panic:|Exception",
)


def tail_text(text: str, max_lines: int = DEFAULT_TAIL_LINES) -> str:
    """Error lines (anywhere) + the last ``max_lines`` lines.

    Order is preserved and lines are not duplicated; a marker line
    records when the middle was elided.
    """
    if max_lines <= 0:
        return text
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    tail_start = len(lines) - max_lines
    keep = [
        index for index, line in enumerate(lines)
        if index >= tail_start or _ERROR_LINE.search(line)
    ]
    if len(keep) == len(lines):
        return text
    parts: list[str] = []
    previous = -1
    for index in keep:
        if previous >= 0 and index > previous + 1:
            parts.append(f"… ({index - previous - 1} lines omitted)")
        parts.append(lines[index])
        previous = index
    return "\n".join(parts)


def tail_artifact_for_prompt(
    artifact: dict[str, Any], max_lines: int = DEFAULT_TAIL_LINES,
) -> dict[str, Any]:
    """A prompt-sized copy of a TEST_REPORT artifact dict.

    Only the structured report's command stdout/stderr are tailed;
    anything else is returned unchanged (same object when nothing
    applies, so callers can use it unconditionally).
    """
    if artifact.get("type") != "TEST_REPORT" or max_lines <= 0:
        return artifact
    content = artifact.get("content")
    if not isinstance(content, dict):
        return artifact
    report = content.get("report")
    if not isinstance(report, dict) or not isinstance(report.get("commands"), list):
        return artifact
    trimmed = deepcopy(artifact)
    for command in trimmed["content"]["report"]["commands"]:
        if isinstance(command, dict):
            for stream in ("stdout", "stderr"):
                value = command.get(stream)
                if isinstance(value, str):
                    command[stream] = tail_text(value, max_lines)
    return trimmed
