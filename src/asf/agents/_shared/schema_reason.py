"""Schema-rejection diagnostics shared by the JSON-validating agents.

When a model's JSON reply fails schema validation, the operator
needs to know *what* was wrong — a missing field is a different
conversation from prose around the JSON. The reply itself is
untrusted content and is never echoed: everything here is built
from schema facts only (field locations, error kinds, the
schema's own expected values and the validating package's own
validator messages), with pydantic inputs excluded, and the
result is redacted and capped before it rides an error.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from asf.agents._shared.security import redact_text

__all__ = ["schema_problems", "schema_reason"]


def schema_problems(exc: Exception) -> str:
    """Field locations and error kinds from a validation failure.

    Input values are deliberately excluded (``include_input=False``):
    the model reply is untrusted content and must not be echoed, but
    "findings.0.line: int_parsing" is exactly what an operator needs
    to tell a truncated reply from a wrong-typed field.
    """
    if isinstance(exc, ValidationError):
        parts = []
        for entry in exc.errors(include_input=False):
            loc = ".".join(str(part) for part in entry["loc"]) or "(root)"
            parts.append(f"{loc}: {entry['type']}")
        return "; ".join(parts[:5])[:400] or "unparseable reply"
    return type(exc).__name__


#: The rejection reason carried in the error: long enough to name
#: the first few problems, short enough for an error banner.
_REASON_LIMIT = 240
_MAX_REASON_PROBLEMS = 3


def schema_reason(exc: Exception, stripped: str) -> str:
    """A short, operator-actionable reason the reply was rejected.

    Built only from schema facts — field locations, error kinds,
    the schema's own expected values and the validating package's
    validator messages — never from the reply itself (inputs are
    excluded from the error entries), then redacted and capped.
    """
    if isinstance(exc, RecursionError):
        return "JSON nested too deeply"
    if not isinstance(exc, ValidationError):
        return "not valid JSON"
    parts = [_problem_reason(entry, stripped) for entry in exc.errors(include_input=False)]
    reason = "; ".join(parts[:_MAX_REASON_PROBLEMS])
    extra = len(parts) - _MAX_REASON_PROBLEMS
    if extra > 0:
        reason += f"; and {extra} more"
    return redact_text(reason)[:_REASON_LIMIT] or "not valid JSON"


def _problem_reason(entry: ErrorDetails, stripped: str) -> str:
    loc = ".".join(str(part) for part in entry["loc"])
    kind = entry["type"]
    ctx = entry.get("ctx") or {}
    if kind == "json_invalid":
        return _json_reason(ctx, stripped)
    if kind == "literal_error":
        return f"unknown value at '{loc}' (expected {ctx.get('expected', 'a listed value')})"
    if kind == "value_error":
        return _value_reason(loc, ctx)
    if kind == "too_long":
        return _too_long_reason(loc, ctx)
    return _basic_reason(loc, kind)


def _basic_reason(loc: str, kind: str) -> str:
    if kind == "missing":
        return f"missing field '{loc}'"
    if kind == "extra_forbidden":
        return f"unexpected field '{loc}'"
    if kind.endswith("_type"):
        return f"wrong type at '{loc}'"
    if "too_short" in kind:
        return f"'{loc}' is too short"
    if loc:
        return f"{loc}: {kind}"
    return kind


def _json_reason(ctx: dict[str, Any], stripped: str) -> str:
    if "trailing characters" in str(ctx.get("error", "")):
        return "extra text after the JSON value"
    text = stripped.lstrip()
    if text[:1] not in ("{", "[", '"') and "{" in text:
        return "extra text before the JSON"
    return "not valid JSON"


def _value_reason(loc: str, ctx: dict[str, Any]) -> str:
    message = str(ctx.get("error", "invalid value"))
    if loc:
        return f"{loc}: {message}"
    return message


def _too_long_reason(loc: str, ctx: dict[str, Any]) -> str:
    limit = ctx.get("max_length", "?")
    if ctx.get("field_type") == "List":
        return f"'{loc}' has too many items (max {limit})"
    return f"'{loc}' is too long (max {limit} characters)"
