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
    "spring boot": "java",
    "spring-boot": "java",
    "springframework": "java",
    "dotnet": "csharp",
    ".net": "csharp",
    "c#": "csharp",
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


def _detect_text_signals(text_signal: str, files: Sequence[str]) -> set[str]:
    signals: set[str] = set()
    for f in files:
        ext = "." + f.rsplit(".", 1)[-1].lower() if "." in f else ""
        if ext in _STACK_EXTENSIONS:
            signals.add(_STACK_EXTENSIONS[ext])
    lowered = text_signal.lower()
    for ext, stack in _STACK_EXTENSIONS.items():
        if re.search(re.escape(ext) + r"(?!\w)", lowered):
            signals.add(stack)
    for tool, stack in _STACK_TOOLS.items():
        prefix = "" if tool.startswith(".") else r"(?<!\w)"
        pattern = prefix + re.escape(tool) + r"(?!\w)"
        if re.search(pattern, lowered):
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
    signals = _detect_text_signals(text_signal, files)
    matched = declared & signals
    if matched:
        logger.info("Stack detected from signals: %s", sorted(matched))
        return frozenset(matched)
    logger.warning("Stack unknown for task; omitting language rule packs")
    return frozenset()


def _starts_new_rule_doc(line: str, current: list[str], seen_title: bool) -> bool:
    if not current or not "".join(current).strip():
        return False
    if line.strip().startswith("<!-- stack:"):
        return True
    if not line.startswith("# "):
        return False
    has_stack = "".join(current).strip().startswith("<!-- stack:")
    return seen_title or not has_stack


def _split_rule_documents(rules_text: str) -> list[str]:
    docs: list[str] = []
    current: list[str] = []
    seen_title = False
    for line in rules_text.splitlines(keepends=True):
        is_title = line.startswith("# ")
        if _starts_new_rule_doc(line, current, seen_title):
            docs.append("".join(current))
            current = [line]
            seen_title = is_title
        else:
            current.append(line)
            seen_title = seen_title or is_title
    if current and "".join(current).strip():
        docs.append("".join(current))
    return docs


def _document_stack(doc: str) -> str | None:
    match = re.search(r"<!--\s*stack:\s*([a-zA-Z0-9_\-]+)\s*-->", doc)
    if match:
        return match.group(1).strip().lower()
    first_line = doc.splitlines()[0].strip().lower() if doc.splitlines() else ""
    if not first_line.startswith("# "):
        return None
    for token, stack in _CANONICAL_STACKS.items():
        if re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", first_line):
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
    (
        "test-style",
        ["testing", "test style", "tests", "verification", "mock", "checklist", "automated"],
    ),
    (
        "api",
        ["api", "endpoint", "resource", "contract", "request", "response", "dto", "http status"],
    ),
    (
        "security",
        [
            "security",
            "auth",
            "secret",
            "permission",
            "audit",
            "validation",
            "injection",
            "disclosure",
        ],
    ),
    ("naming", ["naming", "convention", "constant", "enum"]),
    (
        "structure",
        ["structure", "architecture", "component", "class", "state management", "react and ui"],
    ),
]


def classify_section_scope(heading: str, body: str) -> str:
    """Classifies section scope by explicit tag comment or heading keywords."""
    match = re.search(r"<!--\s*tags:\s*([^>]+)-->", body)
    if match:
        tag_str = match.group(1).lower()
        for scope, _ in _SCOPE_KEYWORDS:
            if scope in tag_str:
                return scope
    target = heading.lower() if heading.strip() else body[:150].lower()
    for scope, keywords in _SCOPE_KEYWORDS:
        if any(kw in target for kw in keywords):
            return scope
    return "coding-detail"


_DESIGN_SCOPES: dict[str, set[str]] = {
    "spec": {"api", "security", "structure", "naming"},
    "plan": {"api", "security", "structure", "naming"},
    "task": {"api", "security", "structure", "naming"},
}


