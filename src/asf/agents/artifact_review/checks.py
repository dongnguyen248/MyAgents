"""Deterministic mechanical checks, run before any model call.

Failures become findings with ``source="mechanical"``; a mechanical
BLOCKER short-circuits the round (the model is not called). The checks
mirror the shipped templates in ``templates/`` — the section lists are
pinned against those files by a unit test.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from asf.agents._shared.code_agents import task_items_from_content
from asf.agents.artifact_review.prompts import Category, Finding, Severity
from asf.contracts.models import Artifact

__all__ = [
    "DEFAULT_MAX_TASKS",
    "MAX_ARTIFACT_CHARS",
    "PLAN_SECTIONS",
    "SPEC_SECTIONS",
    "markdown_text",
    "requirement_ids",
    "run_mechanical_checks",
]

MAX_ARTIFACT_CHARS = 200_000
MAX_MECHANICAL_FINDINGS = 20
DEFAULT_MAX_TASKS = 50
# Cycle detection recurses once per task in the longest dependency
# chain; beyond this many tasks the cap finding already fired and the
# graph check is skipped rather than risking the recursion limit.
MAX_CYCLE_TASKS = 200

REQ_ID_PATTERN = re.compile(r"\bREQ-\d+\b")
DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")

SPEC_SECTIONS = (
    "Background / Goal",
    "Scope (in / out)",
    "Functional requirements",
    "Non-functional requirements",
    "Acceptance criteria",
    "Open questions",
    "Revision history",
)
PLAN_SECTIONS = (
    "Linked SPEC",
    "Scope and out of scope",
    "Approach / architecture",
    "Impacted components",
    "Milestones",
    "Testing strategy",
    "Risks & mitigations",
    "Open questions",
    "Revision history",
)


@dataclass(frozen=True)
class _Issue:
    severity: Severity
    category: Category
    location: str
    problem: str
    required_change: str


class _Collector:
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def add(self, issue: _Issue) -> None:
        if len(self.findings) >= MAX_MECHANICAL_FINDINGS:
            return
        self.findings.append(
            Finding(
                id=f"M-{len(self.findings) + 1:03d}",
                severity=issue.severity,
                category=issue.category,
                location=issue.location,
                problem=issue.problem,
                required_change=issue.required_change,
                source="mechanical",
            )
        )


def markdown_text(artifact: Artifact) -> str:
    """The markdown body of a SPEC/PLAN-style artifact ("" if absent)."""
    if isinstance(artifact.content, dict):
        text = artifact.content.get("text")
        return text if isinstance(text, str) else ""
    if isinstance(artifact.content, str):
        return artifact.content
    return ""


def requirement_ids(text: str) -> list[str]:
    """Requirement ids (REQ-<n>) in order of first appearance."""
    return list(dict.fromkeys(REQ_ID_PATTERN.findall(text)))


def split_sections(text: str) -> dict[str, str]:
    """Map each '## Heading' to its body text."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(body).strip() for name, body in sections.items()}


def run_mechanical_checks(
    stage: str,
    artifact: Artifact,
    upstream: Mapping[str, Artifact],
    *,
    max_tasks: int = DEFAULT_MAX_TASKS,
) -> list[Finding]:
    """All deterministic checks for one stage's artifact."""
    collector = _Collector()
    if stage == "task":
        _check_task(collector, artifact, upstream, max_tasks)
    else:
        text = markdown_text(artifact)
        _check_common(collector, text)
        if stage == "spec":
            _check_spec(collector, text)
        elif stage == "plan":
            _check_plan(collector, text, upstream)
    return collector.findings


def _check_common(collector: _Collector, text: str) -> None:
    if not text.strip():
        collector.add(
            _Issue(
                "BLOCKER",
                "COMPLETENESS",
                "artifact",
                "The artifact is empty.",
                "Produce the full artifact content.",
            )
        )
        return
    if len(text) > MAX_ARTIFACT_CHARS:
        collector.add(
            _Issue(
                "BLOCKER",
                "COMPLETENESS",
                "artifact",
                f"The artifact is {len(text)} characters, over the {MAX_ARTIFACT_CHARS} limit.",
                "Shorten the artifact to fit the size limit.",
            )
        )
    _check_truncation(collector, text)


