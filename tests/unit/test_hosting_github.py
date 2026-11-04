"""GitHub hosting adapter against a fake transport."""

from __future__ import annotations

from asf.integrations.hosting.github import GitHubProvider
from asf.tools.changeset import ChangeSet, FileChange
from tests.unit.test_hosting_fake import FakeTransport

API = "https://api.github.com"
REPO = "/repos/octo/demo"


def _provider(transport: FakeTransport) -> GitHubProvider:
    return GitHubProvider(API, "octo", "demo", "secret-token", transport)


def _changes() -> ChangeSet:
    return ChangeSet(changes=[
        FileChange(path="a.py", operation="create", content="a = 1\n"),
        FileChange(path="b.py", operation="delete"),
    ])


def _stub_push_chain(transport: FakeTransport, *, branch_exists: bool) -> None:
    transport.add("GET", "/git/ref/heads/main", {"object": {"sha": "base-sha"}})
    transport.add("GET", "/git/commits/base-sha", {"tree": {"sha": "tree-1"}})
    transport.add("POST", "/git/trees", {"sha": "tree-2"})
    transport.add("POST", "/git/commits", {"sha": "commit-2"})
    if branch_exists:
        transport.add("GET", "/git/ref/heads/asf/task-1", {"object": {"sha": "old"}})
        transport.add("PATCH", "/git/refs/heads/asf/task-1", {})
    else:
        transport.add(
            "GET", "/git/ref/heads/asf/task-1",
            {"message": "Not Found"}, status=404,
        )
        transport.add("POST", "/git/refs", {"ref": "refs/heads/asf/task-1"})


def test_push_creates_branch_via_git_data_api():
    transport = FakeTransport()
    _stub_push_chain(transport, branch_exists=False)
    result = _provider(transport).push_changeset(
        branch="asf/task-1", base_branch="main",
        changes=_changes(), message="Do it",
    )
    assert result.commit_sha == "commit-2"
    tree_call = transport.calls_to("/git/trees")[0]
    assert tree_call["body"]["base_tree"] == "tree-1"
    assert tree_call["body"]["tree"] == [
        {"path": "a.py", "mode": "100644", "type": "blob", "content": "a = 1\n"},
        {"path": "b.py", "mode": "100644", "type": "blob", "sha": None},
    ]
    commit_call = next(
        call for call in transport.calls_to("/git/commits")
        if call["method"] == "POST"
    )
    assert commit_call["body"]["parents"] == ["base-sha"]
    ref_call = transport.calls[-1]
    assert ref_call["method"] == "POST"
    assert ref_call["body"] == {"ref": "refs/heads/asf/task-1", "sha": "commit-2"}
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer secret-token"


def test_push_updates_existing_branch_ref():
    transport = FakeTransport()
    _stub_push_chain(transport, branch_exists=True)
    _provider(transport).push_changeset(
        branch="asf/task-1", base_branch="main",
        changes=_changes(), message="again",
    )
    ref_call = transport.calls[-1]
    assert ref_call["method"] == "PATCH"
    assert ref_call["body"] == {"sha": "commit-2", "force": False}


def test_open_change_request_and_merged_state():
    transport = FakeTransport()
    transport.add("GET", "/pulls?", [])
    transport.add("POST", "/pulls", {
        "number": 5, "html_url": "https://github.com/octo/demo/pull/5",
        "state": "open", "head": {"ref": "asf/task-1"},
    })
    provider = _provider(transport)
    created = provider.open_change_request(
        branch="asf/task-1", base_branch="main", title="T", description="D",
    )
    assert (created.id, created.state) == ("5", "open")
    assert transport.calls[1]["body"]["head"] == "asf/task-1"
    assert transport.calls[1]["body"]["base"] == "main"

    transport2 = FakeTransport()
    transport2.add("GET", "/pulls?", [{
        "number": 6, "html_url": "u", "state": "closed",
        "merged_at": "2026-11-04T00:00:00Z", "head": {"ref": "asf/task-1"},
    }])
    merged = _provider(transport2).change_request(branch="asf/task-1")
    assert merged is not None and merged.state == "merged"


def test_pipeline_status_from_check_runs_and_combined_status():
    transport = FakeTransport()
    transport.add("GET", "/check-runs", {
        "total_count": 2,
        "check_runs": [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "success"},
        ],
    })
    pipeline = _provider(transport).pipeline_status(branch="asf/task-1")
    assert pipeline is not None and pipeline.status == "PASS"

    transport2 = FakeTransport()
    transport2.add("GET", "/check-runs", {
        "total_count": 1,
        "check_runs": [{"status": "in_progress", "conclusion": None}],
    })
    running = _provider(transport2).pipeline_status(branch="asf/task-1")
    assert running is not None and running.status == "RUNNING"

    transport3 = FakeTransport()
    transport3.add("GET", "/check-runs", {"total_count": 0, "check_runs": []})
    transport3.add("GET", "/status", {"state": "failure", "total_count": 1})
    failed = _provider(transport3).pipeline_status(branch="asf/task-1")
    assert failed is not None and failed.status == "FAIL"

    transport4 = FakeTransport()
    transport4.add("GET", "/check-runs", {"total_count": 0, "check_runs": []})
    transport4.add("GET", "/status", {"state": "pending", "total_count": 0})
    assert _provider(transport4).pipeline_status(branch="asf/task-1") is None
