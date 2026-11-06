"""Hosting workflow actions (run-pipeline / await-merge)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import asf.integrations.hosting.actions as actions_module
from asf.contracts.models import AgentRequest, Artifact
from asf.integrations.hosting.actions import branch_for_task, build_hosting_actions
from asf.integrations.hosting.ports import (
    ChangeRequestRef,
    HostingError,
    PipelineRef,
    PushResult,
)

NOW = datetime(2026, 11, 4, tzinfo=UTC)

PROFILES = {
    "proj": {"repository": {"provider": "gitlab", "url": "https://gitlab.com/g/proj"}},
}


class FakeProvider:
    def __init__(self) -> None:
        self.pipeline: PipelineRef | None = PipelineRef("9", "PASS", "https://ci/9")
        self.change_request_state = "merged"
        self.push_error: HostingError | None = None
        self.description: str | None = None
        self.calls: list[str] = []

    def push_changeset(self, *, branch, base_branch, changes, message):  # noqa: ANN001, ANN202
        self.calls.append(f"push:{branch}:{base_branch}")
        if self.push_error is not None:
            raise self.push_error
        return PushResult(branch=branch, commit_sha="sha-9")

    def open_change_request(self, *, branch, base_branch, title, description):  # noqa: ANN001, ANN202
        self.calls.append(f"open:{branch}")
        self.description = description
        return ChangeRequestRef("4", "https://mr/4", "open", branch)

    def change_request(self, *, branch):  # noqa: ANN001, ANN202
        self.calls.append(f"cr:{branch}")
        if self.change_request_state == "none":
            return None
        return ChangeRequestRef(
            "4",
            "https://mr/4",
            self.change_request_state,
            branch,
        )

    def pipeline_status(self, *, branch):  # noqa: ANN001, ANN202
        self.calls.append(f"pipeline:{branch}")
        return self.pipeline


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    fake = FakeProvider()
    monkeypatch.setattr(
        actions_module,
        "build_provider",
        lambda repository, environ=None, transport=None: fake,
    )
    return fake


def _actions():
    return build_hosting_actions(
        profiles=lambda pid: PROFILES.get(pid),
        clock=lambda: NOW,
    )


def _request(action: str, *, with_code: bool = True) -> AgentRequest:
    artifacts = []
    if with_code:
        artifacts.append(
            Artifact(
                id="code-1",
                type="CODE",
                name="CODE.json",
                version="1",
                content={
                    "format": "json",
                    "changeSet": {
                        "changes": [
                            {"path": "a.py", "operation": "create", "content": "a = 1\n"},
                        ]
                    },
                    "text": "code",
                },
                created_by="agent-implement",
                created_at=NOW,
                metadata={"baseRef": "main"},
            )
        )
    return AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj",
        workflow_id="software-development",
        agent_id=f"action:{action}",
        context={"title": "Build the thing"},
        artifacts=artifacts,
        metadata={"attempt": 1, "runId": "run-1", "stepId": "ci"},
    )


def test_not_configured_projects_keep_noop_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        actions_module,
        "build_provider",
        lambda repository, environ=None, transport=None: None,
    )
    actions = _actions()
    result = actions["run-pipeline"](_request("run-pipeline"))
    assert result.status == "SUCCESS"
    assert result.output == {"hosting": "not-configured"}
    result = actions["await-merge"](_request("await-merge"))
    assert result.status == "SUCCESS"


def test_run_pipeline_pushes_opens_and_passes(provider: FakeProvider):
    result = _actions()["run-pipeline"](_request("run-pipeline"))
    assert result.status == "SUCCESS"
    assert provider.calls == [
        "push:asf/task-1:main",
        "open:asf/task-1",
        "pipeline:asf/task-1",
    ]
    assert result.output["commit"] == "sha-9"
    assert result.output["changeRequest"]["id"] == "4"
    assert result.output["pipeline"]["status"] == "PASS"


def test_run_pipeline_running_waits_and_failed_fails(provider: FakeProvider):
    provider.pipeline = PipelineRef("9", "RUNNING", "")
    result = _actions()["run-pipeline"](_request("run-pipeline"))
    assert result.status == "FAILED"
    assert result.errors[0].code == "PIPELINE_RUNNING"
    assert result.errors[0].retryable is True

    provider.pipeline = PipelineRef("9", "FAIL", "")
    result = _actions()["run-pipeline"](_request("run-pipeline"))
    assert result.errors[0].code == "PIPELINE_FAILED"
    assert result.errors[0].retryable is False


def test_run_pipeline_without_pipeline_succeeds(provider: FakeProvider):
    provider.pipeline = None
    result = _actions()["run-pipeline"](_request("run-pipeline"))
    assert result.status == "SUCCESS"
    assert result.output["pipeline"] is None


def test_run_pipeline_hosting_error_maps_retryable(provider: FakeProvider):
    provider.push_error = HostingError("boom", status=503, retryable=True)
    result = _actions()["run-pipeline"](_request("run-pipeline"))
    assert result.status == "FAILED"
    assert result.errors[0].code == "HOSTING_ERROR"
    assert result.errors[0].retryable is True
    assert result.errors[0].details == {"httpStatus": 503}


def test_await_merge_states(provider: FakeProvider):
    actions = _actions()
    provider.change_request_state = "merged"
    assert actions["await-merge"](_request("await-merge")).status == "SUCCESS"

    provider.change_request_state = "open"
    result = actions["await-merge"](_request("await-merge"))
    assert result.errors[0].code == "MERGE_PENDING"
    assert result.errors[0].retryable is True

    provider.change_request_state = "closed"
    result = actions["await-merge"](_request("await-merge"))
    assert result.errors[0].code == "CHANGE_REQUEST_CLOSED"
    assert result.errors[0].retryable is False

    provider.change_request_state = "none"
    result = actions["await-merge"](_request("await-merge"))
    assert result.errors[0].code == "NO_CHANGE_REQUEST"


def test_missing_token_surfaces_as_config_error():
    # No monkeypatch: the real factory raises for a URL without a token.
    actions = build_hosting_actions(
        profiles=lambda pid: PROFILES.get(pid),
        clock=lambda: NOW,
        environ={},
    )
    result = actions["run-pipeline"](_request("run-pipeline"))
    assert result.status == "FAILED"
    assert result.errors[0].code == "HOSTING_CONFIG"
    assert "ASF_GITLAB_TOKEN" in result.errors[0].message


def test_workflow_policies_cover_the_polling_error_codes():
    from pathlib import Path

    import asf
    from asf.workflow.loader import load_workflow

    root = Path(asf.__file__).resolve().parents[2]
    definition = load_workflow(root / "workflow-definitions" / "software-development.yaml")
    steps = {step.id: step for step in definition.steps}
    assert steps["ci"].retry_policy is not None
    assert steps["ci"].retry_policy.retry_on == ["PIPELINE_RUNNING"]
    assert steps["merge"].retry_policy is not None
    assert steps["merge"].retry_policy.retry_on == ["MERGE_PENDING"]


def test_branch_for_task_sanitizes():
    assert branch_for_task("task-1") == "asf/task-1"
    assert branch_for_task("My Task #2") == "asf/My-Task-2"
    assert branch_for_task("a..b") == "asf/a.b"


def test_opened_change_request_carries_a_rule_shaped_description(provider: FakeProvider):
    from asf.integrations.hosting.description import (
        SECTION_HEADINGS,
        validate_description,
    )

    result = _actions()["run-pipeline"](_request("run-pipeline"))
    assert result.status == "SUCCESS"
    description = provider.description
    assert description is not None
    assert validate_description(description) == []
    for heading in SECTION_HEADINGS:
        assert heading in description
    assert "task-1" in description
    assert "`a.py` - created by the implement step" in description


def test_run_pipeline_refuses_to_open_when_description_is_invalid(
    provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        actions_module, "validate_description", lambda text: ["missing heading: ## Why"]
    )
    result = _actions()["run-pipeline"](_request("run-pipeline"))
    assert result.status == "FAILED"
    assert result.errors[0].code == "VALIDATION_FAILED"
    assert "missing heading: ## Why" in result.errors[0].message
    # Nothing was pushed and nothing was opened.
    assert provider.calls == []
    assert provider.description is None
