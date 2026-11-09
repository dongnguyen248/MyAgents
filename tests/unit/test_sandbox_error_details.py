"""SANDBOX_ERROR cause details (FIX-3 item 3): every sandbox failure
carries its phase, exception type, errno, command name, working
directory and elapsed time instead of flattening into a generic
message with empty details."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from asf.configuration.platform import RetryPolicySettings
from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.changeset_apply import apply_changeset
from asf.tools.fake import ScriptedSandbox
from asf.tools.local import LocalSandbox, LocalWorkspace, WorkspaceSandbox
from asf.tools.ports import (
    CommandSpec,
    CommandTimeoutError,
    SandboxApplyError,
    SandboxError,
)
from asf.tools.worktree import GitWorktreeWorkspace, WorktreeError

_CREATE = ChangeSet(changes=[FileChange(path="scratch.txt", operation="create", content="x\n")])


def test_apply_modify_missing_carries_its_cause(tmp_path: Path) -> None:
    changes = ChangeSet(
        changes=[FileChange(path="docs/decisions.md", operation="modify", content="v2\n")]
    )
    with pytest.raises(SandboxError) as caught:
        apply_changeset(tmp_path, changes, allow_relabel=False)
    error = caught.value
    assert isinstance(error, SandboxApplyError)
    assert str(error) == "apply failed: cannot modify missing file docs/decisions.md"
    assert error.details["phase"] == "start"
    assert error.details["exceptionType"] == "SandboxApplyError"
    assert error.details["cwd"] == str(tmp_path)
    assert error.details["cwdExists"] is True


def test_apply_into_a_missing_root_is_a_distinct_failure(tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    with pytest.raises(SandboxError) as caught:
        apply_changeset(missing, _CREATE, allow_relabel=True)
    error = caught.value
    assert isinstance(error, SandboxApplyError)
    assert "working directory does not exist" in str(error)
    assert str(missing) in str(error)
    assert "antivirus" in str(error)
    assert error.details["cwdExists"] is False


def test_every_apply_validation_failure_is_an_apply_error(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("base\n", encoding="utf-8")
    cases = [
        ChangeSet(changes=[FileChange(path="app.py", operation="create", content="x\n")]),
        ChangeSet(changes=[FileChange(path="ghost.py", operation="delete", content=None)]),
        ChangeSet(changes=[FileChange(path="../evil.py", operation="create", content="x\n")]),
    ]
    for changes in cases:
        with pytest.raises(SandboxApplyError):
            apply_changeset(tmp_path, changes, allow_relabel=True)


def test_apply_failed_is_not_a_configurable_retry_code() -> None:
    # SANDBOX_APPLY_FAILED is deliberately absent from the valid
    # retryOn set, so a workflow cannot opt back into retrying it.
    with pytest.raises(ValidationError, match="SANDBOX_APPLY_FAILED"):
        RetryPolicySettings(max_attempts=2, retry_on=["SANDBOX_APPLY_FAILED"])


def test_spawn_failure_carries_errno_and_the_command_name_only(
    tmp_path: Path,
) -> None:
    spec = CommandSpec(("no-such-executable-asf", "DO-NOT-LEAK"))
    with pytest.raises(SandboxError) as caught:
        LocalSandbox(tmp_path).run([spec], _CREATE, "main")
    error = caught.value
    assert error.details["phase"] == "start"
    assert error.details["exceptionType"] == "FileNotFoundError"
    assert error.details["errno"] == 2
    assert error.details["commandName"] == "no-such-executable-asf"
    assert error.details["cwd"] == str(tmp_path)
    assert error.details["cwdExists"] is True
    assert error.details["elapsedMs"] >= 0
    assert "DO-NOT-LEAK" not in str(error)
    assert "DO-NOT-LEAK" not in str(error.details)


def test_missing_cwd_at_spawn_is_a_distinct_failure(tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    sandbox = LocalSandbox(missing)
    with pytest.raises(SandboxError) as caught:
        sandbox._run_commands([CommandSpec(("python", "-c", "pass"))])
    error = caught.value
    assert "Working directory does not exist" in str(error)
    assert "antivirus" in str(error)
    assert error.details["phase"] == "start"
    assert error.details["cwdExists"] is False
    assert error.details["commandName"] == "python"


def test_timeout_error_carries_phase_and_command_name() -> None:
    error = CommandTimeoutError(CommandSpec(("pytest", "-q"), timeout_seconds=7))
    assert str(error) == "Command timed out after 7s: pytest"
    assert error.details == {
        "phase": "run",
        "exceptionType": "CommandTimeoutError",
        "commandName": "pytest",
        "elapsedMs": 7000,
    }


def test_worktree_prep_failure_is_a_select_phase_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = LocalWorkspace(
        {"proj": tmp_path / "repo"},
        worktrees=GitWorktreeWorkspace(tmp_path / "worktrees"),
    )

    def fail_current_root(ref: str | None = None) -> Path | None:
        raise WorktreeError("git worktree add failed in repo: fatal: invalid reference")

    monkeypatch.setattr(workspace, "current_root", fail_current_root)
    sandbox = WorkspaceSandbox(workspace, ScriptedSandbox())
    with pytest.raises(SandboxError) as caught:
        sandbox.run([CommandSpec(("python", "-c", "pass"))], _CREATE, "main")
    error = caught.value
    assert "git worktree add failed" in str(error)
    assert error.details["phase"] == "select"
    assert error.details["exceptionType"] == "WorktreeError"