def _is_section_allowed(scope: str, agent: str) -> bool:
    allowed = _DESIGN_SCOPES.get(agent, _DESIGN_SCOPES["task"])
    return scope in allowed


_PRIORITY_ORDER: dict[str, int] = {
    "api": 1,
    "security": 2,
    "structure": 3,
    "naming": 4,
}


def apply_character_budget(
    sections: list[tuple[str, str]],
    budget: int = MAX_DESIGN_RULES_BUDGET,
    agent: str = "",
) -> list[tuple[str, str]]:
    """Enforces character budget by dropping entire sections in deterministic priority order.

    The total length check includes the '\\n\\n' delimiters that join sections.
    """
    total_len = len("\n\n".join(c for _, c in sections))
    if total_len <= budget:
        return sections
    annotated = [(idx, classify_section_scope(h, c), h, c) for idx, (h, c) in enumerate(sections)]
    annotated.sort(key=lambda item: (_PRIORITY_ORDER.get(item[1], 99), item[0]))
    selected: list[tuple[int, str, str]] = []
    curr_len = 0
    dropped: list[str] = []
    for idx, _, h, c in annotated:
        extra = len(c) if not selected else (2 + len(c))
        if curr_len + extra <= budget:
            selected.append((idx, h, c))
            curr_len += extra
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


def _retain_matching_docs(docs: list[str], stack: frozenset[str]) -> list[str]:
    retained: list[str] = []
    for doc in docs:
        doc_stack = _document_stack(doc)
        if doc_stack is not None and doc_stack not in {"all"} and doc_stack not in stack:
            continue
        retained.append(doc)
    return retained


def _partition_sections_by_scope(
    sections: list[tuple[str, str]],
    agent: str,
) -> tuple[list[tuple[str, str]], list[str]]:
    allowed: list[tuple[str, str]] = []
    disallowed: list[str] = []
    for h, c in sections:
        scope = classify_section_scope(h, c)
        if _is_section_allowed(scope, agent):
            allowed.append((h, c))
        else:
            disallowed.append(h or "preamble")
    return allowed, disallowed


def _filter_unheaded_rules(joined: str, agent: str, budget: int) -> str:
    stripped = joined.strip()
    if len(stripped) <= budget:
        logger.info(
            "Project rules without headings loaded verbatim for '%s' (%d chars)",
            agent,
            len(stripped),
        )
        return stripped
    logger.warning(
        "Project rules without headings omitted from '%s': %d chars exceed budget (%d chars)",
        agent,
        len(stripped),
        budget,
    )
    return ""


def _log_stack_pack_status(retained_docs: list[str], stack: frozenset[str]) -> None:
    loaded_stacks = {_document_stack(d) for d in retained_docs if _document_stack(d)}
    for s in sorted(stack):
        if s in loaded_stacks:
            logger.info("Rule pack loaded: %s", s)
        else:
            logger.info("Task stack ['%s'] identified but no rule pack configured", s)


def filter_rules_for_task(
    rules_text: str,
    agent: str,
    stack: frozenset[str],
    budget: int = MAX_DESIGN_RULES_BUDGET,
) -> str:
    """Filters rule documents by task stack and sections by agent scope and budget."""
    if not rules_text.strip():
        return ""
    retained_docs = _retain_matching_docs(_split_rule_documents(rules_text), stack)
    _log_stack_pack_status(retained_docs, stack)
    if not retained_docs:
        return ""
    joined = "\n\n".join(retained_docs)
    sections = parse_rule_sections(joined)
    if not any(h.startswith("## ") for h, _ in sections):
        return _filter_unheaded_rules(joined, agent, budget)
    allowed, disallowed = _partition_sections_by_scope(sections, agent)
    if disallowed:
        logger.debug("Project rule section(s) %s omitted from '%s': non-design", disallowed, agent)
    if not allowed:
        logger.warning("Project rules omitted from '%s': no sections match design scopes", agent)
        return ""
    budgeted = apply_character_budget(allowed, budget, agent)
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
