from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from asf.agents._shared.model_errors import invalid_response
from asf.agents._shared.routing import tier_metadata
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.agents.plan.milestones import (
    Milestone,
    milestone_ancestors,
    milestone_number,
    parse_milestones,
)
from asf.agents.task.prompts import (
    TaskPrompts,
    TaskTemplate,
    build_task_messages,
)
from asf.contracts.models import AgentMetadata, AgentRequest, Artifact, ModelRequest

__all__ = [
    "MAX_TASK_CHARS",
    "MAX_TASK_TEXT_CHARS",
    "MAX_TASK_REPLY_CHARS",
    "MAX_TASKS",
    "TaskAgent",
    "render_task_markdown",
]

MAX_TASK_CHARS: int = 50000
MAX_TASKS: int = 100
MAX_TASK_TEXT_CHARS: int = 200000
MAX_TASK_REPLY_CHARS: int = 500000


def _reject_whitespace_only(value: str, field_name: str) -> str:
    """Reject whitespace-only strings."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string (whitespace-only not allowed)")
    return value


def _validate_list_no_whitespace(v: list[str], field_name: str) -> list[str]:
    """Validate list items are non-empty strings (no whitespace-only)."""
    for item in v:
        if not isinstance(item, str) or not item.strip():
            msg = f"{field_name} items must be non-empty strings (whitespace-only not allowed)"
            raise ValueError(msg)
    return v


def render_task_markdown(
    tasks: list[TaskItem],
    plan_milestones: list[Milestone],
    spec_id: str,
    spec_version: str,
) -> str:
    """Deterministically render markdown from validated tasks."""
    lines: list[str] = []
    lines.append("# TASK: Breakdown")
    lines.append("")
    lines.append("## Linked SPEC")
    lines.append(f"ID: {spec_id}")
    lines.append(f"Version: {spec_version}")
    lines.append("")

    # Group tasks by milestone
    tasks_by_milestone: dict[str, list[TaskItem]] = {}
    for task in tasks:
        tasks_by_milestone.setdefault(task.milestone_ref, []).append(task)

    # Sort milestones by numeric order
    sorted_milestone_ids = sorted(plan_milestones, key=lambda m: milestone_number(m.id))

    for milestone in sorted_milestone_ids:
        milestone_tasks = tasks_by_milestone.get(milestone.id, [])
        if not milestone_tasks:
            continue
        lines.append(f"## Milestone {milestone.id}: {milestone.name}")
        lines.append("")
        for task in milestone_tasks:
            lines.append(f"### {task.id}: {task.title}")
            lines.append("")
            lines.append(f"**Description:** {task.description}")
            lines.append("")
            lines.append("**Acceptance Criteria:**")
            for ac in task.acceptance_criteria:
                lines.append(f"- {ac}")
            lines.append("")
            if task.depends_on:
                lines.append(f"**Depends On:** {', '.join(task.depends_on)}")
                lines.append("")
            if task.expected_files:
                lines.append("**Expected Files:**")
                for f in task.expected_files:
                    lines.append(f"- {f}")
                lines.append("")
            lines.append(f"**Verification Hint:** {task.verification_hint}")
            lines.append("")

    return "\n".join(lines).strip()


class TaskItem(BaseModel):
    """A single task item in the task list."""
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    id: str = Field(..., min_length=1, alias="id")
    title: str = Field(..., min_length=1, alias="title")
    milestone_ref: str = Field(..., min_length=1, alias="milestoneRef")
    description: str = Field(..., min_length=1, alias="description")
    acceptance_criteria: list[str] = Field(..., min_length=1, alias="acceptanceCriteria")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    expected_files: list[str] = Field(default_factory=list, alias="expectedFiles")
    verification_hint: str = Field(..., min_length=1, alias="verificationHint")

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        if not re.match(r"^T[1-9][0-9]*$", v):
            raise ValueError(f"Task ID '{v}' must match '^T[1-9][0-9]*$'")
        return v

    @field_validator("id", "title", "milestone_ref", "description", "verification_hint")
    @classmethod
    def validate_no_whitespace_strings(cls, v: str) -> str:
        return _reject_whitespace_only(v, "String field")

    @field_validator("acceptance_criteria", "depends_on", "expected_files", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("Must be a list")
        return v

    @field_validator("acceptance_criteria", "depends_on", "expected_files")
    @classmethod
    def validate_no_duplicates(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("List contains duplicate entries")
        return v

    @field_validator("acceptance_criteria", "depends_on", "expected_files")
    @classmethod
    def validate_no_whitespace_strings_in_list(cls, v: list[str]) -> list[str]:
        return _validate_list_no_whitespace(v, "List field")


class TaskContent(BaseModel):
    """Full task output content."""
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    tasks: list[TaskItem] = Field(..., min_length=1, alias="tasks")


class TaskAgent(BaseAgent):
    """Agent responsible for breaking down plans into implementation tasks."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        prompts: TaskPrompts,
        template: TaskTemplate,
        model: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(runtime)
        self._prompts = prompts
        self._template = template
        self._model = model
        self._parameters = dict(parameters or {})
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
        task_arts = [a for a in request.artifacts if a.type == "TASK"]
        if task_arts:
            try:
                return int(task_arts[0].version)
            except (ValueError, TypeError):
                return 0
        return 0

    def _check(self, request: AgentRequest) -> list[Issue]:
        issues: list[Issue] = []

        # 1. agentId check
        if request.agent_id != self.metadata.id:
            issues.append(
                Issue(
                    "agentId",
                    f"agentId '{request.agent_id}' does not match '{self.metadata.id}'",
                )
            )

        # 2. input keys validation - only 'language' allowed
        allowed_input_keys = {"language"}
        for key in request.input:
            if key not in allowed_input_keys:
                issues.append(
                    Issue(
                        f"input.{key}",
                        f"input.{key} is not allowed for TaskAgent; only 'language' is permitted",
                    )
                )

        # 3. input.language, if present
        if "language" in request.input:
            lang = request.input["language"]
            if not isinstance(lang, str) or not lang.strip():
                issues.append(Issue("input.language", "input.language must be a non-empty string"))

        # 4. Exactly one SPEC artifact required
        spec_arts = [a for a in request.artifacts if a.type == "SPEC"]
        spec_art_idx = -1
        if len(spec_arts) != 1:
            issues.append(
                Issue("artifacts", "Exactly one artifact of type SPEC is required")
            )
        else:
            spec_art = spec_arts[0]
            spec_art_idx = request.artifacts.index(spec_art)
            if (
                not isinstance(spec_art.content, dict)
                or not isinstance(spec_art.content.get("text"), str)
                or not spec_art.content.get("text", "").strip()
            ):
                issues.append(
                    Issue(
                        f"artifacts[{spec_art_idx}].content.text",
                        "SPEC artifact must have inline content mapping with non-empty 'text'",
                    )
                )
            # SPEC version must match ^[1-9][0-9]*$
            is_valid_ver = isinstance(spec_art.version, str) and bool(
                re.match(r"^[1-9][0-9]*$", spec_art.version)
            )
            if not is_valid_ver:
                issues.append(
                    Issue(
                        f"artifacts[{spec_art_idx}].version",
                        f"SPEC artifact version '{spec_art.version}' must match '^[1-9][0-9]*$'",
                    )
                )

        # 5. Exactly one PLAN artifact required
        plan_arts = [a for a in request.artifacts if a.type == "PLAN"]
        plan_art_idx = -1
        if len(plan_arts) != 1:
            issues.append(
                Issue("artifacts", "Exactly one artifact of type PLAN is required")
            )
        else:
            plan_art = plan_arts[0]
            plan_art_idx = request.artifacts.index(plan_art)
            if (
                not isinstance(plan_art.content, dict)
                or not isinstance(plan_art.content.get("text"), str)
                or not plan_art.content.get("text", "").strip()
            ):
                issues.append(
                    Issue(
                        f"artifacts[{plan_art_idx}].content.text",
                        "PLAN artifact must have inline content mapping with non-empty 'text'",
                    )
                )
            # PLAN version must match ^[1-9][0-9]*$
            is_valid_ver = isinstance(plan_art.version, str) and bool(
                re.match(r"^[1-9][0-9]*$", plan_art.version)
            )
            if not is_valid_ver:
                issues.append(
                    Issue(
                        f"artifacts[{plan_art_idx}].version",
                        f"PLAN artifact version '{plan_art.version}' must match '^[1-9][0-9]*$'",
                    )
                )

            # PLAN must parse into >= 1 milestone with no parse errors
            if isinstance(plan_art.content, dict) and isinstance(plan_art.content.get("text"), str):
                try:
                    parse_milestones(plan_art.content["text"])
                except Exception as e:
                    issues.append(
                        Issue(
                            f"artifacts[{plan_art_idx}].content.text",
                            f"PLAN artifact failed to parse milestones: {e}",
                        )
                    )

        # 6. At most one TASK artifact (for revision mode)
        task_arts = [a for a in request.artifacts if a.type == "TASK"]
        if len(task_arts) > 1:
            issues.append(
                Issue("artifacts", "At most one artifact of type TASK is permitted")
            )

        is_revision = len(task_arts) == 1

        # 7. Revision mode iff a TASK artifact is present
        if is_revision:
            task_art = task_arts[0]
            task_art_idx = request.artifacts.index(task_art)

            if not request.feedback:
                issues.append(
                    Issue(
                        "feedback",
                        "Reviewer feedback is required when revising a task breakdown",
                    )
                )

            if (
                not isinstance(task_art.content, dict)
                or not isinstance(task_art.content.get("text"), str)
                or not task_art.content.get("text", "").strip()
            ):
                issues.append(
                    Issue(
                        f"artifacts[{task_art_idx}].content.text",
                        "TASK artifact must have inline content mapping with non-empty 'text'",
                    )
                )

            # Version must match ^[1-9][0-9]*$
            is_valid_ver = isinstance(task_art.version, str) and bool(
                re.match(r"^[1-9][0-9]*$", task_art.version)
            )
            if not is_valid_ver:
                issues.append(
                    Issue(
                        f"artifacts[{task_art_idx}].version",
                        f"TASK artifact version '{task_art.version}' must match '^[1-9][0-9]*$'",
                    )
                )

        # 8. Feedback without TASK artifact
        if request.feedback and not is_revision:
            issues.append(
                Issue("artifacts", "feedback provided without a previous TASK artifact to revise")
            )

        # 9. Reject unknown artifact types
        allowed_types = {"SPEC", "PLAN", "TASK"}
        for idx, art in enumerate(request.artifacts):
            if art.type not in allowed_types:
                issues.append(
                    Issue(
                        f"artifacts[{idx}].type",
                        f"Unknown artifact type '{art.type}'; allowed: {sorted(allowed_types)}",
                    )
                )

        # 10. metadata.attempt, if present
        if "attempt" in request.metadata:
            attempt_val = request.metadata["attempt"]
            if (
                not isinstance(attempt_val, int)
                or isinstance(attempt_val, bool)
                or attempt_val < 1
            ):
                issues.append(
                    Issue("metadata.attempt", "metadata.attempt must be an integer >= 1")
                )

        # 11. PLAN traceability must match SPEC
        spec_arts = [a for a in request.artifacts if a.type == "SPEC"]
        plan_arts = [a for a in request.artifacts if a.type == "PLAN"]
        if len(spec_arts) == 1 and len(plan_arts) == 1:
            spec_art = spec_arts[0]
            plan_art = plan_arts[0]
            plan_meta = plan_art.metadata
            if plan_meta.get("specArtifactId") != spec_art.id:
                issues.append(
                    Issue(
                        "artifacts",
                        "PLAN.metadata.specArtifactId "
                        f"'{plan_meta.get('specArtifactId')}' does not match "
                        f"SPEC artifact ID '{spec_art.id}'",
                    )
                )
            if plan_meta.get("specVersion") != spec_art.version:
                issues.append(
                    Issue(
                        "artifacts",
                        "PLAN.metadata.specVersion "
                        f"'{plan_meta.get('specVersion')}' does not match "
                        f"SPEC artifact version '{spec_art.version}'",
                    )
                )

        # 12. SPEC + PLAN content size limit
        total_chars = 0
        for art in spec_arts + plan_arts:
            if isinstance(art.content, dict) and isinstance(art.content.get("text"), str):
                total_chars += len(art.content["text"])
        if total_chars > MAX_TASK_CHARS:
            issues.append(
                Issue(
                    "artifacts",
                    f"Combined SPEC+PLAN content exceeds {MAX_TASK_CHARS} characters",
                )
            )

        return issues

    def _run(self, request: AgentRequest) -> tuple[dict[str, Any], list[Artifact]]:
        # Extract artifacts
        spec_arts = [a for a in request.artifacts if a.type == "SPEC"]
        spec_art = spec_arts[0]
        spec_artifact_dict = spec_art.to_contract()

        plan_arts = [a for a in request.artifacts if a.type == "PLAN"]
        plan_art = plan_arts[0]
        plan_artifact_dict = plan_art.to_contract()

        task_arts = [a for a in request.artifacts if a.type == "TASK"]
        is_revision = len(task_arts) == 1
        prev_task_art = task_arts[0] if is_revision else None

        previous_task: tuple[str, str] | None = None
        if (
            prev_task_art
            and isinstance(prev_task_art.content, dict)
            and "text" in prev_task_art.content
        ):
            previous_task = (
                prev_task_art.version,
                prev_task_art.content["text"],
            )

        language = request.input.get("language")
        project_context = request.context.get("project")

        # Parse PLAN milestones for validation context
        plan_text = ""
        if isinstance(plan_art.content, dict) and isinstance(plan_art.content.get("text"), str):
            plan_text = plan_art.content["text"]
        plan_milestones = parse_milestones(plan_text)
        plan_milestone_ids = {m.id for m in plan_milestones}
        plan_milestone_ancestors = milestone_ancestors(plan_milestones)

        messages = build_task_messages(
            prompts=self._prompts,
            template=self._template,
            spec_artifact=spec_artifact_dict,
            plan_artifact=plan_artifact_dict,
            language=language,
            project_context=project_context,
            previous_task=previous_task,
            feedback=request.feedback,
        )

        model_req = ModelRequest(
            messages=messages,
            parameters=dict(self._parameters),
            model=self._model,
            metadata={
                "agentId": self.metadata.id, "requestId": request.request_id,
                **tier_metadata(request.context),
            },
        )

        response = self._runtime.models.complete(model_req)
        reply = response.content.strip()

        # Unwrap single code fence if wrapped
        if reply.startswith("```") and reply.endswith("```"):
            lines = reply.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
                reply = "\n".join(lines[1:-1]).strip()

        # Raw reply size limit
        if len(reply) > MAX_TASK_REPLY_CHARS:
            raise invalid_response(
                f"Raw LLM reply exceeds {MAX_TASK_REPLY_CHARS} characters",
                details={"charCount": len(reply), "limit": MAX_TASK_REPLY_CHARS},
            )

        if not reply:
            raise invalid_response(
                "Model returned an empty response",
            )

        # Validate JSON output
        try:
            task_data = TaskContent.model_validate_json(reply)
        except Exception as e:
            raise invalid_response(
                "Model response is not valid task JSON",
                details={"parseError": str(e)},
            )

        tasks = task_data.tasks
        task_issues: list[str] = []

        # Validate task IDs are T1..Tn numerically
        expected_num = 1
        seen_task_ids: set[str] = set()
        prev_milestone_num = 0

        for task in tasks:
            # Check ID format and sequential numeric
            if milestone_number(task.id) != expected_num:
                task_issues.append(
                    f"Task IDs must be sequential: expected T{expected_num}, got {task.id}"
                )
            expected_num += 1

            # Check uniqueness
            if task.id in seen_task_ids:
                task_issues.append(f"Duplicate task ID: {task.id}")
            seen_task_ids.add(task.id)

            # milestoneRef exists in PLAN
            if task.milestone_ref not in plan_milestone_ids:
                task_issues.append(
                    f"Task {task.id}: milestoneRef '{task.milestone_ref}' not found in PLAN"
                )
            else:
                # milestoneRef non-decreasing
                m_num = milestone_number(task.milestone_ref)
                if m_num < prev_milestone_num:
                    task_issues.append(
                        f"Task {task.id}: milestoneRef must be non-decreasing "
                        f"(got {task.milestone_ref} after M{prev_milestone_num})"
                    )
                prev_milestone_num = m_num

            # dependsOn: only existing tasks with LOWER number; no self-dependency
            for dep in task.depends_on:
                if dep == task.id:
                    task_issues.append(f"Task {task.id}: self-dependency is not allowed")
                elif dep not in seen_task_ids:
                    task_issues.append(
                        f"Task {task.id}: depends on later or non-existent task '{dep}'"
                    )
                else:
                    # Check numeric ordering of dependency
                    if milestone_number(dep) >= milestone_number(task.id):
                        task_issues.append(
                            f"Task {task.id}: depends on '{dep}' which is not a lower-numbered task"
                        )

            # Cross-milestone dependency rule
            # Task in Mx may depend on My only if My == Mx or My is ancestor of Mx
            task_milestone = task.milestone_ref
            for dep in task.depends_on:
                # Find dependency task
                dep_task = next((t for t in tasks if t.id == dep), None)
                if dep_task:
                    dep_milestone = dep_task.milestone_ref
                    if dep_milestone != task_milestone:
                        # Check if dep_milestone is ancestor of task_milestone
                        ancestors = plan_milestone_ancestors.get(task_milestone, frozenset())
                        if dep_milestone not in ancestors:
                            task_issues.append(
                                f"Task {task.id}: cross-milestone dependency on '{dep}' "
                                f"(in {dep_milestone}) not allowed; "
                                f"{dep_milestone} is not an ancestor of {task_milestone}"
                            )

        # Every PLAN milestone must have >= 1 task
        for milestone in plan_milestones:
            if not any(t.milestone_ref == milestone.id for t in tasks):
                task_issues.append(
                    f"Milestone {milestone.id} has no tasks assigned"
                )

        # Max tasks
        if len(tasks) > MAX_TASKS:
            task_issues.append(f"Too many tasks: {len(tasks)} (maximum {MAX_TASKS})")

        # Validate expectedFiles rules
        for task in tasks:
            for f in task.expected_files:
                # relative only, no leading "/"
                if f.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", f):
                    task_issues.append(
                        f"Task {task.id}: expectedFiles entry '{f}' must be relative "
                        "(no leading '/' or drive letter)"
                    )
                # no backslashes
                if "\\" in f:
                    task_issues.append(
                        f"Task {task.id}: expectedFiles entry '{f}' must not contain backslashes"
                    )
                # no ".." segment
                if ".." in f.split("/"):
                    task_issues.append(
                        f"Task {task.id}: expectedFiles entry '{f}' must not contain '..' segments"
                    )
                # no empty segments or "//"
                if "//" in f or any(seg == "" for seg in f.split("/")):
                    task_issues.append(
                        f"Task {task.id}: expectedFiles entry '{f}' has empty path segments"
                    )
                # no NUL/control characters
                if any(ord(c) < 32 for c in f):
                    task_issues.append(
                        f"Task {task.id}: expectedFiles entry '{f}' contains control characters"
                    )

        if task_issues:
            raise invalid_response(
                "Model response has invalid task structure",
                details={"taskIssues": task_issues},
            )

        # Determine version
        if is_revision and prev_task_art:
            version = str(int(prev_task_art.version) + 1)
        else:
            version = "1"

        # Render deterministic markdown text from validated tasks
        rendered_text = render_task_markdown(
            tasks, plan_milestones, spec_art.id, spec_art.version
        )

        # Output size limit
        if len(rendered_text) > MAX_TASK_TEXT_CHARS:
            raise invalid_response(
                f"Rendered task output exceeds {MAX_TASK_TEXT_CHARS} characters",
                details={"charCount": len(rendered_text), "limit": MAX_TASK_TEXT_CHARS},
            )

        # Build artifact metadata with traceability
        art_metadata: dict[str, Any] = {
            "template": "task",
            "model": response.model,
            "usage": {
                "promptTokens": response.usage.prompt_tokens,
                "completionTokens": response.usage.completion_tokens,
            },
            "specArtifactId": spec_art.id,
            "specVersion": spec_art.version,
            "planArtifactId": plan_art.id,
            "planVersion": plan_art.version,
        }
        if is_revision and prev_task_art:
            art_metadata["revisionOf"] = prev_task_art.id
        if language and isinstance(language, str) and language.strip():
            art_metadata["language"] = language

        art_id = self._runtime.new_id()
        placeholder_dt = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        artifact = Artifact(
            id=art_id,
            type="TASK",
            name="TASK.md",
            version=version,
            content={
                "format": "json",
                "tasks": [t.model_dump(by_alias=True) for t in tasks],
                "text": rendered_text,
            },
            created_by=self.metadata.id,
            created_at=placeholder_dt,
            metadata=art_metadata,
        )

        summary = "Task breakdown revised" if is_revision else "Task breakdown created"
        output = {
            "summary": summary,
            "artifactId": art_id,
            "version": version,
        }

        return output, [artifact]