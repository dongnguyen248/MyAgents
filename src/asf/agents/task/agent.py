from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from asf.agents._shared.harness import HarnessComponents, components_from_prompts, fingerprint
from asf.agents._shared.model_call import call_model
from asf.agents._shared.model_errors import invalid_response
from asf.agents._shared.paths import CONTROL_CHAR_BOUND
from asf.agents._shared.reply_text import unwrap_code_fence
from asf.agents._shared.request_checks import (
    artifacts_of,
    check_agent_id,
    check_artifact_types,
    check_attempt,
    check_language,
    check_orphan_feedback,
    check_required_artifact,
    check_revision_artifact,
    check_text_size,
)
from asf.agents._shared.routing import tier_metadata
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.agents.plan.milestones import (
    Milestone,
    milestone_ancestors,
    milestone_number,
    parse_milestones,
)
from asf.agents.task.items import TaskContent, TaskItem
from asf.agents.task.prompts import (
    TaskPromptContext,
    TaskPrompts,
    TaskTemplate,
    build_task_messages,
)
from asf.contracts.models import (
    AgentMetadata,
    AgentRequest,
    Artifact,
    ModelMessage,
    ModelRequest,
    ModelResponse,
)

__all__ = [
    "MAX_TASK_CHARS",
    "MAX_TASK_TEXT_CHARS",
    "MAX_TASK_REPLY_CHARS",
    "MAX_TASKS",
    "TaskAgent",
    "TaskContent",
    "TaskItem",
    "TaskSettings",
    "render_task_markdown",
]

MAX_TASK_CHARS: int = 50000
MAX_TASKS: int = 100
MAX_TASK_TEXT_CHARS: int = 200000
MAX_TASK_REPLY_CHARS: int = 500000

_ALLOWED_TYPES = {"SPEC", "PLAN", "TASK"}
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:[/\\]")


def render_task_markdown(
    tasks: list[TaskItem],
    plan_milestones: list[Milestone],
    spec_id: str,
    spec_version: str,
) -> str:
    """Deterministically render markdown from validated tasks."""
    lines = [
        "# TASK: Breakdown",
        "",
        "## Linked SPEC",
        f"ID: {spec_id}",
        f"Version: {spec_version}",
        "",
    ]
    by_milestone = _group_by_milestone(tasks)
    ordered = sorted(plan_milestones, key=lambda m: milestone_number(m.id))
    for milestone in ordered:
        lines.extend(_milestone_lines(milestone, by_milestone.get(milestone.id, [])))
    return "\n".join(lines).strip()


def _group_by_milestone(tasks: list[TaskItem]) -> dict[str, list[TaskItem]]:
    grouped: dict[str, list[TaskItem]] = {}
    for task in tasks:
        grouped.setdefault(task.milestone_ref, []).append(task)
    return grouped


def _milestone_lines(milestone: Milestone, tasks: list[TaskItem]) -> list[str]:
    if not tasks:
        return []
    lines = [f"## Milestone {milestone.id}: {milestone.name}", ""]
    for task in tasks:
        lines.extend(_task_lines(task))
    return lines


def _task_lines(task: TaskItem) -> list[str]:
    lines = [
        f"### {task.id}: {task.title}",
        "",
        f"**Description:** {task.description}",
        "",
        "**Acceptance Criteria:**",
    ]
    lines.extend(f"- {criterion}" for criterion in task.acceptance_criteria)
    lines.append("")
    if task.depends_on:
        lines.append(f"**Depends On:** {', '.join(task.depends_on)}")
        lines.append("")
    if task.expected_files:
        lines.append("**Expected Files:**")
        lines.extend(f"- {path}" for path in task.expected_files)
        lines.append("")
    lines.append(f"**Verification Hint:** {task.verification_hint}")
    lines.append("")
    return lines


@dataclass(frozen=True)
class TaskSettings:
    prompts: TaskPrompts
    template: TaskTemplate
    model: str | None = None
    parameters: Mapping[str, Any] | None = None
    harness: HarnessComponents | None = None


def _check_input_keys(request: AgentRequest) -> list[Issue]:
    issues: list[Issue] = []
    for key in request.input:
        if key != "language":
            message = f"input.{key} is not allowed for TaskAgent; only 'language' is permitted"
            issues.append(Issue(f"input.{key}", message))
    return issues


def _check_plan_milestones(request: AgentRequest) -> list[Issue]:
    plans = artifacts_of(request, "PLAN")
    if len(plans) != 1:
        return []
    plan = plans[0]
    if not isinstance(plan.content, dict) or not isinstance(plan.content.get("text"), str):
        return []
    try:
        parse_milestones(plan.content["text"])
    except Exception as error:
        index = request.artifacts.index(plan)
        message = f"PLAN artifact failed to parse milestones: {error}"
        return [Issue(f"artifacts[{index}].content.text", message)]
    return []


