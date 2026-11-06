from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from asf.agents._shared.code_agents import task_item as find_task_item
from asf.agents._shared.codegen import (
    changeset_secret_issues,
    normalize_changeset_operations,
    validate_changeset,
)
from asf.agents._shared.harness import HarnessComponents, fingerprint
from asf.agents._shared.limits import MAX_FILE_SIZE_BYTES
from asf.agents._shared.model_errors import invalid_response
from asf.agents._shared.parsing import parse_json
from asf.agents._shared.paths import validate_relative_path
from asf.agents._shared.repair import (
    CodeGenerationCall,
    RepairableOutputError,
    run_code_generation,
    summarize_validation_issues,
)
from asf.agents._shared.reply_text import unwrap_code_fence
from asf.agents._shared.repomap import build_repo_map
from asf.agents._shared.request_checks import (
    artifacts_of,
    check_agent_id,
    check_artifact_types,
    check_attempt,
    check_language,
    check_ref,
    check_required_artifact,
    check_task_item_id,
    check_text_size,
)
from asf.agents._shared.routing import tier_metadata
from asf.agents._shared.traceability import ArtifactKind, MetadataSpec, build_metadata
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.agents.implement.prompts import (
    CodeMarkdownContext,
    ImplementPromptContext,
    ImplementPrompts,
    build_implement_messages,
    render_code_markdown,
)
from asf.contracts.models import (
    AgentMetadata,
    AgentRequest,
    Artifact,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from asf.models.errors import ModelGatewayError
from asf.tools.changeset import ChangeSet
from asf.tools.edit_blocks import EditBlockError, parse_edit_blocks
from asf.tools.ports import FileNotFoundInRepository, FileTooLargeError, RepositoryPort

__all__ = [
    "MAX_CODE_REPLY_CHARS",
    "MAX_CODE_TEXT_CHARS",
    "ImplementAgent",
    "ImplementSettings",
    "render_code_markdown",
]

_STABLE_PREFIX_MESSAGES = 2

MAX_CODE_REPLY_CHARS: int = 500000
MAX_CODE_TEXT_CHARS: int = 1000000

_ALLOWED_INPUT_KEYS = {"taskItemId", "ref", "language"}
_ALLOWED_ARTIFACT_TYPES = {"SPEC", "PLAN", "TASK"}
_SIZE_KINDS = {"SPEC", "PLAN", "TASK"}


@dataclass(frozen=True)
class ImplementSettings:
    prompts: ImplementPrompts
    model: str | None = None
    parameters: Mapping[str, Any] | None = None
    edit_format: str = "blocks"
    repair_attempts: int = 1
    repo_map_max_chars: int = 6000
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
class _ImplementRun:
    request: AgentRequest
    spec_art: Artifact
    plan_art: Artifact
    task_art: Artifact
    task_item_id: str
    ref: str
    expected_files: list[str]
    existing_files: dict[str, str]


def _check_input_keys(request: AgentRequest) -> list[Issue]:
    issues: list[Issue] = []
    for key in request.input:
        if key not in _ALLOWED_INPUT_KEYS:
            issues.append(
                Issue(
                    f"input.{key}",
                    f"input.{key} is not allowed for ImplementAgent; "
                    "only 'taskItemId', 'ref', 'language' are permitted",
                )
            )
    return issues


def _check_no_code_artifacts(request: AgentRequest) -> list[Issue]:
    if artifacts_of(request, "CODE"):
        message = "CODE artifacts are not permitted as input to ImplementAgent"
        return [Issue("artifacts", message)]
    return []


def _find_task_item(task_art: Artifact, task_item_id: str) -> dict[str, Any]:
    # The item's existence is validated in _check; this conversion
    # keeps the defensive path's error surface.
    try:
        return find_task_item(task_art, task_item_id)
    except ValueError:
        raise invalid_response(
            f"Task item '{task_item_id}' not found in TASK artifact",
            details={"taskItemId": task_item_id},
        ) from None


def _validate_expected_files(task_item_id: str, expected_files: list[str]) -> None:
    for path in expected_files:
        path_issues = validate_relative_path(path)
        if path_issues:
            raise invalid_response(
                f"Task item '{task_item_id}' has invalid expectedFiles "
                f"entry '{path}': {path_issues}",
                details={"taskItemId": task_item_id, "path": path, "issues": path_issues},
            )


def _parse_json_changeset(reply: str) -> ChangeSet:
    """The legacy JSON output format (edit_format="json")."""
    data = _parse_json_data(reply)
    try:
        return ChangeSet.model_validate(data)
    except Exception as error:
        details = _json_changeset_error_details(str(error))
        raise RepairableOutputError(
            "Model response does not match ChangeSet schema",
            model_message=("Model response does not match ChangeSet schema: " + str(details)[:300]),
            details=details,
        ) from None


def _parse_json_data(reply: str) -> Any:
    try:
        return parse_json(reply)
    except Exception as error:
        raise RepairableOutputError(
            "Model response is not valid JSON",
            model_message=f"Model response is not valid JSON ({error})",
            details={"parseError": str(error)},
        ) from None


def _json_changeset_error_details(error_str: str) -> dict[str, Any]:
    if "at most 50" in error_str or "too_long" in error_str:
        return {"limitIssues": ["ChangeSet exceeds limit of 50 changes"]}
    if "at least 1" in error_str or "too_short" in error_str:
        return {"validationError": "ChangeSet is empty"}
    if "NUL" in error_str or "null" in error_str.lower():
        return {"contentIssues": [{"path": "unknown", "issue": "content contains NUL bytes"}]}
    return {"validationError": error_str}


def _rendered_text(run: _ImplementRun, changeset: ChangeSet) -> str:
    return render_code_markdown(
        CodeMarkdownContext(
            changes=[change.model_dump(by_alias=True) for change in changeset.changes],
            spec_id=run.spec_art.id,
            spec_version=run.spec_art.version,
            plan_id=run.plan_art.id,
            plan_version=run.plan_art.version,
            task_item_id=run.task_item_id,
        )
    )


class ImplementAgent(BaseAgent):
    """Agent responsible for implementing code changes for a single task item."""

    def __init__(
        self,
        runtime: AgentRuntime,
        repository: RepositoryPort,
        settings: ImplementSettings,
    ) -> None:
        super().__init__(runtime)
        self._repository = repository
        self._settings = settings
        self._metadata = AgentMetadata(
            id="agent-implement",
            name="Implementation Agent",
            type="implement",
            version="1.0.0",
            status="IDLE",
            capabilities=["write-code"],
            configuration={},
        )

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    def _check(self, request: AgentRequest) -> list[Issue]:
        agent_id_message = f"agentId '{request.agent_id}' does not match '{self.metadata.id}'"
        size_message = f"Combined SPEC+PLAN+TASK content exceeds {MAX_CODE_REPLY_CHARS} characters"
        checks = [
            lambda: check_agent_id(request, self.metadata.id, agent_id_message),
            lambda: check_task_item_id(request),
            lambda: check_ref(request),
            lambda: _check_input_keys(request),
            lambda: check_language(request, "input.language must be a non-empty string"),
            lambda: check_required_artifact(request, "SPEC"),
            lambda: check_required_artifact(request, "PLAN"),
            lambda: check_required_artifact(request, "TASK"),
            lambda: _check_no_code_artifacts(request),
            lambda: check_artifact_types(request, _ALLOWED_ARTIFACT_TYPES),
            lambda: check_attempt(request),
            lambda: check_text_size(request, _SIZE_KINDS, MAX_CODE_REPLY_CHARS, size_message),
        ]
        return [issue for check in checks for issue in check()]

    def _run(self, request: AgentRequest) -> tuple[dict[str, Any], list[Artifact]]:
        run = self._gather(request)
        messages = self._build_messages(run)
        model_request = self._model_request(request, messages)
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

    def _gather(self, request: AgentRequest) -> _ImplementRun:
        task_art = artifacts_of(request, "TASK")[0]
        task_item_id = request.input["taskItemId"]
        task_item = _find_task_item(task_art, task_item_id)
        expected_files = task_item.get("expectedFiles", [])
        _validate_expected_files(task_item_id, expected_files)
        ref = request.input["ref"]
        existing_files = self._read_existing_files(expected_files, ref)
        return _ImplementRun(
            request=request,
            spec_art=artifacts_of(request, "SPEC")[0],
            plan_art=artifacts_of(request, "PLAN")[0],
            task_art=task_art,
            task_item_id=task_item_id,
            ref=ref,
            expected_files=expected_files,
            existing_files=existing_files,
        )

    def _read_existing_files(self, expected_files: list[str], ref: str) -> dict[str, str]:
        existing_files: dict[str, str] = {}
        for path in expected_files:
            try:
                content = self._repository.read_file(path, ref, max_bytes=MAX_FILE_SIZE_BYTES)
                existing_files[path] = content
            except FileNotFoundInRepository:
                pass
            except FileTooLargeError as error:
                raise ModelGatewayError(
                    "INTEGRATION_UNAVAILABLE",
                    f"File '{path}' exceeds size limit",
                    details={
                        "path": path,
                        "maxBytes": MAX_FILE_SIZE_BYTES,
                        "actualBytes": error.max_bytes,
                    },
                ) from None
        return existing_files

    def _build_messages(self, run: _ImplementRun) -> list[ModelMessage]:
        # The output-format contract travels in the user message:
        # edit blocks by default, legacy JSON when configured so.
        repo_map = build_repo_map(
            self._repository,
            ref=run.ref,
            expected_files=run.expected_files,
            max_chars=self._settings.repo_map_max_chars,
        )
        context = ImplementPromptContext(
            prompts=self._settings.prompts,
            spec_artifact=run.spec_art.to_contract(),
            plan_artifact=run.plan_art.to_contract(),
            task_artifact=run.task_art.to_contract(),
            task_item_id=run.task_item_id,
            existing_files=run.existing_files,
            language=run.request.input.get("language"),
            project_context=run.request.context.get("project"),
            edit_format=self._settings.edit_format,
            repo_map=repo_map,
            harness=self._settings.harness,
        )
        return build_implement_messages(context)

    def _model_request(self, request: AgentRequest, messages: list[ModelMessage]) -> ModelRequest:
        return ModelRequest(
            messages=messages,
            parameters=dict(self._settings.parameters or {}),
            model=self._settings.model,
            metadata={
                "agentId": self.metadata.id,
                "requestId": request.request_id,
                # Stable prefix: system + the SPEC/PLAN message.
                "cachePrefixMessages": (
                    _STABLE_PREFIX_MESSAGES if len(messages) > _STABLE_PREFIX_MESSAGES else 1
                ),
                **tier_metadata(request.context),
            },
        )

    def _parse_reply(self, run: _ImplementRun, response: ModelResponse) -> ChangeSet:
        reply = unwrap_code_fence(response.content.strip())
        if len(reply) > MAX_CODE_REPLY_CHARS:
            raise invalid_response(
                f"Raw LLM reply exceeds {MAX_CODE_REPLY_CHARS} characters",
                details={"charCount": len(reply), "limit": MAX_CODE_REPLY_CHARS},
            )
        if not reply:
            raise RepairableOutputError("Model returned an empty response")
        changeset = self._parse_changeset(run, reply)
        # Align operation labels with the repository state (a
        # "create" for a file that already exists is a "modify" in
        # effect), then validate the change set.
        changeset = normalize_changeset_operations(changeset, run.ref, self._repository)
        validation_issues = validate_changeset(
            changeset, run.expected_files, run.ref, self._repository
        )
        if validation_issues:
            raise RepairableOutputError(
                "Model response has invalid change set",
                model_message=(
                    "Model response has invalid change set: "
                    + summarize_validation_issues(validation_issues)
                ),
                details=validation_issues,
            )
        # Secret findings are never repaired: the model must not be
        # negotiated with over leaked credentials.
        secret_issues = changeset_secret_issues(changeset)
        if secret_issues:
            raise invalid_response(
                "Generated content contains secrets",
                details={"secretIssues": secret_issues},
            )
        return changeset

    def _parse_changeset(self, run: _ImplementRun, reply: str) -> ChangeSet:
        if self._settings.edit_format != "blocks":
            return _parse_json_changeset(reply)
        try:
            return parse_edit_blocks(
                reply,
                existing_files=run.existing_files,
                expected_files=run.expected_files,
            )
        except EditBlockError as error:
            raise RepairableOutputError(
                str(error),
                details={"editBlockError": str(error)},
            ) from None

    def _assemble(
        self,
        run: _ImplementRun,
        changeset: ChangeSet,
        usage: ModelUsage,
        repairs: int,
    ) -> tuple[dict[str, Any], list[Artifact]]:
        rendered_text = _rendered_text(run, changeset)
        if len(rendered_text) > MAX_CODE_TEXT_CHARS:
            raise invalid_response(
                f"Rendered code output exceeds {MAX_CODE_TEXT_CHARS} characters",
                details={"charCount": len(rendered_text), "limit": MAX_CODE_TEXT_CHARS},
            )
        artifact = self._code_artifact(run, changeset, rendered_text)
        output = {
            "summary": "Code implementation created",
            "artifactId": artifact.id,
            "version": "1",
            "usage": {
                "promptTokens": usage.prompt_tokens,
                "completionTokens": usage.completion_tokens,
            },
            "repairs": repairs,
        }
        return output, [artifact]

    def _code_artifact(
        self, run: _ImplementRun, changeset: ChangeSet, rendered_text: str
    ) -> Artifact:
        return Artifact(
            id=self._runtime.new_id(),
            type="CODE",
            name="CODE.json",
            version="1",
            content={
                "format": "json",
                "changeSet": changeset.model_dump(by_alias=True),
                "text": rendered_text,
            },
            created_by=self.metadata.id,
            created_at=self._runtime.clock(),
            metadata=self._artifact_metadata(run, changeset),
        )

    def _harness_fingerprint(self) -> str:
        components = self._settings.harness or self._settings.prompts.to_components()
        return fingerprint(components)

    def _artifact_metadata(self, run: _ImplementRun, changeset: ChangeSet) -> dict[str, Any]:
        metadata = build_metadata(
            MetadataSpec(
                kind=ArtifactKind.CODE,
                task_item_id=run.task_item_id,
                generated_at=self._runtime.clock(),
                spec_id=run.spec_art.id,
                plan_id=run.plan_art.id,
                changeset=changeset,
            )
        )
        metadata["harnessFingerprint"] = self._harness_fingerprint()
        metadata["specArtifactId"] = run.spec_art.id
        metadata["specVersion"] = run.spec_art.version
        metadata["planArtifactId"] = run.plan_art.id
        metadata["planVersion"] = run.plan_art.version
        metadata["taskArtifactId"] = run.task_art.id
        metadata["taskVersion"] = run.task_art.version
        metadata["baseRef"] = run.ref
        return metadata
