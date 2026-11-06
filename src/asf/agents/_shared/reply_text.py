"""Small text helpers for model replies, shared by the text agents."""

from __future__ import annotations

_MIN_FENCE_LINES = 2


def unwrap_code_fence(reply: str) -> str:
    """Remove one wrapping ``` fence from a reply, if it has one."""
    if not (reply.startswith("```") and reply.endswith("```")):
        return reply
    lines = reply.splitlines()
    if len(lines) >= _MIN_FENCE_LINES and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return reply


def heading_lines(reply: str, prefix: str = "## ") -> set[str]:
    return {line.strip() for line in reply.splitlines() if line.strip().startswith(prefix)}