def _check_plan_traceability(request: AgentRequest) -> list[Issue]:
    specs = artifacts_of(request, "SPEC")
    plans = artifacts_of(request, "PLAN")
    if len(specs) != 1 or len(plans) != 1:
        return []
    spec, plan = specs[0], plans[0]
    issues: list[Issue] = []
    if plan.metadata.get("specArtifactId") != spec.id:
        message = (
            "PLAN.metadata.specArtifactId "
            f"'{plan.metadata.get('specArtifactId')}' does not match "
            f"SPEC artifact ID '{spec.id}'"
        )
        issues.append(Issue("artifacts", message))
    if plan.metadata.get("specVersion") != spec.version:
        message = (
            "PLAN.metadata.specVersion "
            f"'{plan.metadata.get('specVersion')}' does not match "
            f"SPEC artifact version '{spec.version}'"
        )
        issues.append(Issue("artifacts", message))
    return issues


@dataclass(frozen=True)
class _PlanContext:
    milestones: list[Milestone]
    milestone_ids: set[str]
    ancestors: dict[str, frozenset[str]]


def _plan_context(plan_art: Artifact) -> _PlanContext:
    plan_text = ""
    if isinstance(plan_art.content, dict) and isinstance(plan_art.content.get("text"), str):
        plan_text = plan_art.content["text"]
    milestones = parse_milestones(plan_text)
    return _PlanContext(
        milestones=milestones,
        milestone_ids={m.id for m in milestones},
        ancestors=milestone_ancestors(milestones),
    )


@dataclass
class _TaskScan:
    all_tasks: list[TaskItem]
    issues: list[str] = field(default_factory=list)
    expected_num: int = 1
    seen_ids: set[str] = field(default_factory=set)
    prev_milestone_num: int = 0


def _validate_task_list(tasks: list[TaskItem], plan: _PlanContext) -> list[str]:
    scan = _TaskScan(all_tasks=tasks)
    for task in tasks:
        _scan_task(scan, task, plan)
    _check_milestone_coverage(scan, tasks, plan)
    if len(tasks) > MAX_TASKS:
        scan.issues.append(f"Too many tasks: {len(tasks)} (maximum {MAX_TASKS})")
    for task in tasks:
        _check_expected_files(scan, task)
    return scan.issues


def _scan_task(scan: _TaskScan, task: TaskItem, plan: _PlanContext) -> None:
    _check_task_identity(scan, task)
    _check_milestone_ref(scan, task, plan)
    _check_dependencies(scan, task)
    _check_cross_milestone(scan, task, plan)


def _check_task_identity(scan: _TaskScan, task: TaskItem) -> None:
    if milestone_number(task.id) != scan.expected_num:
        scan.issues.append(
            f"Task IDs must be sequential: expected T{scan.expected_num}, got {task.id}"
        )
    scan.expected_num += 1
    if task.id in scan.seen_ids:
        scan.issues.append(f"Duplicate task ID: {task.id}")
    scan.seen_ids.add(task.id)


def _check_milestone_ref(scan: _TaskScan, task: TaskItem, plan: _PlanContext) -> None:
    if task.milestone_ref not in plan.milestone_ids:
        scan.issues.append(f"Task {task.id}: milestoneRef '{task.milestone_ref}' not found in PLAN")
        return
    number = milestone_number(task.milestone_ref)
    if number < scan.prev_milestone_num:
        scan.issues.append(
            f"Task {task.id}: milestoneRef must be non-decreasing "
            f"(got {task.milestone_ref} after M{scan.prev_milestone_num})"
        )
    scan.prev_milestone_num = number


def _check_dependencies(scan: _TaskScan, task: TaskItem) -> None:
    for dep in task.depends_on:
        _check_dependency(scan, task, dep)


def _check_dependency(scan: _TaskScan, task: TaskItem, dep: str) -> None:
    if dep == task.id:
        scan.issues.append(f"Task {task.id}: self-dependency is not allowed")
        return
    if dep not in scan.seen_ids:
        scan.issues.append(f"Task {task.id}: depends on later or non-existent task '{dep}'")
        return
    if milestone_number(dep) >= milestone_number(task.id):
        scan.issues.append(f"Task {task.id}: depends on '{dep}' which is not a lower-numbered task")


def _check_cross_milestone(scan: _TaskScan, task: TaskItem, plan: _PlanContext) -> None:
    for dep in task.depends_on:
        _check_cross_dependency(scan, task, dep, plan)


