"""Automatic splitting of oversized requirements into sub-tasks.

When a run's requirement is far beyond what one pipeline pass should
chew on (see ``SPLIT_REQUIREMENT_CHARS`` in the API service), the
service asks this decomposer to break it into a short sequence of
self-contained sub-requirements. Each part becomes a normal child run
of the platform — same agents, same approvals, same contracts — and
the parts execute one at a time, in order, under the original task as
their parent.

The decomposition itself is one model call through the platform's
ModelGateway (so the configured provider and the shared/strong model
apply), answered as strict JSON and validated hard: a bounded number
of parts, every part small enough to run unsplit, no part empty.
Anything unusable raises ValueError; the caller decides the fallback
(the service runs the task whole and surfaces the failure).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from asf.contracts.models import ModelMessage, ModelRequest
from asf.models.ports import ModelGateway

MAX_SPLIT_PARTS = 6
# A part must itself stay below the split threshold so a child run
# never needs splitting again; the prompt targets roughly half of it.
MAX_PART_CHARS = 12_000
MIN_PART_CHARS = 50

_SYSTEM_PROMPT = """\
You split an oversized software requirement into a sequence of smaller,
self-contained sub-requirements for an automated development pipeline.

Rules:
- Produce between 2 and 6 parts, in execution order. Later parts may
  build on earlier parts' results; say so in the shared context when
  they do.
- Be lossless: every requirement, constraint and detail of the
  original must survive, in exactly one part (or in the shared
  context when it applies to all parts).
- Put facts every part needs (overall goal, architecture, shared
  conventions, definitions) into "context" instead of repeating them.
- Each part's "requirement" is a standalone instruction for that part
  alone and must be at most 8000 characters.
- Give each part a short, specific "title" (at most 80 characters).

Respond with ONLY a JSON object of exactly this shape, no prose, no
code fence:
{"context": "<shared context, may be empty>", "parts": [{"title": "...", "requirement": "..."}]}
"""


@dataclass(frozen=True)
class SplitPart:
    title: str
    requirement: str


@dataclass(frozen=True)
class SplitPlan:
    context: str
    parts: list[SplitPart]

    def full_requirement(self, part: SplitPart) -> str:
        """The requirement text a child run receives for `part`."""
        if self.context:
            return f"{self.context}\n\n---\n\n{part.requirement}"
        return part.requirement


class RequirementDecomposer:
    """Splits a requirement via one validated model call."""

    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    def split(self, *, title: str, requirement: str) -> SplitPlan:
        request = ModelRequest(
            messages=[
                ModelMessage(role="system", content=_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=f"Task title: {title}\n\nRequirement:\n{requirement}",
                ),
            ],
            parameters={"temperature": 0.2},
            # Unknown agent id -> the shared configured model; the
            # complex tier pins it too. Decomposition is the run's
            # most consequential call, so it never goes to an economy
            # per-agent override.
            metadata={"agentId": "decomposer", "modelTier": "complex"},
        )
        response = self._gateway.complete(request)
        return _parse_plan(response.content)


def _parse_plan(content: str) -> SplitPlan:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Decomposition response is not JSON") from None
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            raise ValueError("Decomposition response is not valid JSON") from None
    if not isinstance(data, dict):
        raise ValueError("Decomposition response is not a JSON object")
    context = data.get("context") or ""
    if not isinstance(context, str):
        raise ValueError("Decomposition 'context' must be a string")
    raw_parts = data.get("parts")
    if not isinstance(raw_parts, list) or not 2 <= len(raw_parts) <= MAX_SPLIT_PARTS:
        raise ValueError(
            f"Decomposition must produce 2..{MAX_SPLIT_PARTS} parts",
        )
    parts: list[SplitPart] = []
    for index, raw in enumerate(raw_parts, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Decomposition part {index} is not an object")
        title = raw.get("title")
        requirement = raw.get("requirement")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Decomposition part {index} has no title")
        if not isinstance(requirement, str) or len(requirement.strip()) < MIN_PART_CHARS:
            raise ValueError(
                f"Decomposition part {index} is too short to be a requirement",
            )
        if len(requirement) > MAX_PART_CHARS:
            raise ValueError(
                f"Decomposition part {index} exceeds {MAX_PART_CHARS} characters",
            )
        parts.append(SplitPart(
            title=title.strip()[:120],
            requirement=requirement.strip(),
        ))
    return SplitPlan(context=context.strip(), parts=parts)
