"""The improver: proposes harness edits from behavioral evidence (H3).

`GatewayImprover` is the real `ImproverPort`. It renders one of
the mission templates in `prompts/`, sends it through a
`ModelGateway`, and parses the reply's edit blocks with the same
parser the code agents use (design D3 — wrapped, not forked). A
reply that does not parse gets one repair call with the parser's
message fed back, mirroring the agents' repair pattern; a reply
that still does not parse raises `ValueError`, and the Stage
treats that like any other failed attempt (one retry with the
message appended to the mission, then fall back to the current
harness). The path allow-list is deliberately NOT given to the
parser: new skill files cannot be enumerated in advance, so the
surface validator (the Stage's check) owns the allow-list and its
prose is what the retry feeds back.

The Stage shape follows the Harness² method (Google Research,
Apache-2.0); the implementation and all prompt text are ASF's own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from asf.contracts.models import ModelMessage, ModelRequest
from asf.models.ports import ModelGateway
from asf.tools.changeset import ChangeSet
from asf.tools.edit_blocks import parse_edit_blocks
from harness.harness2.context import EvidenceBundle
from harness.harness2.prompts import MissionInputs, mission_prompt
from harness.harness2.surface import Tree

__all__ = [
    "MISSION_TEMPLATES",
    "GatewayImprover",
    "ImproverPort",
    "ImproverReply",
    "StageContext",
    "apply_changeset",
]

MISSION_TEMPLATES = {
    "invariant": "propose_inv",
    "domain": "propose_dom",
    "aggregate": "aggregate",
    "compose_round": "compose_round",
}
_BLOCK_HEADERS = ("FILE:", "CREATE:", "DELETE:")
REPAIR_EXCERPT_CHARS = 8_000


@dataclass(frozen=True)
class ImproverReply:
    """One improver session's output: the candidate tree + its notes."""

    tree: Tree
    notes: str = ""


@dataclass(frozen=True)
class StageContext:
    """A stage's extra inputs beyond mission, evidence and harness.

    `decisions` carries the notes of earlier candidate stages
    (composition missions); `feedback` carries the rejection
    message of this stage's previous attempt, on a retry.
    """

    decisions: Mapping[str, str] | None = None
    feedback: str = ""


class ImproverPort(Protocol):
    """Anything that can propose a harness edit from evidence."""

    def improve(
        self,
        mission: str,
        evidence: EvidenceBundle,
        harness: Tree,
        context: StageContext | None = None,
    ) -> ImproverReply:
        """Return a candidate tree (may equal `harness` for a no-op)."""
        ...


def apply_changeset(tree: Tree, changeset: ChangeSet) -> Tree:
    """A copy of `tree` with a parsed edit-block changeset applied."""
    result = dict(tree)
    for change in changeset.changes:
        if change.operation == "delete":
            result.pop(change.path, None)
        else:
            result[change.path] = change.content or ""
    return result


def _split_reply(reply: str) -> tuple[str, str]:
    lines = reply.replace("\r\n", "\n").split("\n")
    for index, line in enumerate(lines):
        if line.startswith(_BLOCK_HEADERS):
            return "\n".join(lines[:index]).strip(), "\n".join(lines[index:])
    return reply.strip(), ""


def _parse_reply(reply: str, harness: Tree) -> ImproverReply:
    notes, blocks = _split_reply(reply)
    if not blocks.strip():
        return ImproverReply(tree=dict(harness), notes=notes)
    changeset = parse_edit_blocks(blocks, existing_files=harness)
    return ImproverReply(tree=apply_changeset(harness, changeset), notes=notes)


class GatewayImprover:
    """ImproverPort over a ModelGateway: one call, one repair call."""

    def __init__(self, gateway: ModelGateway, *, agent: str, model: str | None = None) -> None:
        self._gateway = gateway
        self._agent = agent
        self._model = model

    def improve(
        self,
        mission: str,
        evidence: EvidenceBundle,
        harness: Tree,
        context: StageContext | None = None,
    ) -> ImproverReply:
        template = MISSION_TEMPLATES.get(mission)
        if template is None:
            raise ValueError(f"unknown improver mission '{mission}'")
        stage = context if context is not None else StageContext()
        prompt = mission_prompt(
            template,
            MissionInputs(
                agent=self._agent,
                evidence=evidence.render(),
                harness=harness,
                decisions=stage.decisions,
            ),
        )
        if stage.feedback:
            prompt += f"\n\n## Feedback on your previous attempt\n\n{stage.feedback}"
        messages = [ModelMessage(role="system", content=prompt)]
        reply = self._call(messages, mission)
        try:
            return _parse_reply(reply, harness)
        except ValueError as error:
            repaired = self._repair(messages, reply, error, mission)
            return _parse_reply(repaired, harness)

    def _call(self, messages: list[ModelMessage], mission: str) -> str:
        request = ModelRequest(
            messages=messages,
            model=self._model,
            metadata={"agentId": "harness2-improver", "mission": mission},
        )
        return self._gateway.complete(request).content

    def _repair(
        self, messages: list[ModelMessage], reply: str, error: ValueError, mission: str
    ) -> str:
        repair_messages = [
            *messages,
            ModelMessage(role="assistant", content=reply[:REPAIR_EXCERPT_CHARS]),
            ModelMessage(
                role="user",
                content=(
                    f"Your previous reply could not be applied: {error}\n"
                    "Reply again: brief notes first, then the edit blocks "
                    "in exactly the format described."
                ),
            ),
        ]
        return self._call(repair_messages, mission)