def _check_cross_dependency(scan: _TaskScan, task: TaskItem, dep: str, plan: _PlanContext) -> None:
    dep_task = next((t for t in scan.all_tasks if t.id == dep), None)
    if dep_task is None:
        return
    dep_milestone = dep_task.milestone_ref
    if dep_milestone == task.milestone_ref:
        return
    ancestors = plan.ancestors.get(task.milestone_ref, frozenset())
    if dep_milestone not in ancestors:
        scan.issues.append(
            f"Task {task.id}: cross-milestone dependency on '{dep}' "
            f"(in {dep_milestone}) not allowed; "
            f"{dep_milestone} is not an ancestor of {task.milestone_ref}"
        )


def _check_milestone_coverage(scan: _TaskScan, tasks: list[TaskItem], plan: _PlanContext) -> None:
    for milestone in plan.milestones:
        if not any(t.milestone_ref == milestone.id for t in tasks):
            scan.issues.append(f"Milestone {milestone.id} has no tasks assigned")


def _check_expected_files(scan: _TaskScan, task: TaskItem) -> None:
    for path in task.expected_files:
        _check_expected_file(scan, task, path)


def _check_expected_file(scan: _TaskScan, task: TaskItem, path: str) -> None:
    prefix = f"Task {task.id}: expectedFiles entry '{path}'"
    if path.startswith("/") or _DRIVE_PREFIX.match(path):
        scan.issues.append(f"{prefix} must be relative (no leading '/' or drive letter)")
    if "\\" in path:
        scan.issues.append(f"{prefix} must not contain backslashes")
    if ".." in path.split("/"):
        scan.issues.append(f"{prefix} must not contain '..' segments")
    if "//" in path or any(segment == "" for segment in path.split("/")):
        scan.issues.append(f"{prefix} has empty path segments")
    if any(ord(char) < CONTROL_CHAR_BOUND for char in path):
        scan.issues.append(f"{prefix} contains control characters")


@dataclass(frozen=True)
class _TaskRun:
    request: AgentRequest
    spec_art: Artifact
    plan_art: Artifact
    previous: Artifact | None
    plan: _PlanContext


def _task_run(request: AgentRequest) -> _TaskRun:
    plan_art = artifacts_of(request, "PLAN")[0]
    return _TaskRun(
        request=request,
        spec_art=artifacts_of(request, "SPEC")[0],
        plan_art=plan_art,
        previous=_previous_task(request),
        plan=_plan_context(plan_art),
    )


def _previous_task(request: AgentRequest) -> Artifact | None:
    task_arts = artifacts_of(request, "TASK")
    return task_arts[0] if len(task_arts) == 1 else None


def _previous_task_text(previous: Artifact | None) -> tuple[str, str] | None:
    if previous is None or not isinstance(previous.content, dict):
        return None
    if "text" not in previous.content:
        return None
    return (previous.version, previous.content["text"])


