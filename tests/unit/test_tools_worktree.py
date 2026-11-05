"""Per-run git worktrees: isolation, PASS commits, fix resets,
cleanup, orphan sweep, and the non-git fallback.

Every test builds a REAL git repository in a temp folder — the
worktree behaviour under test is git's, so faking it would prove
nothing.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from asf.api.demo import _WorkspaceBindingAgent
from asf.api.service import FactoryService
from asf.contracts.models import AgentRequest, AgentResult, Artifact, RunMetrics
from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.fake import InMemoryRepository, ScriptedSandbox
from asf.tools.local import LocalWorkspace, WorkspaceRepository, WorkspaceSandbox
from asf.tools.ports import CommandSpec
from asf.tools.worktree import GitWorktreeWorkspace, validate_run_id
from tests.unit.test_api_service import PROJECTS, FakeMetrics
from tests.unit.test_workspace_concurrency import build_engine

PYTHON = sys.executable
NOW = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)


def git(path: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}"
    return proc.stdout


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.com")
    (path / "app.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-m", "base")
    return path


def make_workspace(tmp_path: Path, repo: Path) -> LocalWorkspace:
    return LocalWorkspace(
        {"proj": repo},
        worktrees=GitWorktreeWorkspace(tmp_path / "worktrees"),
    )


def _changeset(*changes: FileChange) -> ChangeSet:
    return ChangeSet(changes=list(changes))


def _create(path: str, content: str) -> FileChange:
    return FileChange(path=path, operation="create", content=content)


def _modify(path: str, content: str) -> FileChange:
    return FileChange(path=path, operation="modify", content=content)


def _run_sandbox(workspace: LocalWorkspace, changes: ChangeSet, code: str):
    sandbox = WorkspaceSandbox(workspace, ScriptedSandbox())
    return sandbox.run(
        [CommandSpec(argv=(PYTHON, "-c", code))],
        changes,
        "main",
    )


PASS = "pass"
FAIL = "raise SystemExit(1)"


# -- isolation ----------------------------------------------------------------


def test_two_runs_of_one_project_never_see_each_others_changes(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    workspace = make_workspace(tmp_path, repo)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def work(run_id: str) -> None:
        try:
            token = workspace.bind("proj", run_id)
            try:
                root = workspace.current_root("main")
                assert root is not None and root != repo
                barrier.wait(timeout=15)  # both worktrees exist now
                _run_sandbox(
                    workspace,
                    _changeset(
                        _create(f"marker-{run_id}.py", f"# {run_id}\n"),
                    ),
                    PASS,
                )
                tree = WorkspaceRepository(
                    workspace,
                    InMemoryRepository(),
                ).list_tree("main")
                assert f"marker-{run_id}.py" in tree
                other = "run-2" if run_id == "run-1" else "run-1"
                assert f"marker-{other}.py" not in tree
            finally:
                workspace.reset_binding(token)
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=work, args=(run_id,)) for run_id in ("run-1", "run-2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors
    # The user's own tree never saw either run's files.
    assert not (repo / "marker-run-1.py").exists()
    assert not (repo / "marker-run-2.py").exists()
    assert git(repo, "status", "--porcelain").strip() == ""
    branches = git(repo, "branch", "--list", "asf/*")
    assert "asf/run-1" in branches and "asf/run-2" in branches


# -- FAILED runs leave the project tree clean ----------------------------------


def test_failed_run_changes_never_reach_the_project_tree(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    workspace = make_workspace(tmp_path, repo)
    token = workspace.bind("proj", "run-fail")
    try:
        _run_sandbox(
            workspace,
            _changeset(
                _create("junk.py", "# junk\n"),
                _modify("app.py", "VALUE = 'x'\n"),
            ),
            FAIL,
        )
    finally:
        workspace.reset_binding(token)
    assert not (repo / "junk.py").exists()
    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 'base'\n"
    assert git(repo, "status", "--porcelain").strip() == ""

    workspace.finish_run("proj", "run-fail", "FAILED")
    worktrees = workspace.worktrees
    assert worktrees is not None
    assert not worktrees.worktree_path("proj", "run-fail").exists()
    assert "asf/run-fail" not in git(repo, "branch", "--list", "asf/*")


# -- the PASS / fix state convention --------------------------------------------


def test_fix_changeset_lands_on_the_last_passing_commit(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    workspace = make_workspace(tmp_path, repo)
    repository = WorkspaceRepository(workspace, InMemoryRepository())
    token = workspace.bind("proj", "run-fix")
    try:
        # Item v1 passes -> committed as the green baseline.
        _run_sandbox(
            workspace,
            _changeset(
                _modify("app.py", "VALUE = 'v1-good'\n"),
            ),
            PASS,
        )
        sha = workspace.commit_current_worktree(
            "asf: task item T1 — code code-1 v1 (tests passed)",
        )
        assert sha is not None
        # A broken attempt: applied, tests fail, nothing committed.
        _run_sandbox(
            workspace,
            _changeset(
                _modify("app.py", "VALUE = 'broken'\n"),
                _create("broken.py", "# broken\n"),
            ),
            FAIL,
        )
        # The fix agent reads the broken state it has to fix.
        assert repository.read_file("app.py", "main") == "VALUE = 'broken'\n"
        # The replacement change set must land on the PASS baseline:
        # the reset wipes broken.py and the broken edit first.
        _run_sandbox(
            workspace,
            _changeset(
                _modify("app.py", "VALUE = 'v2-fixed'\n"),
            ),
            PASS,
        )
        worktree = workspace.current_root("main")
        assert worktree is not None
        assert not (worktree / "broken.py").exists()
        assert repository.read_file("app.py", "main") == "VALUE = 'v2-fixed'\n"
        sha2 = workspace.commit_current_worktree(
            "asf: task item T1 — code code-1 v2 (tests passed)",
        )
        assert sha2 is not None and sha2 != sha
        log = git(worktree, "log", "--format=%s")
        assert "code code-1 v2" in log and "code code-1 v1" in log
        # The broken content was never committed anywhere.
        assert "broken" not in git(worktree, "log", "-p", "--format=")
    finally:
        workspace.reset_binding(token)


# -- cleanup policy ---------------------------------------------------------------


def test_finish_run_cleanup_policy(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    workspace = make_workspace(tmp_path, repo)
    worktrees = workspace.worktrees
    assert worktrees is not None

    def start(run_id: str) -> None:
        token = workspace.bind("proj", run_id)
        try:
            workspace.current_root("main")
        finally:
            workspace.reset_binding(token)

    start("run-done")
    workspace.finish_run("proj", "run-done", "COMPLETED")
    assert worktrees.has_worktree("proj", "run-done")  # kept for review
    assert "asf/run-done" in git(repo, "branch", "--list", "asf/*")

    start("run-cancelled")
    workspace.finish_run("proj", "run-cancelled", "CANCELLED")
    assert not worktrees.has_worktree("proj", "run-cancelled")
    assert "asf/run-cancelled" not in git(repo, "branch", "--list", "asf/*")

    strict = LocalWorkspace(
        {"proj": repo},
        worktrees=GitWorktreeWorkspace(
            tmp_path / "worktrees",
            cleanup_completed=True,
        ),
    )
    token = strict.bind("proj", "run-done-2")
    try:
        strict.current_root("main")
    finally:
        strict.reset_binding(token)
    strict.finish_run("proj", "run-done-2", "COMPLETED")
    assert not strict.worktrees.has_worktree("proj", "run-done-2")  # type: ignore[union-attr]


# -- orphan sweep -------------------------------------------------------------------


def test_startup_sweep_removes_orphans_and_keeps_live_work(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    workspace = make_workspace(tmp_path, repo)
    for run_id in ("run-failed", "run-gone", "run-active", "run-done"):
        token = workspace.bind("proj", run_id)
        try:
            workspace.current_root("main")
        finally:
            workspace.reset_binding(token)
    stages = {
        "run-failed": "FAILED",
        "run-active": "ACTIVE",
        "run-done": "COMPLETED",
    }
    removed = workspace.sweep_orphans(lambda run_id: stages.get(run_id))
    assert any("run-failed" in entry for entry in removed)
    assert any("run-gone" in entry for entry in removed)  # unknown run
    worktrees = workspace.worktrees
    assert worktrees is not None
    assert not worktrees.has_worktree("proj", "run-failed")
    assert not worktrees.has_worktree("proj", "run-gone")
    assert worktrees.has_worktree("proj", "run-active")
    assert worktrees.has_worktree("proj", "run-done")


# -- non-git projects -----------------------------------------------------------------


def test_non_git_project_keeps_direct_behaviour_with_a_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    workspace = LocalWorkspace(
        {"proj": plain},
        worktrees=GitWorktreeWorkspace(tmp_path / "worktrees"),
    )
    token = workspace.bind("proj", "run-plain")
    try:
        with caplog.at_level(logging.WARNING, logger="asf.tools.local"):
            root = workspace.current_root("main")
            workspace.current_root("main")  # warns once, not per call
        assert root == plain
        warnings = [
            record
            for record in caplog.records
            if record.levelno == logging.WARNING and "not a git repository" in record.getMessage()
        ]
        assert len(warnings) == 1
        _run_sandbox(
            workspace,
            _changeset(
                _create("direct.py", "# written directly\n"),
            ),
            PASS,
        )
        # Old behaviour: the change lands in the user's folder itself.
        assert (plain / "direct.py").exists()
    finally:
        workspace.reset_binding(token)


# -- safety validation ------------------------------------------------------------------


def test_run_id_and_ref_validation():
    for bad in ("", "../escape", "-rf", "a/b", "a b", ".hidden", "a..b"):
        with pytest.raises(ValueError):
            validate_run_id(bad)
    assert validate_run_id("run-123_AB") == "run-123_AB"


def test_ensure_rejects_option_like_refs(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    worktrees = GitWorktreeWorkspace(tmp_path / "worktrees")
    with pytest.raises(ValueError):
        worktrees.ensure(repo, "proj", "run-1", "--upload-pack=touch /tmp/x")
    with pytest.raises(ValueError):
        worktrees.worktree_path("../evil", "run-1")


# -- assembly-level hooks -----------------------------------------------------------------


def _artifact(type_: str, **kwargs) -> Artifact:  # noqa: ANN202
    return Artifact(
        id=kwargs.get("id", "art-1"),
        type=type_,
        name=type_.title(),
        version=kwargs.get("version", "1"),
        content=kwargs.get("content"),
        created_by="test-agent",
        created_at=NOW,
        metadata=kwargs.get("metadata", {}),
    )


def test_binding_agent_commits_the_worktree_after_a_passing_test(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    workspace = make_workspace(tmp_path, repo)

    class _FakeTestAgent:
        """Mimics the test agent: applies the change set, reports PASS."""

        def get_metadata(self):  # noqa: ANN202
            raise NotImplementedError

        def validate(self, request):  # noqa: ANN202
            raise NotImplementedError

        def execute(self, request: AgentRequest) -> AgentResult:
            _run_sandbox(
                workspace,
                _changeset(
                    _create("feature.py", "# feature\n"),
                ),
                PASS,
            )
            report = _artifact(
                "TEST_REPORT",
                id="report-1",
                content={
                    "format": "json",
                    "report": {"verdict": "PASS", "summary": "PASS"},
                },
            )
            return AgentResult(
                request_id=request.request_id,
                agent_id="test",
                status="SUCCESS",
                artifacts=[report],
                metrics=RunMetrics(
                    duration_seconds=0.1,
                    revision_count=0,
                    attempt=1,
                ),
            )

    agent = _WorkspaceBindingAgent(_FakeTestAgent(), workspace, role="test")
    code = _artifact(
        "CODE",
        id="code-9",
        version="2",
        metadata={"taskItemId": "T1"},
        content={"format": "json", "changes": []},
    )
    request = AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj",
        workflow_id="software-development",
        agent_id="test",
        input={"taskItemId": "T1", "ref": "main"},
        context={},
        artifacts=[code],
        metadata={"attempt": 1, "runId": "run-e2e"},
    )
    agent.execute(request)
    worktrees = workspace.worktrees
    assert worktrees is not None
    worktree = worktrees.worktree_path("proj", "run-e2e")
    subjects = git(worktree, "log", "--format=%s")
    assert "task item T1" in subjects
    assert "code-9" in subjects and "v2" in subjects
    assert git(worktree, "status", "--porcelain").strip() == ""


def test_service_terminal_hook_fires_on_completion_and_cancel():
    from tests.unit.test_api_service import RoutingGateway

    calls: list[tuple[str, str, str]] = []
    service = FactoryService(
        build_engine(RoutingGateway()),
        projects=PROJECTS,
        metrics=FakeMetrics(),
        clock=lambda: NOW,
        on_run_terminal=lambda *args: calls.append(args),
    )
    try:
        run = service.start_run(
            "task-hook",
            "proj-1",
            inputs={"spec": {"requirement": "Build a calculator"}},
        )
        service.wait_for_drives(timeout=30)
        assert calls == []  # parked at the gate: not terminal
        pending = service.list_approvals()
        assert len(pending) == 1
        service.decide_approval(pending[0]["id"], decision="APPROVE")
        service.wait_for_drives(timeout=30)
        view = service.get_workflow(run.id)
        assert view is not None and view["status"] == "COMPLETED"
        assert (run.id, "proj-1", "COMPLETED") in calls

        run2 = service.start_run(
            "task-hook-2",
            "proj-1",
            inputs={"spec": {"requirement": "Build a calculator"}},
        )
        service.wait_for_drives(timeout=30)
        service.cancel_run(run2.id)
        service.wait_for_drives(timeout=30)
        assert (run2.id, "proj-1", "CANCELLED") in calls
    finally:
        service.shutdown()
