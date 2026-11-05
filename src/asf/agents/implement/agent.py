from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from asf.agents._shared.codegen import (
    changeset_secret_issues,
    normalize_changeset_operations,
    validate_changeset,
)
from asf.agents._shared.limits import (
    MAX_FILE_SIZE_BYTES,
)
from asf.agents._shared.model_errors import invalid_response
from asf.agents._shared.parsing import parse_json
from asf.agents._shared.paths import validate_relative_path
from asf.agents._shared.repair import (
    RepairableOutputError,
    run_code_generation,
    summarize_validation_issues,
)
from asf.agents._shared.routing import tier_metadata
from asf.agents._shared.traceability import ArtifactKind, build_metadata
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.agents.implement.prompts import (
    ImplementPrompts,
    build_implement_messages,
    render_code_markdown,
)
from asf.contracts.models import (
    AgentMetadata,
    AgentRequest,
    Artifact,
    ModelRequest,
    ModelResponse,
)
from asf.models.errors import ModelGatewayError
from asf.tools.changeset import ChangeSet
from asf.tools.edit_blocks import EditBlockError, parse_edit_blocks
from asf.tools.ports import FileNotFoundInRepository, FileTooLargeError, RepositoryPort

__all__ = [
    "MAX_CODE_REPLY_CHARS",
    "MAX_CODE_TEXT_CHARS",
    "ImplementAgent",
    "render_code_markdown",
]

MAX_CODE_REPLY_CHARS: int = 500000
MAX_CODE_TEXT_CHARS: int = 1000000


