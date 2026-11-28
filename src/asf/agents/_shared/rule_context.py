"""Rule text selected for an agent in a run context."""

import json
from typing import Any


def project_rules(project: Any, agent: str = "") -> str:
    """The configured rules text from a project context value, or ''."""
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (ValueError, RecursionError):
            return ""
    if not isinstance(project, dict):
        return ""
    rules = project.get("reviewRules")
    base = rules.strip() if isinstance(rules, str) else ""
    extra_rules = project.get("agentRules")
    extra = extra_rules.get(agent) if isinstance(extra_rules, dict) else None
    if isinstance(extra, str) and extra.strip():
        return "\n\n".join(text for text in (base, extra.strip()) if text)
    return base
