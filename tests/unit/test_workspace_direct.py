"""Direct workspace mode: journaled edits of the project folder itself.

Covers git and non-git folders, the fix loop's re-apply, the run-end
policies (FAILED/CANCELLED revert, COMPLETED keep, keepChangesOnFailure),
the no-clobber rule, the startup sweep, per-project mode switching, and
the profile/service surface of repository.workspaceMode.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from asf.api.service import FactoryService
from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.fake import ScriptedSandbox
from asf.tools.journal import JournalStore
from asf.tools.local import (
    DirectWorkspace,
    LocalWorkspace,
    ProjectWorkspaceSettings,
    WorkspaceSandbox,
)
from asf.tools.ports import CommandSpec, SandboxError
from asf.tools.worktree import GitWorktreeWorkspace
from tests.unit.test_api_service import PROJECTS, FakeMetrics
from tests.unit.test_workspace_concurrency import build_engine

PYTHON = sys.executable
PASS = "pass"


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


def _changeset(*changes: FileChange) -> ChangeSet:
    return ChangeSet(changes=list(changes))


def _create(path: str, content: str) -> FileChange:
    return FileChange(path=path, operation="create", content=content)


def _modify(path: str, content: str) -> FileChange:
    return FileChange(path=path, operation="modify", content=content)


def make_workspace(
    tmp_path: Path,
    roots: dict[str, Path],
    settings: dict[str, ProjectWorkspaceSettings] | None = None,
) -> LocalWorkspace:
    return LocalWorkspace(
        roots,
        worktrees=GitWorktreeWorkspace(tmp_path / "worktrees"),
        direct=DirectWorkspace(
            journals=JournalStore(tmp_path / "journals"),
            settings=settings or {},
        ),
    )


@contextmanager
def bound(workspace: LocalWorkspace, project_id: str, run_id: str) -> Iterator[None]:
    token = workspace.bind(project_id, run_id)
    try:
        yield
    finally:
        workspace.reset_binding(token)


def apply_changes(
    workspace: LocalWorkspace,
    project_id: str,
    run_id: str,
    changes: ChangeSet,
) -> None:
    sandbox = WorkspaceSandbox(workspace, ScriptedSandbox())
    with bound(workspace, project_id, run_id):
        sandbox.run([CommandSpec(argv=(PYTHON, "-c", PASS))], changes, "main")


DIRECT = {"proj": ProjectWorkspaceSettings(mode="direct")}


# -- direct writes and run-end policies --------------------------------------


def test_direct_non_git_writes_then_failed_run_reverts(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a.txt").write_text("old", encoding="utf-8")
    workspace = make_workspace(tmp_path, {"proj": folder}, DIRECT)

    apply_changes(
        workspace,
        "proj",
        "run-1",
        _changeset(_modify("a.txt", "new"), _create("b.txt", "created")),
    )
    assert (folder / "a.txt").read_text(encoding="utf-8") == "new"
    assert (folder / "b.txt").read_text(encoding="utf-8") == "created"

    outcome = workspace.finish_run("proj", "run-1", "FAILED")
    assert outcome is not None and outcome.journal_state == "reverted"
    assert outcome.files_written == ("a.txt", "b.txt")
    assert (folder / "a.txt").read_text(encoding="utf-8") == "old"
    assert not (folder / "b.txt").exists()
    # Idempotent: a second terminal call closes nothing again.
    assert workspace.finish_run("proj", "run-1", "FAILED") is None


def test_direct_completed_run_keeps_files_and_discards_journal(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    workspace = make_workspace(tmp_path, {"proj": folder}, DIRECT)
    apply_changes(workspace, "proj", "run-1", _changeset(_create("b.txt", "created")))

    outcome = workspace.finish_run("proj", "run-1", "COMPLETED")

    assert outcome is not None and outcome.journal_state == "kept"
    assert (folder / "b.txt").read_text(encoding="utf-8") == "created"
    assert workspace.journal_for("proj", "run-1") is None


def test_direct_cancelled_run_reverts_like_failed(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    workspace = make_workspace(tmp_path, {"proj": folder}, DIRECT)
    apply_changes(workspace, "proj", "run-1", _changeset(_create("b.txt", "created")))

    outcome = workspace.finish_run("proj", "run-1", "CANCELLED")

    assert outcome is not None and outcome.journal_state == "reverted"
    assert not (folder / "b.txt").exists()


def test_direct_keep_changes_on_failure_leaves_files(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    settings = {"proj": ProjectWorkspaceSettings(mode="direct", keep_changes_on_failure=True)}
    workspace = make_workspace(tmp_path, {"proj": folder}, settings)
    apply_changes(workspace, "proj", "run-1", _changeset(_create("b.txt", "created")))

    outcome = workspace.finish_run("proj", "run-1", "FAILED")

    assert outcome is not None and outcome.journal_state == "kept"
    assert (folder / "b.txt").read_text(encoding="utf-8") == "created"
    journal = workspace.journal_for("proj", "run-1")
    assert journal is not None and journal.state == "kept"


# -- the fix loop --------------------------------------------------------------


def test_direct_fix_loop_replacement_reapplies_after_revert(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    workspace = make_workspace(tmp_path, {"proj": folder}, DIRECT)
    apply_changes(workspace, "proj", "run-1", _changeset(_create("fix.py", "v1 broken")))
    # The replacement CODE is again a create of the same path: without
    # the journal revert it would fail as "create existing".
    apply_changes(workspace, "proj", "run-1", _changeset(_create("fix.py", "v2 fixed")))
    assert (folder / "fix.py").read_text(encoding="utf-8") == "v2 fixed"


def test_direct_fix_after_pass_lands_on_the_green_state(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "app.py").write_text("v0", encoding="utf-8")
    workspace = make_workspace(tmp_path, {"proj": folder}, DIRECT)
    apply_changes(workspace, "proj", "run-1", _changeset(_modify("app.py", "v1 green")))
    with bound(workspace, "proj", "run-1"):
        workspace.record_green_state("tests passed")
    apply_changes(workspace, "proj", "run-1", _changeset(_modify("app.py", "v2 broken")))

    outcome = workspace.finish_run("proj", "run-1", "FAILED")

    assert outcome is not None and outcome.journal_state == "reverted"
    assert (folder / "app.py").read_text(encoding="utf-8") == "v1 green"


# -- no clobbering ---------------------------------------------------------------


def test_direct_revert_reports_and_keeps_user_edits(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a.txt").write_text("old", encoding="utf-8")
    workspace = make_workspace(tmp_path, {"proj": folder}, DIRECT)
    apply_changes(workspace, "proj", "run-1", _changeset(_modify("a.txt", "asf version")))
    (folder / "a.txt").write_text("user version", encoding="utf-8")

    outcome = workspace.finish_run("proj", "run-1", "FAILED")

    assert outcome is not None and outcome.journal_state == "conflict"
    assert outcome.conflicts == ("a.txt",)
    assert (folder / "a.txt").read_text(encoding="utf-8") == "user version"
    view = workspace.run_workspace_view("proj", "run-1")
    assert view is not None and view["journalState"] == "conflict"
    assert view["conflicts"] == ["a.txt"]


# -- git folders -------------------------------------------------------------------


def test_direct_git_folder_writes_in_place_not_in_a_worktree(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    workspace = make_workspace(tmp_path, {"proj": repo}, DIRECT)

    apply_changes(workspace, "proj", "run-1", _changeset(_modify("app.py", "VALUE = 'new'\n")))

    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 'new'\n"
    worktrees = workspace.worktrees
    assert worktrees is not None and not worktrees.has_worktree("proj", "run-1")
    # Nothing was committed: the change is a plain working-tree edit.
    assert " M app.py" in git(repo, "status", "--porcelain")


def test_direct_git_refuses_uncommitted_changes_on_touched_files(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / "app.py").write_text("VALUE = 'user work'\n", encoding="utf-8")
    (repo / "other.py").write_text("untouched dirty\n", encoding="utf-8")
    workspace = make_workspace(tmp_path, {"proj": repo}, DIRECT)

    with pytest.raises(SandboxError, match="app.py"):
        apply_changes(
            workspace,
            "proj",
            "run-1",
            _changeset(_modify("app.py", "VALUE = 'asf'\n")),
        )
    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 'user work'\n"

    # A dirty file the change set does not touch does not block the run.
    apply_changes(workspace, "proj", "run-2", _changeset(_create("new.py", "# new\n")))
    assert (repo / "new.py").read_text(encoding="utf-8") == "# new\n"


def test_direct_git_refuses_to_overwrite_an_untracked_file(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / "draft.py").write_text("# user draft\n", encoding="utf-8")
    workspace = make_workspace(tmp_path, {"proj": repo}, DIRECT)

    with pytest.raises(SandboxError, match="draft.py"):
        apply_changes(workspace, "proj", "run-1", _changeset(_create("draft.py", "# asf\n")))
    assert (repo / "draft.py").read_text(encoding="utf-8") == "# user draft\n"


# -- startup sweep -------------------------------------------------------------------


def test_sweep_reverts_journal_of_unknown_run_and_spares_live_ones(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    workspace = make_workspace(tmp_path, {"proj": folder}, DIRECT)
    apply_changes(workspace, "proj", "run-dead", _changeset(_create("b.txt", "x")))
    apply_changes(workspace, "proj", "run-live", _changeset(_create("c.txt", "y")))

    outcomes = workspace.sweep_journals(lambda run_id: None if run_id == "run-dead" else "ACTIVE")

    assert [item.run_id for item in outcomes] == ["run-dead"]
    assert not (folder / "b.txt").exists()
    assert (folder / "c.txt").read_text(encoding="utf-8") == "y"


def test_sweep_keeps_journal_when_project_keeps_changes_on_failure(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    settings = {"proj": ProjectWorkspaceSettings(mode="direct", keep_changes_on_failure=True)}
    workspace = make_workspace(tmp_path, {"proj": folder}, settings)
    apply_changes(workspace, "proj", "run-1", _changeset(_create("b.txt", "x")))

    outcomes = workspace.sweep_journals(lambda run_id: "FAILED")

    assert len(outcomes) == 1 and outcomes[0].journal_state == "kept"
    assert (folder / "b.txt").read_text(encoding="utf-8") == "x"


# -- per-project mode switching ---------------------------------------------------


def test_modes_are_per_project_within_one_workspace(tmp_path: Path):
    auto_repo = make_repo(tmp_path / "auto-repo")
    direct_repo = make_repo(tmp_path / "direct-repo")
    workspace = make_workspace(
        tmp_path,
        {"auto-proj": auto_repo, "direct-proj": direct_repo},
        {"direct-proj": ProjectWorkspaceSettings(mode="direct")},
    )

    apply_changes(
        workspace,
        "auto-proj",
        "run-1",
        _changeset(_modify("app.py", "VALUE = 'wt'\n")),
    )
    apply_changes(
        workspace,
        "direct-proj",
        "run-1",
        _changeset(_modify("app.py", "VALUE = 'direct'\n")),
    )

    # Auto (git) project: isolated worktree, user tree pristine.
    assert (auto_repo / "app.py").read_text(encoding="utf-8") == "VALUE = 'base'\n"
    worktrees = workspace.worktrees
    assert worktrees is not None and worktrees.has_worktree("auto-proj", "run-1")
    # Direct project: the folder itself carries the edit.
    assert (direct_repo / "app.py").read_text(encoding="utf-8") == "VALUE = 'direct'\n"


def test_worktree_mode_on_a_non_git_folder_falls_back_to_the_journal(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    settings = {"proj": ProjectWorkspaceSettings(mode="worktree")}
    workspace = make_workspace(tmp_path, {"proj": folder}, settings)
    apply_changes(workspace, "proj", "run-1", _changeset(_create("b.txt", "x")))

    outcome = workspace.finish_run("proj", "run-1", "FAILED")

    assert outcome is not None and outcome.journal_state == "reverted"
    assert not (folder / "b.txt").exists()


# -- profile + service surface ---------------------------------------------------


def _service() -> FactoryService:
    from tests.unit.test_api_service import RoutingGateway

    return FactoryService(
        build_engine(RoutingGateway()),
        projects=PROJECTS,
        metrics=FakeMetrics(),
    )


def _payload(**repository: object) -> dict:
    return {
        "id": "ws-proj",
        "name": "WS Proj",
        "repository": {"provider": "git", **repository},
        "technology": {"backend": ["python"]},
        "workflow": "software-development",
    }


def test_create_project_defaults_to_direct_mode():
    service = _service()
    try:
        view = service.create_project(_payload(path="/srv/ws"))
        assert view["workspaceMode"] == "direct"
        assert view["keepChangesOnFailure"] is False
        stored = service._project_profiles["ws-proj"]
        assert stored["repository"]["workspaceMode"] == "direct"
    finally:
        service.shutdown()


def test_create_project_rejects_an_unknown_workspace_mode():
    service = _service()
    try:
        with pytest.raises(ValueError, match="workspaceMode"):
            service.create_project(_payload(workspaceMode="sideways"))
        with pytest.raises(ValueError, match="keepChangesOnFailure"):
            service.create_project(_payload(keepChangesOnFailure="yes"))
    finally:
        service.shutdown()


def test_update_project_preserves_mode_the_payload_does_not_resend():
    service = _service()
    try:
        service.create_project(_payload(workspaceMode="worktree"))
        view = service.update_project("ws-proj", {"name": "Renamed"})
        assert view["workspaceMode"] == "worktree"
    finally:
        service.shutdown()


def test_workflow_view_carries_the_workspace_block():
    from tests.unit.test_api_service import RoutingGateway

    block = {
        "mode": "direct",
        "configuredMode": "direct",
        "folderPath": "/srv/ws",
        "filesWritten": ["a.txt"],
        "journalState": "active",
        "conflicts": [],
        "keepChangesOnFailure": False,
    }
    service = FactoryService(
        build_engine(RoutingGateway()),
        projects=PROJECTS,
        metrics=FakeMetrics(),
        workspace_view=lambda project_id, run_id: block,
    )
    try:
        run = service.start_run(
            "task-ws",
            "proj-1",
            inputs={"spec": {"requirement": "Build a calculator"}},
        )
        view = service.get_workflow(run.id)
        assert view is not None and view["workspace"] == block
    finally:
        service.shutdown()