class ImplementAgent(BaseAgent):
    """Agent responsible for implementing code changes for a single task item."""

    def __init__(
        self,
        runtime: AgentRuntime,
        repository: RepositoryPort,
        *,
        prompts: ImplementPrompts,
        model: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        edit_format: str = "blocks",
        repair_attempts: int = 1,
    ) -> None:
        super().__init__(runtime)
        if edit_format not in ("blocks", "json"):
            raise ValueError(
                f"edit_format must be 'blocks' or 'json', got {edit_format!r}",
            )
        if repair_attempts not in (0, 1):
            raise ValueError(
                f"repair_attempts must be 0 or 1, got {repair_attempts!r}",
            )
        self._repository = repository
        self._prompts = prompts
        self._model = model
        self._parameters = dict(parameters or {})
        self._edit_format = edit_format
        self._repair_attempts = repair_attempts
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
        issues: list[Issue] = []

        # 1. agentId check
        if request.agent_id != self.metadata.id:
            issues.append(
                Issue(
                    "agentId",
                    f"agentId '{request.agent_id}' does not match '{self.metadata.id}'",
                )
            )

        # 2. input.taskItemId required, matches regex
        task_item_id = request.input.get("taskItemId")
        if not task_item_id:
            issues.append(Issue("input.taskItemId", "input.taskItemId is required"))
        elif not isinstance(task_item_id, str):
            issues.append(Issue("input.taskItemId", "input.taskItemId must be a string"))
        elif not re.match(r"^T[1-9][0-9]*$", task_item_id):
            issues.append(
                Issue(
                    "input.taskItemId",
                    f"input.taskItemId '{task_item_id}' must match '^T[1-9][0-9]*$'",
                )
            )

        # 3. input.ref required, non-empty string
        ref = request.input.get("ref")
        if not ref:
            issues.append(Issue("input.ref", "input.ref is required"))
        elif not isinstance(ref, str) or not ref.strip():
            issues.append(Issue("input.ref", "input.ref must be a non-empty string"))

        # 4. input keys validation
        allowed_input_keys = {"taskItemId", "ref", "language"}
        for key in request.input:
            if key not in allowed_input_keys:
                issues.append(
                    Issue(
                        f"input.{key}",
                        f"input.{key} is not allowed for ImplementAgent; "
                        "only 'taskItemId', 'ref', 'language' are permitted",
                    )
                )

        # 5. input.language, if present
        if "language" in request.input:
            lang = request.input["language"]
            if not isinstance(lang, str) or not lang.strip():
                issues.append(Issue("input.language", "input.language must be a non-empty string"))

        # 6. Exactly 1 SPEC artifact required
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

        # 7. Exactly 1 PLAN artifact required
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

        # 8. Exactly 1 TASK artifact required
        task_arts = [a for a in request.artifacts if a.type == "TASK"]
        task_art_idx = -1
        if len(task_arts) != 1:
            issues.append(
                Issue("artifacts", "Exactly one artifact of type TASK is required")
            )
        else:
            task_art = task_arts[0]
            task_art_idx = request.artifacts.index(task_art)
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


        # 9. No CODE artifacts present (no revision mode)
        code_arts = [a for a in request.artifacts if a.type == "CODE"]
        if code_arts:
            issues.append(
                Issue("artifacts", "CODE artifacts are not permitted as input to ImplementAgent")
            )

        # 10. No unknown artifact types
        allowed_types = {"SPEC", "PLAN", "TASK"}
        for idx, art in enumerate(request.artifacts):
            if art.type not in allowed_types:
                issues.append(
                    Issue(
                        f"artifacts[{idx}].type",
                        f"Unknown artifact type '{art.type}'; allowed: {sorted(allowed_types)}",
                    )
                )

        # 11. metadata.attempt, if present
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

        # 12. SPEC+PLAN+TASK content size limit
        total_chars = 0
        for art in spec_arts + plan_arts + task_arts:
            if isinstance(art.content, dict) and isinstance(art.content.get("text"), str):
                total_chars += len(art.content["text"])
        if total_chars > MAX_CODE_REPLY_CHARS:
            issues.append(
                Issue(
                    "artifacts",
                    f"Combined SPEC+PLAN+TASK content exceeds {MAX_CODE_REPLY_CHARS} characters",
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
        task_art = task_arts[0]
        task_artifact_dict = task_art.to_contract()

        task_item_id = request.input["taskItemId"]
        ref = request.input["ref"]
        language = request.input.get("language")
        project_context = request.context.get("project")

        # Find the task item in the TASK artifact (validated in _check)
        task_item = None
        if isinstance(task_art.content, dict):
            content = task_art.content
            # Tasks may be in content["tasks"] directly or in content["text"] as JSON string
            tasks = None
            if isinstance(content.get("tasks"), list):
                tasks = content["tasks"]
            elif isinstance(content.get("text"), str):
                try:
                    import json as _json
                    task_content = _json.loads(content["text"])
                    if isinstance(task_content.get("tasks"), list):
                        tasks = task_content["tasks"]
                except _json.JSONDecodeError:
                    pass
            if tasks:
                for task in tasks:
                    if task.get("id") == task_item_id:
                        task_item = task
                        break

        # task_item is guaranteed to exist due to _check validation
        if task_item is None:
            raise invalid_response(
                f"Task item '{task_item_id}' not found in TASK artifact",
                details={"taskItemId": task_item_id},
            )
        expected_files = task_item.get("expectedFiles", [])

        # Validate expected_files with shared path validator
        for f in expected_files:
            path_issues = validate_relative_path(f)
            if path_issues:
                raise invalid_response(
                    f"Task item '{task_item_id}' has invalid expectedFiles "
                    f"entry '{f}': {path_issues}",
                    details={"taskItemId": task_item_id, "path": f, "issues": path_issues},
                )

        # Read existing files through RepositoryPort
        existing_files: dict[str, str] = {}

        for path in expected_files:
            try:
                file_content = self._repository.read_file(path, ref, max_bytes=MAX_FILE_SIZE_BYTES)
                existing_files[path] = file_content
            except FileNotFoundInRepository:
                # File doesn't exist - this is fine for create operations
                pass
            except FileTooLargeError as e:
                raise ModelGatewayError(
                    "INTEGRATION_UNAVAILABLE",
                    f"File '{path}' exceeds size limit",
                    details={
                        "path": path,
                        "maxBytes": MAX_FILE_SIZE_BYTES,
                        "actualBytes": e.max_bytes,
                    },
                )

        # Build messages (the output-format contract travels in the
        # user message: edit blocks by default, legacy JSON when the
        # agent is configured with edit_format="json").
        messages = build_implement_messages(
            prompts=self._prompts,
            spec_artifact=spec_artifact_dict,
            plan_artifact=plan_artifact_dict,
            task_artifact=task_artifact_dict,
            task_item_id=task_item_id,
            existing_files=existing_files,
            language=language,
            project_context=project_context,
            edit_format=self._edit_format,
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

        def parse_reply(response: ModelResponse) -> ChangeSet:
            reply = response.content.strip()
            # Unwrap single code fence if wrapped
            if reply.startswith("```") and reply.endswith("```"):
                lines = reply.splitlines()
                if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
                    reply = "\n".join(lines[1:-1]).strip()
            if len(reply) > MAX_CODE_REPLY_CHARS:
                raise invalid_response(
                    f"Raw LLM reply exceeds {MAX_CODE_REPLY_CHARS} characters",
                    details={"charCount": len(reply), "limit": MAX_CODE_REPLY_CHARS},
                )
            if not reply:
                raise RepairableOutputError("Model returned an empty response")
            if self._edit_format == "blocks":
                try:
                    changeset = parse_edit_blocks(
                        reply,
                        existing_files=existing_files,
                        expected_files=expected_files,
                    )
                except EditBlockError as error:
                    raise RepairableOutputError(
                        str(error),
                        details={"editBlockError": str(error)},
                    ) from None
            else:
                changeset = self._parse_json_changeset(reply)
            # Align operation labels with the repository state (a
            # "create" for a file that already exists is a "modify" in
            # effect), then validate the change set.
            changeset = normalize_changeset_operations(
                changeset, ref, self._repository,
            )
            validation_issues = self._validate_changeset(
                changeset, expected_files, existing_files, ref, self._repository,
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
            # Secret findings are never repaired: the model must not
            # be negotiated with over leaked credentials.
            secret_issues = self._scan_changeset_for_secrets(changeset)
            if secret_issues:
                raise invalid_response(
                    "Generated content contains secrets",
                    details={"secretIssues": secret_issues},
                )
            return changeset

        changeset, usage, repairs = run_code_generation(
            gateway=self._runtime.models,
            request=model_req,
            parse=parse_reply,
            repair_attempts=self._repair_attempts,
            format_name="edit-block" if self._edit_format == "blocks" else "JSON",
        )

        # Render deterministic markdown text
        rendered_text = render_code_markdown(
            [fc.model_dump(by_alias=True) for fc in changeset.changes],
            spec_art.id,
            spec_art.version,
            plan_art.id,
            plan_art.version,
            task_item_id,
        )

        # Output size limit
        if len(rendered_text) > MAX_CODE_TEXT_CHARS:
            raise invalid_response(
                f"Rendered code output exceeds {MAX_CODE_TEXT_CHARS} characters",
                details={"charCount": len(rendered_text), "limit": MAX_CODE_TEXT_CHARS},
            )

        # Build artifact metadata with traceability
        art_metadata = build_metadata(
            ArtifactKind.CODE,
            task_item_id=task_item_id,
            generated_at=self._runtime.clock(),
            spec_id=spec_art.id,
            plan_id=plan_art.id,
            changeset=changeset,
        )
        # Add additional metadata per D3/D12
        art_metadata["specArtifactId"] = spec_art.id
        art_metadata["specVersion"] = spec_art.version
        art_metadata["planArtifactId"] = plan_art.id
        art_metadata["planVersion"] = plan_art.version
        art_metadata["taskArtifactId"] = task_art.id
        art_metadata["taskVersion"] = task_art.version
        art_metadata["baseRef"] = ref

        art_id = self._runtime.new_id()
        artifact = Artifact(
            id=art_id,
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
            metadata=art_metadata,
        )

        output = {
            "summary": "Code implementation created",
            "artifactId": art_id,
            "version": "1",
            "usage": {
                "promptTokens": usage.prompt_tokens,
                "completionTokens": usage.completion_tokens,
            },
            "repairs": repairs,
        }

        return output, [artifact]

    def _parse_json_changeset(self, reply: str) -> ChangeSet:
        """The legacy JSON output format (edit_format="json")."""
        try:
            data = parse_json(reply)
        except Exception as error:
            raise RepairableOutputError(
                "Model response is not valid JSON",
                model_message=f"Model response is not valid JSON ({error})",
                details={"parseError": str(error)},
            ) from None
        try:
            return ChangeSet.model_validate(data)
        except Exception as error:
            # Convert Pydantic ValidationError to expected format
            error_str = str(error)
            details: dict[str, Any] = {"validationError": error_str}
            if "at most 50" in error_str or "too_long" in error_str:
                details = {"limitIssues": ["ChangeSet exceeds limit of 50 changes"]}
            elif "at least 1" in error_str or "too_short" in error_str:
                details = {"validationError": "ChangeSet is empty"}
            elif "NUL" in error_str or "null" in error_str.lower():
                details = {
                    "contentIssues": [{"path": "unknown", "issue": "content contains NUL bytes"}]
                }
            elif "duplicate" in error_str.lower():
                details = {"validationError": error_str}
            raise RepairableOutputError(
                "Model response does not match ChangeSet schema",
                model_message=(
                    "Model response does not match ChangeSet schema: "
                    + str(details)[:300]
                ),
                details=details,
            ) from None

    def _validate_changeset(
        self,
        changeset: ChangeSet,
        expected_files: list[str],
        existing_files: dict[str, str],
        ref: str,
        repository: RepositoryPort,
    ) -> dict[str, Any] | None:
        """Validate the change set against all rules. Returns dict of issues or None."""
        return validate_changeset(changeset, expected_files, ref, repository)

    def _scan_changeset_for_secrets(self, changeset: ChangeSet) -> list[dict[str, Any]]:
        """Scan all file contents in changeset for secrets."""
        return changeset_secret_issues(changeset)
