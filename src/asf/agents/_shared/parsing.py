from __future__ import annotations

import json
import re
from typing import Any

__all__ = [
    "strip_code_fence",
    "parse_json",
    "ParseError",
]


class ParseError(Exception):
    """Raised when JSON parsing fails."""

    def __init__(self, message: str, *, raw: str | None = None) -> None:
        super().__init__(message)
        self.raw = raw


_CODE_FENCE_RE = re.compile(
    r"^```(?:\w+)?\n(.*?)\n```$",
    re.DOTALL,
)


def strip_code_fence(text: str) -> str:
    """Strip markdown code fences from text if present.

    Handles both ```language and ``` fences.
    If no fence is found, returns the text unchanged.
    """
    text = text.strip()
    match = _CODE_FENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    return text


def parse_json(text: str) -> dict[str, Any]:
    """Parse JSON with code fence stripping and clear error messages.

    Args:
        text: The JSON text, possibly wrapped in markdown code fences.

    Returns:
        Parsed JSON object as a dict.

    Raises:
        ParseError: If the text is not valid JSON.
    """
    stripped = strip_code_fence(text)
    try:
        result = json.loads(stripped)
        if not isinstance(result, dict):
            raise ParseError("JSON root must be an object", raw=text)
        return result
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON: {e.msg} at line {e.lineno}, column {e.colno}", raw=text)
