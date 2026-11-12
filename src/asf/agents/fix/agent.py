from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from asf.agents._shared.code_agents import (
    MAX_REPLY_CHARS,
    MAX_TEXT_CHARS,
    CodeRequestRules,
    artifact_of,
    check_code_request,
    code_changeset,
    invalid_response,
    task_item,
)
from asf.agents._shared.codegen import (
    FixContext,
    changeset_secret_issues,
    normalize_changeset_operations,
    validate_changeset,
)
from asf.agents._shared.context_slicing import slice_plan, slice_spec
from asf.agents._shared.harness import HarnessComponents, fingerprint
from asf.agents._shared.limits import MAX_FILE_SIZE_BYTES
from asf.agents._shared.parsing import ParseError, parse_json
from asf.agents._shared.paths import validate_relative_path
from asf.agents._shared.repair import (
    CodeGenerationCall,
    RepairableOutputError,
    enrich_parse_error,
    run_code_generation,
    summarize_validation_issues,
)
from asf.agents._shared.repomap import build_repo_map
from asf.agents._shared.report_tail import tail_artifact_for_prompt
from asf.agents._shared.routing import tier_metadata
from asf.agents.base import (
    AgentErrorOptions,
    AgentExecutionError,
    AgentRuntime,
    BaseAgent,
    Issue,
)
from asf.agents.fix.compose import (
    check_completeness,
    check_delete_targets,
    compose_replacement,
    effective_existing,
    replaceable_paths,
)
from asf.agents.fix.prompts import FixMessageOptions, FixPrompts, build_fix_messages
from asf.agents.implement.prompts import CodeMarkdownContext, render_code_markdown
from asf.contracts.models import (
    AgentMetadata,
    AgentRequest,
    Artifact,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from asf.tools.changeset import ChangeSet
from asf.tools.edit_blocks import EditBlockError, parse_edit_blocks
from asf.tools.ports import (
    FileNotFoundInRepository,
    FileTooLargeError,
    RepositoryError,
    RepositoryPort,
)

_MAX_PREVIOUS_ERROR_CHARS = 2000
_REPORT_TYPES = {"CODE_REVIEW", "TEST_REPORT"}


@dataclass(frozen=True)
class FixSettings:
    prompts: FixPrompts
    model: str | None = None
    parameters: Mapping[str, Any] | None = None
    edit_format: str = "blocks"
    repair_attempts: int = 1
    repo_map_max_chars: int = 6000
    report_tail_lines: int = 120
    harness: HarnessComponents | None = None

    def __post_init__(self) -> None:
        if self.edit_format not in ("blocks", "json"):
            raise ValueError(
                f"edit_format must be 'blocks' or 'json', got {self.edit_format!r}",
            )
        if self.repair_attempts not in (0, 1):
            raise ValueError(
                f"repair_attempts must be 0 or 1, got {self.repair_attempts!r}",
            )


@dataclass(frozen=True)
class _FixRun:
    request: AgentRequest
    spec: Artifact
    plan: Artifact
    task: Artifact
    code: Artifact
    item_id: str
    ref: str
    expected: list[str]
    existing: dict[str, str]
    reports: list[Artifact]
    item: dict[str, Any]
    previous_changeset: ChangeSet
    effective_existing: dict[str, str]


def _reports(request: AgentRequest) -> list[Artifact]:
    return [artifact for artifact in request.artifacts if artifact.type in _REPORT_TYPES]


def _check_previous_error(request: AgentRequest) -> list[Issue]:
    previous_error = request.input.get("previousFixError")
    if previous_error is None:
        return []
    if (
        not isinstance(previous_error, str)
        or not previous_error.strip()
        or len(previous_error) > _MAX_PREVIOUS_ERROR_CHARS
    ):
        message = "previousFixError must be a non-empty string of at most 2000 characters"
        return [Issue("input.previousFixError", message)]
    return []


def _check_report_links(request: AgentRequest) -> list[Issue]:
    reports = _reports(request)
    if not reports:
        return [Issue("artifacts", "At least one CODE_REVIEW or TEST_REPORT is required")]
    codes = [artifact for artifact in request.artifacts if artifact.type == "CODE"]
    if len(codes) != 1:
        return []
    return _check_reports_against_code(request, reports, codes[0])


def _check_reports_against_code(
    request: AgentRequest, reports: list[Artifact], code: Artifact
) -> list[Issue]:
    issues: list[Issue] = []
    if request.input.get("ref") != code.metadata.get("baseRef"):
        issues.append(Issue("input.ref", "Fix ref must equal CODE baseRef"))
    seen: set[str] = set()
    for report in reports:
        issues.extend(_check_report_link(request, report, code, seen))
    return issues


def _check_report_link(
    request: AgentRequest, report: Artifact, code: Artifact, seen: set[str]
) -> list[Issue]:
    issues: list[Issue] = []
    if (
        report.metadata.get("codeArtifactId") != code.id
        or report.metadata.get("codeVersion") != code.version
        or report.metadata.get("taskItemId") != request.input.get("taskItemId")
    ):
        issues.append(Issue("artifacts", "Review/report is stale or for another task"))
    if report.id in seen:
        issues.append(Issue("artifacts", "Duplicate review/report artifact"))
    seen.add(report.id)
    return issues


def _check_project_context(request: AgentRequest) -> list[Issue]:
    issues: list[Issue] = []
    project = request.context.get("project")
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except json.JSONDecodeError:
            issues.append(Issue("context.project", "Project context must be valid JSON"))
    if project is not None and not isinstance(project, dict):
        issues.append(Issue("context.project", "Project context must be a mapping"))
    if isinstance(project, dict):
        skills = project.get("enabledSkills", [])
        if not isinstance(skills, list) or not all(
            isinstance(skill, str) and skill.strip() for skill in skills
        ):
            issues.append(Issue("context.project.enabledSkills", "Invalid enabled skills"))
    return issues


def _check_expected_files(request: AgentRequest) -> list[Issue]:
    try:
        expected = task_item(artifact_of(request, "TASK"), request.input["taskItemId"]).get(
            "expectedFiles"
        )
        valid = _expected_files_valid(expected)
    except (TypeError, ValueError):
        valid = False
    if valid:
        return []
    return [Issue("artifacts.TASK", "Invalid expectedFiles")]


def _expected_files_valid(expected: Any) -> bool:
    if not isinstance(expected, list) or not expected:
        return False
    if any(not isinstance(path, str) or validate_relative_path(path) for path in expected):
        return False
    return len(expected) == len(set(expected))


def _findings(run: _FixRun, tail_lines: int) -> tuple[dict[str, Any], ...]:
    return tuple(
        tail_artifact_for_prompt(artifact.to_contract(), tail_lines) for artifact in run.reports
    )


def _parse_json_changeset(response: ModelResponse, reply: str) -> ChangeSet:
    try:
        return ChangeSet.model_validate(parse_json(reply))
    except (ValueError, ValidationError, ParseError) as error:
        # Keep the underlying reason: "Invalid replacement ChangeSet"
        # alone is undiagnosable (truncated JSON? an extra key? an
        # empty change list?) and the repair prompt is told it
        # verbatim, so it must say what to fix.
        cause = str(error)[:400]
        raise RepairableOutputError(
            "Invalid replacement ChangeSet",
            model_message=(f"The reply was not a valid replacement ChangeSet: {cause}"),
            details={
                "cause": cause,
                "replyChars": len(reply),
                "finishReason": response.finish_reason,
            },
        ) from None


class FixAgent(BaseAgent):
    """Produces a complete replacement CODE without mutating its base repository."""

    def __init__(
        self,
        runtime: AgentRuntime,
        repository: RepositoryPort,
        settings: FixSettings,
    ) -> None:
        super().__init__(runtime)
        self._repository = repository
        self._settings = settings

    @property
    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            id="agent-fix",
            name="Fix Agent",
            type="fix",
            version="1.0.0",
            status="IDLE",
            capabilities=["fix-code"],
            configuration={},
        )

    def _check(self, request: AgentRequest) -> list[Issue]:
        issues = check_code_request(
            request,
            CodeRequestRules(
                agent_id=self.metadata.id,
                required={"SPEC", "PLAN", "TASK", "CODE"},
                optional={"CODE_REVIEW", "TEST_REPORT"},
                require_ref=True,
                extra_input={"previousFixError"},
            ),
        )
        issues.extend(_check_previous_error(request))
        issues.extend(_check_report_links(request))
        if not issues:
            issues.extend(_check_project_context(request))
        if not issues:
            issues.extend(_check_expected_files(request))
        return issues

    def _run(self, request: AgentRequest) -> tuple[dict[str, Any], list[Artifact]]:
        run = self._gather(request)
        model_request = self._model_request(run)
        changeset, usage, repairs = run_code_generation(
            CodeGenerationCall(
                gateway=self._runtime.models,
                request=model_request,
                parse=lambda response: self._parse_reply(run, response),
                repair_attempts=self._settings.repair_attempts,
                format_name="edit-block" if self._settings.edit_format == "blocks" else "JSON",
            )
        )
        return self._assemble(run, changeset, usage, repairs)

    def _gather(self, request: AgentRequest) -> _FixRun:
        task = artifact_of(request, "TASK")
        code = artifact_of(request, "CODE")
        item_id = request.input["taskItemId"]
        ref = request.input["ref"]
        item = task_item(task, item_id)
        expected = item["expectedFiles"]
        existing = self._read_existing(expected, ref)
        previous_changeset = code_changeset(code)
        return _FixRun(
            request=request,
            spec=artifact_of(request, "SPEC"),
            plan=artifact_of(request, "PLAN"),
            task=task,
            code=code,
            item_id=item_id,
            ref=ref,
            expected=expected,
            existing=existing,
            reports=_reports(request),
            item=item,
            previous_changeset=previous_changeset,
            effective_existing=effective_existing(existing, previous_changeset),
        )

    def _read_existing(self, expected: list[str], ref: str) -> dict[str, str]:
        existing: dict[str, str] = {}
        try:
            for path in expected:
                try:
                    existing[path] = self._repository.read_file(
                        path, ref, max_bytes=MAX_FILE_SIZE_BYTES
                    )
                except FileNotFoundInRepository:
                    continue
        except FileTooLargeError:
            raise AgentExecutionError(
                "VALIDATION_FAILED",
                "Base file exceeds the read limit",
                AgentErrorOptions(category="VALIDATION", retryable=False, status="REJECTED"),
            ) from None
        except RepositoryError:
            raise AgentExecutionError(
                "REPOSITORY_ERROR", "Could not read the base repository"
            ) from None
        return existing

    def _build_context(self, run: _FixRun) -> FixContext:
        spec_text = run.spec.to_contract()["content"]["text"]
        plan_text = run.plan.to_contract()["content"]["text"]
        previous_error = run.request.input.get("previousFixError")
        return FixContext(
            task_id=run.item_id,
            spec_summary=slice_spec(
                spec_text,
                task_title=str(run.item.get("title", "")),
                task_description=str(run.item.get("description", "")),
            ),
            plan_summary=slice_plan(
                plan_text,
                str(run.item["milestoneRef"]) if run.item.get("milestoneRef") else None,
            ),
            task_summary=run.task.to_contract()["content"]["text"],
            expected_files=tuple(run.expected),
            existing_files=run.existing,
            review_findings=_findings(run, self._settings.report_tail_lines),
            previous_changeset=run.previous_changeset,
            previous_error=previous_error if isinstance(previous_error, str) else None,
            repo_map=build_repo_map(
                self._repository,
                ref=run.ref,
                expected_files=run.expected,
                max_chars=self._settings.repo_map_max_chars,
            ),
        )

    def _model_request(self, run: _FixRun) -> ModelRequest:
        return ModelRequest(
            messages=build_fix_messages(
                self._settings.prompts,
                run.request,
                self._build_context(run),
                FixMessageOptions(
                    edit_format=self._settings.edit_format,
                    harness=self._settings.harness,
                ),
            ),
            model=self._settings.model,
            parameters=dict(self._settings.parameters or {}),
            metadata={
                "agentId": self.metadata.id,
                "requestId": run.request.request_id,
                "cachePrefixMessages": 1,
                **tier_metadata(run.request.context),
            },
        )

    def _parse_reply(self, run: _FixRun, response: ModelResponse) -> ChangeSet:
        reply = response.content
        if not reply.strip() or len(reply) > MAX_REPLY_CHARS:
            raise invalid_response("Empty or oversized fix reply")
        changeset = self._parse_edits(run, response, reply)
        changeset = self._validate_replacement(run, changeset)
        secret_issues = changeset_secret_issues(changeset)
        if secret_issues:
            raise invalid_response(
                "Replacement contains secret patterns",
                details={"secretIssues": secret_issues},
            )
        return changeset

    def _parse_edits(self, run: _FixRun, response: ModelResponse, reply: str) -> ChangeSet:
        if self._settings.edit_format == "blocks":
            edits = self._parse_blocks(run, response, reply)
        else:
            edits = _parse_json_changeset(response, reply)
        check_delete_targets(run.effective_existing, edits)
        replacement = compose_replacement(run.previous_changeset, run.existing, edits)
        check_completeness(run.previous_changeset, edits, replacement)
        return replacement

    def _parse_blocks(self, run: _FixRun, response: ModelResponse, reply: str) -> ChangeSet:
        try:
            return parse_edit_blocks(
                reply.strip(),
                existing_files=run.effective_existing,
                expected_files=run.expected,
                replaceable_paths=replaceable_paths(
                    run.existing, run.effective_existing, run.previous_changeset
                ),
            )
        except EditBlockError as error:
            raise RepairableOutputError(
                str(error),
                model_message=enrich_parse_error(
                    str(error), path=error.path, existing_content=error.existing_content
                ),
                details={
                    "cause": str(error),
                    "replyChars": len(reply),
                    "finishReason": response.finish_reason,
                },
            ) from None

    def _validate_replacement(self, run: _FixRun, changeset: ChangeSet) -> ChangeSet:
        try:
            changeset = normalize_changeset_operations(
                changeset,
                run.ref,
                self._repository,
            )
            issues = validate_changeset(changeset, run.expected, run.ref, self._repository)
        except RepositoryError:
            raise AgentExecutionError(
                "REPOSITORY_ERROR",
                "Could not validate base files",
            ) from None
        if issues:
            raise RepairableOutputError(
                "Replacement violates scope or content constraints",
                model_message=(
                    "Replacement violates scope or content"
                    " constraints: " + summarize_validation_issues(issues)
                ),
                details=issues,
            )
        return changeset

    def _assemble(
        self,
        run: _FixRun,
        changeset: ChangeSet,
        usage: ModelUsage,
        repairs: int,
    ) -> tuple[dict[str, Any], list[Artifact]]:
        text = render_code_markdown(
            CodeMarkdownContext(
                changes=changeset.model_dump(by_alias=True)["changes"],
                spec_id=run.spec.id,
                spec_version=run.spec.version,
                plan_id=run.plan.id,
                plan_version=run.plan.version,
                task_item_id=run.item_id,
            )
        )
        if len(text) > MAX_TEXT_CHARS:
            raise invalid_response("Rendered CODE exceeds the size limit")
        artifact = self._code_artifact(run, changeset, text)
        return {
            "summary": "Replacement code created",
            "artifactId": artifact.id,
            "version": artifact.version,
            "usage": {
                "promptTokens": usage.prompt_tokens,
                "completionTokens": usage.completion_tokens,
            },
            "repairs": repairs,
        }, [artifact]

    def _harness_fingerprint(self) -> str:
        components = self._settings.harness or self._settings.prompts.to_components()
        return fingerprint(components)

    def _code_artifact(self, run: _FixRun, changeset: ChangeSet, text: str) -> Artifact:
        return Artifact(
            id=self._runtime.new_id(),
            type="CODE",
            name="CODE.json",
            version=str(int(run.code.version) + 1),
            content={
                "format": "json",
                "changeSet": changeset.model_dump(by_alias=True),
                "text": text,
            },
            created_by=self.metadata.id,
            created_at=self._runtime.clock(),
            metadata={
                **_fix_metadata(run),
                "harnessFingerprint": self._harness_fingerprint(),
            },
        )

    def _compute_revision_count(self, request: AgentRequest) -> int:
        codes = [artifact for artifact in request.artifacts if artifact.type == "CODE"]
        if len(codes) == 1 and codes[0].version.isdecimal():
            return int(codes[0].version)
        return 0


def _fix_metadata(run: _FixRun) -> dict[str, Any]:
    return {
        "taskItemId": run.item_id,
        "specArtifactId": run.spec.id,
        "specVersion": run.spec.version,
        "planArtifactId": run.plan.id,
        "planVersion": run.plan.version,
        "taskArtifactId": run.task.id,
        "taskVersion": run.task.version,
        "baseRef": run.ref,
        "revisionOf": run.code.id,
        "fixedReviewIds": [a.id for a in run.reports if a.type == "CODE_REVIEW"],
        "fixedTestReportIds": [a.id for a in run.reports if a.type == "TEST_REPORT"],
    }