def _check_truncation(collector: _Collector, text: str) -> None:
    if text.count("```") % 2 == 1:
        collector.add(
            _Issue(
                "BLOCKER",
                "CORRECTNESS",
                "artifact",
                "The artifact ends inside an unclosed code fence (truncated).",
                "Complete the truncated section and close the code fence.",
            )
        )
    last_line = next((line for line in reversed(text.splitlines()) if line.strip()), "")
    if last_line.lstrip().startswith("|") and not last_line.rstrip().endswith("|"):
        collector.add(
            _Issue(
                "BLOCKER",
                "CORRECTNESS",
                "artifact",
                "The artifact ends mid-table (the last row is incomplete).",
                "Complete the truncated table row.",
            )
        )


def _check_sections(collector: _Collector, text: str, required: tuple[str, ...]) -> dict[str, str]:
    sections = split_sections(text)
    for name in required:
        if name not in sections:
            _report_section(
                collector,
                name,
                f"Required section '## {name}' is missing.",
                f"Add the '## {name}' section with real content.",
            )
        elif not sections[name]:
            _report_section(
                collector,
                name,
                f"Section '## {name}' is present but empty.",
                f"Write the content of the '## {name}' section.",
            )
    return sections


def _report_section(collector: _Collector, name: str, problem: str, change: str) -> None:
    collector.add(_Issue("BLOCKER", "COMPLETENESS", f"## {name}", problem, change))


def _check_spec(collector: _Collector, text: str) -> None:
    sections = _check_sections(collector, text, SPEC_SECTIONS)
    functional = sections.get("Functional requirements", "")
    ids = requirement_ids(functional)
    if not ids:
        collector.add(
            _Issue(
                "BLOCKER",
                "COMPLETENESS",
                "## Functional requirements",
                "No numbered requirement id (REQ-<n>) is defined.",
                "Give every functional requirement a stable REQ-<n> id.",
            )
        )
        return
    _check_duplicate_requirements(collector, functional)
    _check_acceptance_coverage(collector, ids, sections.get("Acceptance criteria", ""))


def _check_duplicate_requirements(collector: _Collector, functional: str) -> None:
    defined = REQ_ID_PATTERN.findall(functional)
    for duplicate in sorted({item for item in defined if defined.count(item) > 1}):
        collector.add(
            _Issue(
                "BLOCKER",
                "CONSISTENCY",
                duplicate,
                f"Requirement id {duplicate} is defined more than once.",
                f"Keep exactly one definition of {duplicate}.",
            )
        )


def _check_acceptance_coverage(collector: _Collector, ids: list[str], criteria: str) -> None:
    for req_id in ids:
        if req_id not in criteria:
            collector.add(
                _Issue(
                    "BLOCKER",
                    "TRACEABILITY",
                    req_id,
                    f"Requirement {req_id} has no acceptance criterion referencing it.",
                    f"Add an acceptance criterion that references {req_id}.",
                )
            )


def _check_plan(collector: _Collector, text: str, upstream: Mapping[str, Artifact]) -> None:
    _check_sections(collector, text, PLAN_SECTIONS)
    spec = upstream.get("SPEC")
    if spec is None:
        return
    spec_ids = requirement_ids(markdown_text(spec))
    referenced = set(requirement_ids(text))
    _check_plan_coverage(collector, spec_ids, referenced)
    _check_plan_unknown(collector, spec_ids, referenced)


def _check_plan_coverage(collector: _Collector, spec_ids: list[str], referenced: set[str]) -> None:
    for req_id in spec_ids:
        if req_id not in referenced:
            collector.add(
                _Issue(
                    "BLOCKER",
                    "TRACEABILITY",
                    req_id,
                    f"SPEC requirement {req_id} is never referenced in the PLAN.",
                    f"Reference {req_id} in the approach or a milestone of the PLAN.",
                )
            )


