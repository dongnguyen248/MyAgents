"""GitLab hosting adapter against a fake transport."""

from __future__ import annotations

import pytest

from asf.integrations.hosting.gitlab import GitLabProvider
from asf.integrations.hosting.ports import HostingError
from asf.tools.changeset import ChangeSet, FileChange
from tests.unit.test_hosting_fake import FakeTransport

API = "https://gitlab.example.com/api/v4"
PROJECT = "group%2Fsub%2Fproj"


def _provider(transport: FakeTransport) -> GitLabProvider:
    return GitLabProvider(API, "group/sub/proj", "secret-token", transport)


def _changes() -> ChangeSet:
    return ChangeSet(
        changes=[
            FileChange(path="src/a.py", operation="create", content="a = 1\n"),
            FileChange(path="src/b.py", operation="modify", content="b = 2\n"),
            FileChange(path="src/c.py", operation="delete"),
        ]
    )


def test_push_creates_branch_with_one_atomic_commit():
    transport = FakeTransport()
    transport.add("POST", "/repository/commits", {"id": "sha-1"})
    result = _provider(transport).push_changeset(
        branch="asf/task-1",
        base_branch="main",
        changes=_changes(),
        message="Do the thing (task task-1)",
    )
    assert result.commit_sha == "sha-1"
    (call,) = transport.calls
    assert call["url"] == f"{API}/projects/{PROJECT}/repository/commits"
    assert call["headers"]["PRIVATE-TOKEN"] == "secret-token"
    assert call["body"]["branch"] == "asf/task-1"
    assert call["body"]["start_branch"] == "main"
    assert call["body"]["actions"] == [
        {"action": "create", "file_path": "src/a.py", "content": "a = 1\n"},
        {"action": "update", "file_path": "src/b.py", "content": "b = 2\n"},
        {"action": "delete", "file_path": "src/c.py"},
    ]


def test_push_onto_existing_branch_retries_without_start_branch():
    transport = FakeTransport()
    transport.add(
        "POST",
        "/repository/commits",
        {"message": "A branch called 'asf/task-1' already exists"},
        status=400,
    )
    transport.add("POST", "/repository/commits", {"id": "sha-2"})
    result = _provider(transport).push_changeset(
        branch="asf/task-1",
        base_branch="main",
        changes=_changes(),
        message="again",
    )
    assert result.commit_sha == "sha-2"
    assert len(transport.calls) == 2
    assert "start_branch" not in transport.calls[1]["body"]


def test_push_propagates_other_errors():
    transport = FakeTransport()
    transport.add("POST", "/repository/commits", {"message": "denied"}, status=403)
    with pytest.raises(HostingError) as caught:
        _provider(transport).push_changeset(
            branch="asf/task-1",
            base_branch="main",
            changes=_changes(),
            message="x",
        )
    assert caught.value.status == 403
    assert caught.value.retryable is False


def test_open_change_request_creates_then_reuses():
    transport = FakeTransport()
    transport.add("GET", "/merge_requests", [])
    transport.add(
        "POST",
        "/merge_requests",
        {
            "iid": 7,
            "web_url": "https://gitlab.example.com/mr/7",
            "state": "opened",
            "source_branch": "asf/task-1",
        },
    )
    provider = _provider(transport)
    created = provider.open_change_request(
        branch="asf/task-1",
        base_branch="main",
        title="T",
        description="D",
    )
    assert (created.id, created.state, created.url) == (
        "7",
        "open",
        "https://gitlab.example.com/mr/7",
    )
    assert transport.calls[1]["body"]["target_branch"] == "main"

    transport2 = FakeTransport()
    transport2.add(
        "GET",
        "/merge_requests",
        [
            {
                "iid": 9,
                "web_url": "u",
                "state": "opened",
                "source_branch": "asf/task-1",
            }
        ],
    )
    reused = _provider(transport2).open_change_request(
        branch="asf/task-1",
        base_branch="main",
        title="T",
        description="D",
    )
    assert reused.id == "9"
    assert len(transport2.calls) == 1  # no POST needed


def test_change_request_state_mapping_and_pipeline_mapping():
    transport = FakeTransport()
    transport.add(
        "GET",
        "/merge_requests",
        [
            {
                "iid": 3,
                "web_url": "u",
                "state": "merged",
                "source_branch": "asf/task-1",
            }
        ],
    )
    transport.add(
        "GET",
        "/pipelines",
        [
            {"id": 42, "status": "success", "web_url": "https://ci/42"},
        ],
    )
    provider = _provider(transport)
    ref = provider.change_request(branch="asf/task-1")
    assert ref is not None and ref.state == "merged"
    pipeline = provider.pipeline_status(branch="asf/task-1")
    assert pipeline is not None
    assert (pipeline.id, pipeline.status) == ("42", "PASS")

    transport2 = FakeTransport()
    transport2.add("GET", "/pipelines", [])
    assert _provider(transport2).pipeline_status(branch="asf/task-1") is None

    transport3 = FakeTransport()
    transport3.add(
        "GET",
        "/pipelines",
        [
            {"id": 1, "status": "running", "web_url": ""},
        ],
    )
    running = _provider(transport3).pipeline_status(branch="asf/task-1")
    assert running is not None and running.status == "RUNNING"