class TaskAgent(BaseAgent):
    """Agent responsible for breaking down plans into implementation tasks."""

    def __init__(self, runtime: AgentRuntime, settings: TaskSettings) -> None:
        super().__init__(runtime)
        self._prompts = settings.prompts
        self._template = settings.template
        self._harness = settings.harness
        self._model = settings.model
        self._parameters = dict(settings.parameters or {})
        self._metadata = AgentMetadata(
            id="agent-task",
            name="Task Agent",
            type="task",
            version="1.0.0",
            status="IDLE",
            capabilities=["write-task", "revise-task"],
            configuration={},
        )

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    def _compute_revision_count(self, request: AgentRequest) -> int:
        """Computes revision count from the TASK artifact version."""
        task_arts = artifacts_of(request, "TASK")
        if task_arts:
            try:
                return int(task_arts[0].version)
            except (ValueError, TypeError):
                return 0
        return 0

    def _check(self, request: AgentRequest) -> list[Issue]:
        agent_id_message = f"agentId '{request.agent_id}' does not match '{self.metadata.id}'"
        revision_message = "Reviewer feedback is required when revising a task breakdown"
        size_message = f"Combined SPEC+PLAN content exceeds {MAX_TASK_CHARS} characters"
        validators = [
            lambda: check_agent_id(request, self.metadata.id, agent_id_message),
            lambda: _check_input_keys(request),
            lambda: check_language(request, "input.language must be a non-empty string"),
            lambda: check_required_artifact(request, "SPEC"),
            lambda: check_required_artifact(request, "PLAN"),
            lambda: _check_plan_milestones(request),
            lambda: check_revision_artifact(request, "TASK", revision_message),
            lambda: check_orphan_feedback(request, "TASK"),
            lambda: check_artifact_types(request, _ALLOWED_TYPES),
            lambda: check_attempt(request),
            lambda: _check_plan_traceability(request),
            lambda: check_text_size(request, {"SPEC", "PLAN"}, MAX_TASK_CHARS, size_message),
        ]
        return [issue for validate in validators for issue in validate()]

    def _run(self, request: AgentRequest) -> tuple[dict[str, Any], list[Artifact]]:
        run = _task_run(request)
        messages = self._build_messages(run)
        response = call_model(self._runtime.models, self._model_request(request, messages))
        tasks = self._checked_tasks(response, run.plan)
        return self._assemble(run, tasks, response)

    def _build_messages(self, run: _TaskRun) -> list[ModelMessage]:
        request = run.request
        context = TaskPromptContext(
            prompts=self._prompts,
            template=self._template,
            spec_artifact=run.spec_art.to_contract(),
            plan_artifact=run.plan_art.to_contract(),
            language=request.input.get("language"),
            project_context=request.context.get("project"),
            previous_task=_previous_task_text(run.previous),
            feedback=request.feedback,
            harness=self._harness,
        )
        return build_task_messages(context)

    def _model_request(self, request: AgentRequest, messages: list[ModelMessage]) -> ModelRequest:
        return ModelRequest(
            messages=messages,
            parameters=dict(self._parameters),
            model=self._model,
            metadata={
                "agentId": self.metadata.id,
                "requestId": request.request_id,
                "cachePrefixMessages": 1,
                **tier_metadata(request.context),
            },
        )

    def _checked_tasks(self, response: ModelResponse, plan: _PlanContext) -> list[TaskItem]:
        reply = unwrap_code_fence(response.content.strip())
        if len(reply) > MAX_TASK_REPLY_CHARS:
            raise invalid_response(
                f"Raw LLM reply exceeds {MAX_TASK_REPLY_CHARS} characters",
                details={"charCount": len(reply), "limit": MAX_TASK_REPLY_CHARS},
            )
        if not reply:
            raise invalid_response("Model returned an empty response")
        tasks = _parse_tasks(reply)
        issues = _validate_task_list(tasks, plan)
        if issues:
            raise invalid_response(
                "Model response has invalid task structure",
                details={"taskIssues": issues},
            )
        return tasks

    def _assemble(
        self,
        run: _TaskRun,
        tasks: list[TaskItem],
        response: ModelResponse,
    ) -> tuple[dict[str, Any], list[Artifact]]:
        previous = run.previous
        version = str(int(previous.version) + 1) if previous is not None else "1"
        rendered = render_task_markdown(
            tasks, run.plan.milestones, run.spec_art.id, run.spec_art.version
        )
        if len(rendered) > MAX_TASK_TEXT_CHARS:
            raise invalid_response(
                f"Rendered task output exceeds {MAX_TASK_TEXT_CHARS} characters",
                details={"charCount": len(rendered), "limit": MAX_TASK_TEXT_CHARS},
            )
        metadata = self._artifact_metadata(run, response)
        artifact = self._task_artifact(tasks, rendered, version, metadata)
        summary = "Task breakdown revised" if previous is not None else "Task breakdown created"
        output = {"summary": summary, "artifactId": artifact.id, "version": version}
        return output, [artifact]

    def _task_artifact(
        self,
        tasks: list[TaskItem],
        rendered: str,
        version: str,
        metadata: dict[str, Any],
    ) -> Artifact:
        return Artifact(
            id=self._runtime.new_id(),
            type="TASK",
            name="TASK.md",
            version=version,
            content={
                "format": "json",
                "tasks": [task.model_dump(by_alias=True) for task in tasks],
                "text": rendered,
            },
            created_by=self.metadata.id,
            created_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            metadata=metadata,
        )

    def _harness_fingerprint(self) -> str:
        components = self._harness or components_from_prompts(
            contract=self._prompts.contract,
            system=self._prompts.system,
            revision=self._prompts.revision,
        )
        return fingerprint(components)

    def _artifact_metadata(self, run: _TaskRun, response: ModelResponse) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "template": "task",
            "harnessFingerprint": self._harness_fingerprint(),
            "model": response.model,
            "usage": {
                "promptTokens": response.usage.prompt_tokens,
                "completionTokens": response.usage.completion_tokens,
            },
            "specArtifactId": run.spec_art.id,
            "specVersion": run.spec_art.version,
            "planArtifactId": run.plan_art.id,
            "planVersion": run.plan_art.version,
        }
        if run.previous is not None:
            metadata["revisionOf"] = run.previous.id
        language = run.request.input.get("language")
        if isinstance(language, str) and language.strip():
            metadata["language"] = language
        return metadata


def _parse_tasks(reply: str) -> list[TaskItem]:
    try:
        task_data = TaskContent.model_validate_json(reply)
    except Exception as error:
        raise invalid_response(
            "Model response is not valid task JSON",
            details={"parseError": str(error)},
        ) from None
    return task_data.tasks
