from __future__ import annotations

from typing import Any

from asf.approval.models import ApprovalRequest
from asf.contracts.models import Artifact
from asf.integrations.teams.approval import TeamsAction


def approval_card(run_id: str, request: ApprovalRequest, artifact: Artifact) -> dict[str, Any]:
    """Action.Submit is the Power Automate wait-for-response contract, not bot Execute."""
    text = artifact.content.get("text") if isinstance(artifact.content, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Teams approval requires a nonempty rendered text artifact")
    common = TeamsAction(
        run_id=run_id,
        approval_id=request.id,
        decision="APPROVED",
    ).model_dump(by_alias=True, exclude={"decision", "comment"})
    return {
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": "AI Software Agents: approval required",
                "weight": "Bolder",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": f"{artifact.type} v{artifact.version} | {artifact.id}",
                "wrap": True,
            },
            {"type": "TextBlock", "text": text, "wrap": True},
            {
                "type": "Input.Text",
                "id": "comment",
                "label": "Comment (optional for Approve)",
                "isMultiline": True,
                "maxLength": 4000,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Approve",
                "associatedInputs": "auto",
                "data": {**common, "decision": "APPROVED"},
            },
            {
                "type": "Action.ShowCard",
                "title": "Reject",
                "card": {
                    "type": "AdaptiveCard",
                    "version": "1.3",
                    "body": [
                        {
                            "type": "Input.Text",
                            "id": "rejectComment",
                            "label": "Reason for rejection",
                            "isMultiline": True,
                            "isRequired": True,
                            "errorMessage": "Please describe what the agent must change",
                            "maxLength": 4000,
                        }
                    ],
                    "actions": [
                        {
                            "type": "Action.Submit",
                            "title": "Send rejection",
                            "associatedInputs": "auto",
                            "data": {**common, "decision": "REJECTED"},
                        }
                    ],
                },
            },
        ],
    }