def _check_plan_unknown(collector: _Collector, spec_ids: list[str], referenced: set[str]) -> None:
    for req_id in sorted(referenced - set(spec_ids)):
        collector.add(
            _Issue(
                "BLOCKER",
                "CONSISTENCY",
                req_id,
                f"The PLAN references {req_id}, which does not exist in the SPEC.",
                f"Remove the reference to {req_id} or add it to the SPEC.",
            )
        )


def _parse_items(collector: _Collector, artifact: Artifact) -> list[dict[str, Any]] | None:
    try:
        items = task_items_from_content(artifact.content)
    except ValueError:
        collector.add(
            _Issue(
                "BLOCKER",
                "CORRECTNESS",
                "artifact",
                "The TASK content is not a valid task breakdown.",
                "Return the breakdown as a JSON object with a 'tasks' list.",
            )
        )
        return None
    if not items:
        collector.add(
            _Issue(
                "BLOCKER",
                "COMPLETENESS",
                "artifact",
                "The task breakdown contains no tasks.",
                "Break the plan down into at least one task.",
            )
        )
        return None
    return items


def _check_task(
    collector: _Collector, artifact: Artifact, upstream: Mapping[str, Artifact], max_tasks: int
) -> None:
    items = _parse_items(collector, artifact)
    if items is None:
        return
    if len(items) > max_tasks:
        collector.add(
            _Issue(
                "BLOCKER",
                "SCOPE",
                "artifact",
                f"The breakdown has {len(items)} tasks, over the cap of {max_tasks}.",
                f"Merge related work so the breakdown has at most {max_tasks} tasks.",
            )
        )
    ids = _check_task_items(collector, items)
    _check_task_graph(collector, items, ids)
    _check_task_coverage(collector, items, upstream)
    _check_task_tests(collector, items)
    _check_task_paths(collector, items)


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _check_one_item(collector: _Collector, item: dict[str, Any], index: int) -> str | None:
    task_id = item.get("id")
    location = task_id if isinstance(task_id, str) and task_id.strip() else f"tasks[{index}]"
    for field_name in ("id", "title", "description"):
        if _blank(item.get(field_name)):
            collector.add(
                _Issue(
                    "BLOCKER",
                    "COMPLETENESS",
                    location,
                    f"Task {location} has no usable '{field_name}'.",
                    f"Give task {location} a non-empty '{field_name}'.",
                )
            )
    _check_item_criteria(collector, item, location)
    return task_id if isinstance(task_id, str) and task_id.strip() else None


def _check_item_criteria(collector: _Collector, item: dict[str, Any], location: str) -> None:
    criteria = item.get("acceptanceCriteria")
    if not isinstance(criteria, list) or not criteria or any(_blank(c) for c in criteria):
        collector.add(
            _Issue(
                "BLOCKER",
                "COMPLETENESS",
                location,
                f"Task {location} has no usable acceptance criteria.",
                f"Give task {location} at least one concrete acceptance criterion.",
            )
        )


