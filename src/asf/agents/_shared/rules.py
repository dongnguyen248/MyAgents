"""Standing project rules shared by the agents that design and write code.

The assembly resolves a project's standards — shared language rule packs
plus the project's own rule files — into the run context as
``context["project"]["reviewRules"]``. Each producing agent's builder
appends that text to its system prompt, so the whole team develops
against the same standards the Review Agent later enforces. The rules
act as the team's persistent memory: they are re-read from the rule
files on every run, so editing a rule file changes every agent's
behavior on the next run.
"""

from __future__ import annotations

import json
from typing import Any


def project_rules(project: Any) -> str:
    """The configured rules text from a project context value, or ''.

    The context value may be the project mapping itself or its JSON text
    form; anything else (or a blank/invalid rules value) yields ''.
    """
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (ValueError, RecursionError):
            return ""
    if not isinstance(project, dict):
        return ""
    rules = project.get("reviewRules")
    return rules.strip() if isinstance(rules, str) else ""


def rules_section(project: Any, intro: str) -> str:
    """A system-prompt block carrying the project rules, or ''."""
    rules = project_rules(project)
    if not rules:
        return ""
    return f"\n\n{intro}\n{rules}"
