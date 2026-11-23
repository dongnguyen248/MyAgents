"""Standing project rules shared by the agents that design and write code.

The assembly resolves a project's standards — shared language rule packs
plus the project's own rule files — into the run context as
``context["project"]["reviewRules"]``. Each producing agent's builder
appends that text to its system prompt. Design agents (spec, plan, task)
filter sections to API/security/structure/naming and apply a 2,500 char
budget, while code/review agents receive the full rules.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DESIGN_AGENTS: frozenset[str] = frozenset({"spec", "plan", "task"})
MAX_DESIGN_RULES_BUDGET: int = 2500


@dataclass(frozen=True)
class RulesFilterOptions:
    agent: str = ""
    stack: frozenset[str] | None = None
    budget: int = MAX_DESIGN_RULES_BUDGET


_STACK_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".java": "java",
    ".cs": "csharp",
}

_STACK_TOOLS: dict[str, str] = {
    "pytest": "python",
    "pip": "python",
    "poetry": "python",
    "fastapi": "python",
    "npm": "typescript",
    "yarn": "typescript",
    "eslint": "typescript",
    "prettier": "typescript",
    "react": "typescript",
    "mvn": "java",
    "gradle": "java",
    "spring": "java",
    "dotnet": "csharp",
    "msbuild": "csharp",
}

_CANONICAL_STACKS: dict[str, str] = {
    "python": "python",
    "fastapi": "python",
    "typescript": "typescript",
    "ts": "typescript",
    "javascript": "typescript",
    "js": "typescript",
    "react": "typescript",
    "java": "java",
    "spring": "java",
    "csharp": "csharp",
    "c#": "csharp",
    "dotnet": "csharp",
    ".net": "csharp",
}


def _canonical_stack(token: str) -> str | None:
    return _CANONICAL_STACKS.get(token.strip().lower())


def _collect_raw_tokens(project_tech: Any) -> list[str]:
    if isinstance(project_tech, list):
        return [str(item) for item in project_tech]
    if not isinstance(project_tech, dict):
        return []
    tokens: list[str] = []
    for val in project_tech.values():
        if isinstance(val, list):
            tokens.extend(str(item) for item in val)
        elif isinstance(val, str):
            tokens.append(val)
    return tokens


def _extract_declared_stacks(project_tech: Any) -> set[str]:
    raw_list = _collect_raw_tokens(project_tech)
    stacks = {_canonical_stack(tok) for tok in raw_list}
    return {s for s in stacks if s is not None}


def _detect_signals(text_signal: str, files: Sequence[str]) -> set[str]:
    signals: set[str] = set()
    for f in files:
        ext = "." + f.rsplit(".", 1)[-1].lower() if "." in f else ""
        if ext in _STACK_EXTENSIONS:
            signals.add(_STACK_EXTENSIONS[ext])
    lowered = text_signal.lower()
    for ext, stack in _STACK_EXTENSIONS.items():
        if ext in lowered:
            signals.add(stack)
    for tool, stack in _STACK_TOOLS.items():
        if re.search(r"\b" + re.escape(tool) + r"\b", lowered):
            signals.add(stack)
    return signals


def detect_task_stack(
    language: str | None,
    project_tech: Any,
    text_signal: str = "",
    files: Sequence[str] = (),
) -> frozenset[str]:
    """Resolves task stack following exact priority: metadata, intersection, or none."""
    if language and language.strip():
        canon = _canonical_stack(language)
        if canon:
            logger.info("Stack detected from metadata: %s", canon)
            return frozenset({canon})
    declared = _extract_declared_stacks(project_tech)
    signals = _detect_signals(text_signal, files)
    matched = declared & signals
    if matched:
        logger.info("Stack detected from signals: %s", sorted(matched))
        return frozenset(matched)
    logger.warning("Stack unknown for task; omitting language rule packs")
    return frozenset()


def _split_rule_documents(rules_text: str) -> list[str]:
    docs: list[str] = []
    current: list[str] = []
    for line in rules_text.splitlines(keepends=True):
        is_new_stack = line.strip().startswith("<!-- stack:")
        has_stack = "".join(current).strip().startswith("<!-- stack:")
        is_new_title = line.startswith("# ") and not has_stack
        if (is_new_stack or is_new_title) and current and "".join(current).strip():
            docs.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current and "".join(current).strip():
        docs.append("".join(current))
    return docs


def _document_stack(doc: str) -> str | None:
    match = re.search(r"<!--\s*stack:\s*([a-zA-Z0-9_\-]+)\s*-->", doc)
    if match:
        return match.group(1).strip().lower()
    first_line = doc.splitlines()[0].lower() if doc.splitlines() else ""
    for token, stack in _CANONICAL_STACKS.items():
        if token in first_line:
            return stack
    return None


def parse_rule_sections(text: str) -> list[tuple[str, str]]:
    """Splits markdown rule text into [(heading, section_text)]."""
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            if current_lines:
                sections.append((current_heading, "".join(current_lines).strip()))
                current_lines = []
            current_heading = line.strip()
            current_lines.append(line)
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, "".join(current_lines).strip()))
    return [(h, c) for h, c in sections if c]


_SCOPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("formatting", ["formatting", "prettier", "eslint", "whitespace", "brace", "indent"]),
    ("test-style", ["testing and quality", "test style", "mock", "checklist", "automated"]),
    ("security", ["security", "auth", "secret", "permission", "audit", "validation"]),
    ("api", ["api", "endpoint", "resource", "contract", "request", "response", "dto"]),
    ("naming", ["naming", "convention", "constant", "enum"]),
    ("structure", ["structure", "architecture", "component", "class", "function", "state"]),
]


def classify_section_scope(heading: str, body: str) -> str:
    """Classifies section scope by explicit tag comment or heading keywords."""
    match = re.search(r"<!--\s*tags:\s*([^>]+)-->", body)
    if match:
        tag_str = match.group(1).lower()
        for scope, _ in _SCOPE_KEYWORDS:
            if scope in tag_str:
                return scope
    combined = (heading + " " + body[:150]).lower()
    for scope, keywords in _SCOPE_KEYWORDS:
        if any(kw in combined for kw in keywords):
            return scope
    return "general"


_DESIGN_SCOPES: dict[str, set[str]] = {
    "spec": {"security", "api", "structure", "naming", "general"},
    "plan": {"security", "api", "structure", "naming", "general"},
    "task": {"security", "api", "structure", "naming", "general"},
}


def _is_section_allowed(scope: str, agent: str) -> bool:
    if scope in {"formatting", "test-style"}:
        return False
    allowed = _DESIGN_SCOPES.get(agent, _DESIGN_SCOPES["task"])
    return scope in allowed


_PRIORITY_ORDER: dict[str, int] = {
    "security": 1,
    "api": 2,
    "structure": 3,
    "naming": 4,
    "general": 5,
}


def apply_character_budget(
    sections: list[tuple[str, str]],
    budget: int = MAX_DESIGN_RULES_BUDGET,
    agent: str = "",
) -> list[tuple[str, str]]:
    """Enforces character budget by dropping entire sections in deterministic priority order."""
    total_len = sum(len(c) for _, c in sections)
    if total_len <= budget:
        return sections
    annotated = [(idx, classify_section_scope(h, c), h, c) for idx, (h, c) in enumerate(sections)]
    annotated.sort(key=lambda item: (_PRIORITY_ORDER.get(item[1], 99), item[0]))
    selected: list[tuple[int, str, str]] = []
    curr_len = 0
    dropped: list[str] = []
    for idx, _, h, c in annotated:
        if curr_len + len(c) <= budget:
            selected.append((idx, h, c))
            curr_len += len(c)
        else:
            dropped.append(h or "preamble")
    if dropped:
        msg = (
            "Project rule section(s) %s omitted from agent '%s':"
            " exceeded character budget (%d chars)"
        )
        logger.warning(msg, dropped, agent, budget)
    selected.sort(key=lambda item: item[0])
    return [(h, c) for _, h, c in selected]


def filter_rules_for_task(
    rules_text: str,
    agent: str,
    stack: frozenset[str],
    budget: int = MAX_DESIGN_RULES_BUDGET,
) -> str:
    """Filters rule documents by task stack and sections by agent scope and budget."""
    docs = _split_rule_documents(rules_text)
    retained_docs: list[str] = []
    for doc in docs:
        doc_stack = _document_stack(doc)
        if doc_stack is not None and doc_stack not in {"all"} and doc_stack not in stack:
            continue
        retained_docs.append(doc)
    if not retained_docs:
        return ""
    joined_text = "\n\n".join(retained_docs)
    sections = parse_rule_sections(joined_text)
    filtered = [
        (h, c) for h, c in sections if _is_section_allowed(classify_section_scope(h, c), agent)
    ]
    budgeted = apply_character_budget(filtered, budget, agent)
    return "\n\n".join(c for _, c in budgeted).strip()


def project_rules(project: Any) -> str:
    """The configured rules text from a project context value, or ''."""
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (ValueError, RecursionError):
            return ""
    if not isinstance(project, dict):
        return ""
    rules = project.get("reviewRules")
    return rules.strip() if isinstance(rules, str) else ""


def rules_section(
    project: Any,
    intro: str,
    opts: RulesFilterOptions | None = None,
) -> str:
    """A system-prompt block carrying the project rules, or ''."""
    rules = project_rules(project)
    if not rules:
        return ""
    if opts is not None and opts.agent in DESIGN_AGENTS:
        stack = opts.stack
        if stack is None:
            proj_dict = project if isinstance(project, dict) else {}
            tech = proj_dict.get("technology") or proj_dict.get("technologies")
            stack = detect_task_stack(None, tech)
        rules = filter_rules_for_task(rules, opts.agent, stack, opts.budget)
        if not rules:
            return ""
    return f"\n\n{intro}\n{rules}"