def _check_task_items(collector: _Collector, items: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for index, item in enumerate(items):
        task_id = _check_one_item(collector, item, index)
        if task_id is not None:
            ids.append(task_id)
    for duplicate in sorted({item for item in ids if ids.count(item) > 1}):
        collector.add(
            _Issue(
                "BLOCKER",
                "CONSISTENCY",
                duplicate,
                f"Task id {duplicate} is used more than once.",
                f"Give every task a unique id; {duplicate} must appear once.",
            )
        )
    return ids


def _task_deps(item: dict[str, Any]) -> list[str]:
    deps = item.get("dependsOn")
    if not isinstance(deps, list):
        return []
    return [dep for dep in deps if isinstance(dep, str)]


def _check_task_graph(collector: _Collector, items: list[dict[str, Any]], ids: list[str]) -> None:
    known = set(ids)
    deps: dict[str, list[str]] = {}
    for item in items:
        task_id = item.get("id")
        if not isinstance(task_id, str) or task_id not in known:
            continue
        task_deps = _task_deps(item)
        deps[task_id] = [dep for dep in task_deps if dep in known]
        _check_dep_targets(collector, task_id, task_deps, known)
    if len(ids) <= MAX_CYCLE_TASKS:
        cycle = _find_cycle(ids, deps)
        if cycle is not None:
            collector.add(
                _Issue(
                    "BLOCKER",
                    "CONSISTENCY",
                    cycle[0],
                    f"Task dependencies contain a cycle: {' -> '.join(cycle)}.",
                    "Break the dependency cycle so the tasks form a DAG.",
                )
            )


def _check_dep_targets(
    collector: _Collector, task_id: str, task_deps: list[str], known: set[str]
) -> None:
    for dep in task_deps:
        if dep == task_id:
            collector.add(
                _Issue(
                    "BLOCKER",
                    "CONSISTENCY",
                    task_id,
                    f"Task {task_id} depends on itself.",
                    f"Remove the self-dependency from task {task_id}.",
                )
            )
        elif dep not in known:
            collector.add(
                _Issue(
                    "BLOCKER",
                    "CONSISTENCY",
                    task_id,
                    f"Task {task_id} depends on unknown task {dep}.",
                    f"Point the dependency of {task_id} at an existing task or remove it.",
                )
            )


def _find_cycle(ids: list[str], deps: dict[str, list[str]]) -> list[str] | None:
    color = dict.fromkeys(ids, 0)
    for start in ids:
        if color[start] == 0:
            cycle = _visit(start, deps, color, [start])
            if cycle is not None:
                return cycle
    return None


def _visit(
    node: str, deps: dict[str, list[str]], color: dict[str, int], path: list[str]
) -> list[str] | None:
    color[node] = 1
    for nxt in deps.get(node, []):
        if color.get(nxt) == 1:
            return path[path.index(nxt) :] + [nxt]
        if color.get(nxt) == 0:
            path.append(nxt)
            cycle = _visit(nxt, deps, color, path)
            if cycle is not None:
                return cycle
            path.pop()
    color[node] = 2
    return None


def _task_haystack(item: dict[str, Any]) -> str:
    parts = [item.get("title"), item.get("description"), item.get("verificationHint")]
    criteria = item.get("acceptanceCriteria")
    if isinstance(criteria, list):
        parts.extend(c for c in criteria if isinstance(c, str))
    return " ".join(part for part in parts if isinstance(part, str))


def _check_task_coverage(
    collector: _Collector, items: list[dict[str, Any]], upstream: Mapping[str, Artifact]
) -> None:
    spec = upstream.get("SPEC")
    if spec is None:
        return
    haystack = "\n".join(_task_haystack(item) for item in items)
    for req_id in requirement_ids(markdown_text(spec)):
        if req_id not in haystack:
            collector.add(
                _Issue(
                    "BLOCKER",
                    "TRACEABILITY",
                    req_id,
                    f"SPEC requirement {req_id} is covered by no task.",
                    f"Add or extend a task so it explicitly covers {req_id}.",
                )
            )


def _check_task_tests(collector: _Collector, items: list[dict[str, Any]]) -> None:
    for item in items:
        task_id = item.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            continue
        if "test" not in _task_haystack(item).lower():
            collector.add(
                _Issue(
                    "MINOR",
                    "TESTABILITY",
                    task_id,
                    f"Task {task_id} never mentions how it will be tested.",
                    f"State the test or check that proves task {task_id} is done.",
                )
            )


def _check_task_paths(collector: _Collector, items: list[dict[str, Any]]) -> None:
    for item in items:
        task_id = item.get("id")
        location = task_id if isinstance(task_id, str) and task_id.strip() else "tasks"
        files = item.get("expectedFiles")
        if not isinstance(files, list):
            continue
        for path in files:
            if isinstance(path, str) and _unsafe_path(path):
                collector.add(
                    _Issue(
                        "BLOCKER",
                        "RISK",
                        location,
                        f"Expected file '{path}' is not a safe relative project path.",
                        f"Change '{path}' to a relative path inside the project.",
                    )
                )


def _unsafe_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return path.startswith("/") or bool(DRIVE_PATTERN.match(path)) or ".." in parts
