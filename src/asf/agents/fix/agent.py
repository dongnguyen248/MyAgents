from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from asf.agents._shared.code_agents import (
    MAX_REPLY_CHARS,
    MAX_TEXT_CHARS,
    artifact_of,
    check_code_request,
    code_changeset,
    invalid_response,
    task_item,
)
from asf.agents._shared.codegen import (
    build_fix_context,
    changeset_secret_issues,
    normalize_changeset_operations,
    validate_changeset,
)
from asf.agents._shared.limits import MAX_FILE_SIZE_BYTES
from asf.agents._shared.parsing import ParseError, parse_json
from asf.agents._shared.paths import validate_relative_path
from asf.agents._shared.routing import tier_metadata
from asf.agents.base import AgentExecutionError, AgentRuntime, BaseAgent, Issue
from asf.agents.fix.prompts import FixPrompts, build_fix_messages
from asf.agents.implement.prompts import render_code_markdown
from asf.contracts.models import AgentMetadata, AgentRequest, Artifact, ModelRequest
from asf.tools.changeset import ChangeSet
from asf.tools.ports import (
    FileNotFoundInRepository,
    FileTooLargeError,
    RepositoryError,
    RepositoryPort,
)


class FixAgent(BaseAgent):
    """Produces a complete replacement CODE without mutating its base repository."""

    def __init__(
        self,
        runtime: AgentRuntime,
        repository: RepositoryPort,
        *,
        prompts: FixPrompts,
        model: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(runtime)
        self._repository = repository
        self._prompts = prompts
        self._model = model
        self._parameters = dict(parameters or {})

    @property
    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            id="agent-fix", name="Fix Agent", type="fix", version="1.0.0",
            status="IDLE", capabilities=["fix-code"], configuration={},
        )

    def _check(self, request: AgentRequest) -> list[Issue]:
        issues = check_code_request(
            request, self.metadata.id, {"SPEC", "PLAN", "TASK", "CODE"},
            optional={"CODE_REVIEW", "TEST_REPORT"}, require_ref=True,
            extra_input={"previousFixError"},
        )
        previous_error = request.input.get("previousFixError")
        if previous_error is not None and (
            not isinstance(previous_error, str)
            or not previous_error.strip()
            or len(previous_error) > 2000
        ):
            issues.append(Issue(
                "input.previousFixError",
                "previousFixError must be a non-empty string of at most 2000 characters",
            ))
        reports = [
            artifact for artifact in request.artifacts
            if artifact.type in {"CODE_REVIEW", "TEST_REPORT"}
        ]
        if not reports:
            issues.append(Issue("artifacts", "At least one CODE_REVIEW or TEST_REPORT is required"))
        codes = [artifact for artifact in request.artifacts if artifact.type == "CODE"]
        if len(codes) == 1:
            code = codes[0]
            if request.input.get("ref") != code.metadata.get("baseRef"):
                issues.append(Issue("input.ref", "Fix ref must equal CODE baseRef"))
            ids: set[str] = set()
            for report in reports:
                if (
                    report.metadata.get("codeArtifactId") != code.id
                    or report.metadata.get("codeVersion") != code.version
                    or report.metadata.get("taskItemId") != request.input.get("taskItemId")
                ):
                    issues.append(Issue("artifacts", "Review/report is stale or for another task"))
                if report.id in ids:
                    issues.append(Issue("artifacts", "Duplicate review/report artifact"))
                ids.add(report.id)
        if not issues:
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
        if not issues:
            try:
                expected = task_item(
                    artifact_of(request, "TASK"), request.input["taskItemId"]
                ).get("expectedFiles")
                if (
                    not isinstance(expected, list) or not expected
                    or any(
                        not isinstance(path, str) or validate_relative_path(path)
                        for path in expected
                    )
                    or len(expected) != len(set(expected))
                ):
                    issues.append(Issue("artifacts.TASK", "Invalid expectedFiles"))
            except (TypeError, ValueError):
                issues.append(Issue("artifacts.TASK", "Invalid expectedFiles"))
        return issues

    def _run(self, request: AgentRequest) -> tuple[dict[str, Any], list[Artifact]]:
        spec = artifact_of(request, "SPEC")
        plan = artifact_of(request, "PLAN")
        task = artifact_of(request, "TASK")
        code = artifact_of(request, "CODE")
        item_id = request.input["taskItemId"]
        ref = request.input["ref"]
        expected = task_item(task, item_id)["expectedFiles"]
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
                "VALIDATION_FAILED", "Base file exceeds the read limit",
                category="VALIDATION", retryable=False, status="REJECTED",
            ) from None
        except RepositoryError:
            raise AgentExecutionError("REPOSITORY_ERROR", "Could not read the base repository") \
                from None
        reports = [
            artifact for artifact in request.artifacts
            if artifact.type in {"CODE_REVIEW", "TEST_REPORT"}
        ]
        previous_error = request.input.get("previousFixError")
        context = build_fix_context(
            task_id=item_id, spec_summary=spec.to_contract()["content"]["text"],
            plan_summary=plan.to_contract()["content"]["text"],
            task_summary=task.to_contract()["content"]["text"],
            expected_files=expected, existing_files=existing,
            review_findings=[artifact.to_contract() for artifact in reports],
            previous_changeset=code_changeset(code),
            previous_error=previous_error if isinstance(previous_error, str) else None,
        )
        response = self._runtime.models.complete(
            ModelRequest(
                messages=build_fix_messages(self._prompts, request, context),
                model=self._model, parameters=self._parameters,
                metadata={
                    "agentId": self.metadata.id, "requestId": request.request_id,
                    **tier_metadata(request.context),
                },
            )
        )
        if not response.content.strip() or len(response.content) > MAX_REPLY_CHARS:
            raise invalid_response("Empty or oversized fix reply")
        try:
            changeset = ChangeSet.model_validate(parse_json(response.content))
        except (ValueError, ValidationError, ParseError) as exc:
            # Keep the underlying reason: "Invalid replacement
            # ChangeSet" alone is undiagnosable (truncated JSON? an
            # extra key? an empty change list?) and the next attempt
            # is told this error verbatim, so it must say what to fix.
            raise invalid_response(
                "Invalid replacement ChangeSet",
                details={
                    "cause": str(exc)[:400],
                    "replyChars": len(response.content),
                    "finishReason": response.finish_reason,
                },
            ) from None
        try:
            changeset = normalize_changeset_operations(changeset, ref, self._repository)
            issues = validate_changeset(changeset, expected, ref, self._repository)
        except RepositoryError:
            raise AgentExecutionError("REPOSITORY_ERROR", "Could not validate base files") from None
        if issues:
            raise invalid_response(
                "Replacement violates scope or content constraints",
                details=issues,
            )
        secret_issues = changeset_secret_issues(changeset)
        if secret_issues:
            raise invalid_response(
                "Replacement contains secret patterns",
                details={"secretIssues": secret_issues},
            )
        text = render_code_markdown(
            changeset.model_dump(by_alias=True)["changes"],
            spec.id, spec.version, plan.id, plan.version, item_id,
        )
        if len(text) > MAX_TEXT_CHARS:
            raise invalid_response("Rendered CODE exceeds the size limit")
        version = str(int(code.version) + 1)
        metadata = {
            "taskItemId": item_id, "specArtifactId": spec.id, "specVersion": spec.version,
            "planArtifactId": plan.id, "planVersion": plan.version,
            "taskArtifactId": task.id, "taskVersion": task.version,
            "baseRef": ref, "revisionOf": code.id,
            "fixedReviewIds": [a.id for a in reports if a.type == "CODE_REVIEW"],
            "fixedTestReportIds": [a.id for a in reports if a.type == "TEST_REPORT"],
        }
        artifact = Artifact(
            id=self._runtime.new_id(), type="CODE", name="CODE.json", version=version,
            content={"format": "json", "changeSet": changeset.model_dump(by_alias=True),
                     "text": text},
            created_by=self.metadata.id, created_at=self._runtime.clock(), metadata=metadata,
        )
        return {
            "summary": "Replacement code created", "artifactId": artifact.id, "version": version,
        }, [artifact]

    def _compute_revision_count(self, request: AgentRequest) -> int:
        codes = [artifact for artifact in request.artifacts if artifact.type == "CODE"]
        if len(codes) == 1 and codes[0].version.isdecimal():
            return int(codes[0].version)
        return 0
