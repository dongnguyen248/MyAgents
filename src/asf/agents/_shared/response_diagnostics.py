"""Bounded evidence for unusable model replies.

The excerpt is built from redacted text only: the reply is passed
through ``redact_text`` before any window is taken, so a secret that
crosses the window boundary cannot leak a fragment.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from asf.agents._shared.security import redact_text
from asf.contracts.models import ModelResponse

__all__ = [
    "EXCERPT_CONTEXT_CHARS",
    "EXCERPT_MAX_CHARS",
    "ResponseEvidence",
    "diagnostic_details",
    "error_offset",
    "evidence_for",
]

EXCERPT_CONTEXT_CHARS: int = 80
EXCERPT_MAX_CHARS: int = 160

_LINE_COLUMN_RE = re.compile(r"line (\d+),? column (\d+)")


@dataclass(frozen=True)
class ResponseEvidence:
    content: str
    finish_reason: str | None
    repairs_attempted: int = 0
    offset: int | None = None
    excerpt_text: str | None = None


def evidence_for(
    response: ModelResponse,
    *,
    offset: int | None = None,
    repairs_attempted: int = 0,
    excerpt_text: str | None = None,
) -> ResponseEvidence:
    return ResponseEvidence(
        content=response.content,
        finish_reason=response.finish_reason,
        repairs_attempted=repairs_attempted,
        offset=offset,
        excerpt_text=excerpt_text,
    )


def diagnostic_details(
    evidence: ResponseEvidence,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = dict(extra or {})
    details["replyChars"] = len(evidence.content)
    details["finishReason"] = evidence.finish_reason
    details["repairsAttempted"] = evidence.repairs_attempted
    excerpt = _excerpt(evidence)
    if excerpt is not None:
        details["excerpt"] = excerpt
    return details


def error_offset(error: BaseException, text: str) -> int | None:
    if isinstance(error, json.JSONDecodeError):
        return _valid_offset(error.pos, text)
    if isinstance(error, ValidationError):
        return _validation_offset(error, text)
    return _offset_from_message(str(error), text)


def _validation_offset(error: ValidationError, text: str) -> int | None:
    for entry in error.errors(include_input=False):
        offset = _entry_offset(entry, text)
        if offset is not None:
            return offset
    return None


def _entry_offset(entry: Mapping[str, Any], text: str) -> int | None:
    ctx = entry.get("ctx") or {}
    for message in (str(ctx.get("error", "")), str(entry.get("msg", ""))):
        offset = _offset_from_message(message, text)
        if offset is not None:
            return offset
    return None


def _offset_from_message(message: str, text: str) -> int | None:
    match = _LINE_COLUMN_RE.search(message)
    if match is None:
        return None
    return _offset_from_line_column(text, int(match.group(1)), int(match.group(2)))


def _offset_from_line_column(text: str, line: int, column: int) -> int | None:
    if line < 1 or column < 1:
        return None
    lines = text.splitlines(True)
    if line > len(lines):
        return None
    line_start = sum(len(part) for part in lines[: line - 1])
    line_length = len(lines[line - 1])
    if column - 1 > line_length:
        return None
    return line_start + column - 1


def _valid_offset(offset: int, text: str) -> int | None:
    if 0 <= offset <= len(text):
        return offset
    return None


def _excerpt(evidence: ResponseEvidence) -> str | None:
    if evidence.offset is None:
        return None
    text = evidence.excerpt_text if evidence.excerpt_text is not None else evidence.content
    offset = _valid_offset(evidence.offset, text)
    if offset is None:
        return None
    redacted = redact_text(text)
    redacted_offset = len(redact_text(text[:offset]))
    excerpt = _window(redacted, redacted_offset)
    return excerpt or None


def _window(redacted: str, offset: int) -> str:
    start = max(0, offset - EXCERPT_CONTEXT_CHARS)
    end = min(len(redacted), start + EXCERPT_MAX_CHARS)
    if end - start < EXCERPT_MAX_CHARS:
        start = max(0, end - EXCERPT_MAX_CHARS)
    return redacted[start:end]
