"""Workflow actions backed by the hosting port: ``run-pipeline`` and
``await-merge``.

These are the handlers the orchestrator invokes for the workflow's CI
and merge steps; they speak the agent result contract like any agent.

Semantics per project, driven by its profile:

- No hosting configured (no provider/URL): the action succeeds as a
  no-op with ``{"hosting": "not-configured"}`` — the same behavior the
  demo stubs had, so unconfigured projects are unaffected.
- ``run-pipeline``: pushes the CODE change set to branch
  ``asf/<task-id>`` (from the artifact's base ref), opens the change
  request if needed, then reads the pipeline: PASS (or no pipeline at
  all) succeeds with the details in the output; FAIL fails the step;
  RUNNING fails with the retryable ``PIPELINE_RUNNING`` error, which
  the step's retry policy turns into polling on later ticks.
- ``await-merge``: succeeds once the change request is merged; while
  it is open it fails with the retryable ``MERGE_PENDING`` error (the
  step's retry policy polls); a change request closed unmerged fails
  the step for good.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from asf.contracts.models import AgentRequest, AgentResult, PlatformError, RunMetrics
from asf.integrations.hosting.factory import build_provider
from asf.integrations.hosting.http import Transport
from asf.integrations.hosting.ports import HostingError, HostingProvider
from asf.tools.changeset import ChangeSet

__all__ = ["build_hosting_actions", "branch_for_task"]

ProfileSource = Callable[[str], Mapping[str, Any] | None]


def branch_for_task(task_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._/-]+", "-", task_id).strip("/") or "task"
    slug = re.sub(r"\.{2,}", ".", slug).strip(".") or "task"
    return f"asf/{slug}"


def build_hosting_actions(
    *,
    profiles: ProfileSource,
    clock: Callable[[], datetime],
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> dict[str, Callable[[AgentRequest], AgentResult]]:
    """Build the ``run-pipeline`` / ``await-merge`` action handlers."""

    def provider_for(request: AgentRequest) -> HostingProvider | None:
        profile = profiles(request.project_id) or {}
        repository = profile.get("repository")
        return build_provider(
            repository if isinstance(repository, Mapping) else None,
            environ=environ,
            transport=transport,
        )

    def run_pipeline(request: AgentRequest) -> AgentResult:
        started = clock()
        try:
            provider = provider_for(request)
        except HostingError as error:
            return _fail(request, started, clock, "HOSTING_CONFIG", str(error))
        if provider is None:
            return _succeed(request, started, clock, {"hosting": "not-configured"})
        code = next((a for a in request.artifacts if a.type == "CODE"), None)
        if code is None or not isinstance(code.content, dict):
            return _fail(
                request, started, clock, "VALIDATION_FAILED",
                "The CI step needs the CODE artifact to push",
            )
        try:
            changes = ChangeSet.model_validate(code.content.get("changeSet"))
        except Exception:
            return _fail(
                request, started, clock, "VALIDATION_FAILED",
                "The CODE artifact does not carry a valid change set",
            )
        branch = branch_for_task(request.task_id)
        base_branch = str(code.metadata.get("baseRef") or "main")
        title = _title(request)
        try:
            push = provider.push_changeset(
                branch=branch, base_branch=base_branch, changes=changes,
                message=f"{title} (task {request.task_id})",
            )
            change_request = provider.open_change_request(
                branch=branch, base_branch=base_branch, title=title,
                description=(
                    f"Opened by AI Software Agents for task "
                    f"{request.task_id} (run {request.metadata.get('runId', '')})."
                ),
            )
            pipeline = provider.pipeline_status(branch=branch)
        except HostingError as error:
            return _fail(
                request, started, clock, "HOSTING_ERROR", str(error),
                retryable=error.retryable,
                details={"httpStatus": error.status} if error.status else {},
            )
        output: dict[str, Any] = {
            "hosting": "configured",
            "branch": branch,
            "commit": push.commit_sha,
            "changeRequest": {
                "id": change_request.id,
                "url": change_request.url,
                "state": change_request.state,
            },
            "pipeline": (
                {"id": pipeline.id, "status": pipeline.status, "url": pipeline.url}
                if pipeline is not None else None
            ),
        }
        if pipeline is not None and pipeline.status == "RUNNING":
            return _fail(
                request, started, clock, "PIPELINE_RUNNING",
                f"CI pipeline {pipeline.id} is still running", retryable=True,
            )
        if pipeline is not None and pipeline.status == "FAIL":
            return _fail(
                request, started, clock, "PIPELINE_FAILED",
                f"CI pipeline {pipeline.id} failed",
            )
        return _succeed(request, started, clock, output)

    def await_merge(request: AgentRequest) -> AgentResult:
        started = clock()
        try:
            provider = provider_for(request)
        except HostingError as error:
            return _fail(request, started, clock, "HOSTING_CONFIG", str(error))
        if provider is None:
            return _succeed(request, started, clock, {"hosting": "not-configured"})
        branch = branch_for_task(request.task_id)
        try:
            change_request = provider.change_request(branch=branch)
        except HostingError as error:
            return _fail(
                request, started, clock, "HOSTING_ERROR", str(error),
                retryable=error.retryable,
                details={"httpStatus": error.status} if error.status else {},
            )
        if change_request is None:
            return _fail(
                request, started, clock, "NO_CHANGE_REQUEST",
                f"No merge/pull request found for branch {branch}; "
                "the CI step must push and open one first",
            )
        output = {
            "hosting": "configured",
            "branch": branch,
            "changeRequest": {
                "id": change_request.id,
                "url": change_request.url,
                "state": change_request.state,
            },
        }
        if change_request.state == "merged":
            return _succeed(request, started, clock, output)
        if change_request.state == "open":
            return _fail(
                request, started, clock, "MERGE_PENDING",
                f"Change request {change_request.id} is still open: "
                f"{change_request.url}",
                retryable=True,
            )
        return _fail(
            request, started, clock, "CHANGE_REQUEST_CLOSED",
            f"Change request {change_request.id} was closed without merging",
        )

    return {"run-pipeline": run_pipeline, "await-merge": await_merge}


def _title(request: AgentRequest) -> str:
    title = request.context.get("title")
    return title if isinstance(title, str) and title.strip() else request.task_id


def _metrics(request: AgentRequest, started: datetime, clock: Callable[[], datetime]):
    attempt = request.metadata.get("attempt")
    return RunMetrics(
        duration_seconds=max(0.0, (clock() - started).total_seconds()),
        revision_count=0,
        attempt=attempt if isinstance(attempt, int) and attempt >= 1 else 1,
    )


def _succeed(
    request: AgentRequest, started: datetime,
    clock: Callable[[], datetime], output: dict[str, Any],
) -> AgentResult:
    return AgentResult(
        request_id=request.request_id, agent_id=request.agent_id,
        status="SUCCESS", output=output, artifacts=[], events=[],
        metrics=_metrics(request, started, clock), errors=[],
    )


def _fail(
    request: AgentRequest, started: datetime, clock: Callable[[], datetime],
    code: str, message: str, *, retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> AgentResult:
    error = PlatformError(
        code=code, message=message, category="INTEGRATION",
        details=details or {}, retryable=retryable, timestamp=clock(),
    )
    return AgentResult(
        request_id=request.request_id, agent_id=request.agent_id,
        status="FAILED", output=None, artifacts=[], events=[],
        metrics=_metrics(request, started, clock), errors=[error],
    )
