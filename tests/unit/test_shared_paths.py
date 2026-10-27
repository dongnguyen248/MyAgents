from __future__ import annotations

import re

from asf.agents._shared.paths import (
    check_denied_paths,
    check_scope,
    validate_relative_path,
)
from asf.tools.changeset import ChangeSet, FileChange


def _taskagent_validate_path(path: str) -> list[str]:
    """Replicate TaskAgent's inline path validation logic for parity testing."""
    issues: list[str] = []
    # relative only, no leading "/"
    if path.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", path):
        issues.append("must be relative (no leading '/' or drive letter)")
    # no backslashes
    if "\\" in path:
        issues.append("must not contain backslashes")
    # no ".." segment
    if ".." in path.split("/"):
        issues.append("must not contain '..' segments")
    # no empty segments or "//"
    if "//" in path or any(seg == "" for seg in path.split("/")):
        issues.append("has empty path segments")
    # no NUL/control characters
    if any(ord(c) < 32 for c in path):
        issues.append("contains control characters")
    return issues


def test_taskagent_parity_valid_paths() -> None:
    valid = ["src/foo.py", "foo/bar/baz.py", "README.md", "a/b/c/d/e.py"]
    for path in valid:
        shared = validate_relative_path(path)
        taskagent = _taskagent_validate_path(path)
        assert shared == [], f"Shared failed for valid {path}: {shared}"
        assert taskagent == [], f"TaskAgent failed for valid {path}: {taskagent}"


def test_taskagent_parity_leading_slash() -> None:
    path = "/absolute/path.py"
    shared = validate_relative_path(path)
    taskagent = _taskagent_validate_path(path)
    assert any("relative" in i or "leading" in i for i in shared)
    assert any("relative" in i or "leading" in i for i in taskagent)


def test_taskagent_parity_drive_letter() -> None:
    path = "C:/path.py"
    shared = validate_relative_path(path)
    taskagent = _taskagent_validate_path(path)
    assert any("drive" in i for i in shared)
    assert any("drive" in i for i in taskagent)


def test_taskagent_parity_backslashes() -> None:
    path = "src\\foo.py"
    shared = validate_relative_path(path)
    taskagent = _taskagent_validate_path(path)
    assert any("backslash" in i for i in shared)
    assert any("backslash" in i for i in taskagent)


def test_taskagent_parity_dotdot() -> None:
    for path in ["src/../foo.py", "../foo.py"]:
        shared = validate_relative_path(path)
        taskagent = _taskagent_validate_path(path)
        assert any(".." in i for i in shared)
        assert any(".." in i for i in taskagent)


def test_taskagent_parity_empty_segments() -> None:
    for path in ["src//foo.py", "src/", "/src/foo.py"]:
        shared = validate_relative_path(path)
        taskagent = _taskagent_validate_path(path)
        assert any("empty" in i for i in shared)
        assert any("empty" in i for i in taskagent)


def test_taskagent_parity_control_chars() -> None:
    for path in ["src/\x00foo.py", "src/\nfoo.py"]:
        shared = validate_relative_path(path)
        taskagent = _taskagent_validate_path(path)
        assert any("control" in i for i in shared)
        assert any("control" in i for i in taskagent)


def test_validate_relative_path_valid_paths() -> None:
    valid = [
        "src/foo.py",
        "foo/bar/baz.py",
        "README.md",
        "a/b/c/d/e.py",
    ]
    for path in valid:
        assert validate_relative_path(path) == [], f"Failed for {path}"


def test_validate_relative_path_empty_path() -> None:
    assert validate_relative_path("") == ["path must not be empty"]


def test_validate_relative_path_leading_slash() -> None:
    assert validate_relative_path("/absolute/path.py") == [
        "path must be relative (no leading '/')",
        "path must not have empty segments",
    ]


def test_validate_relative_path_drive_letter() -> None:
    assert validate_relative_path("C:/path.py") == ["path must not contain drive letters"]
    assert validate_relative_path("C:\\path.py") == [
        "path must not contain drive letters",
        "path must not contain backslashes",
    ]


def test_validate_relative_path_backslashes() -> None:
    assert validate_relative_path("src\\foo.py") == ["path must not contain backslashes"]


def test_validate_relative_path_dotdot_segments() -> None:
    assert validate_relative_path("src/../foo.py") == ["path must not contain '..' segments"]
    assert validate_relative_path("../foo.py") == ["path must not contain '..' segments"]


def test_validate_relative_path_empty_segments() -> None:
    assert validate_relative_path("src//foo.py") == ["path must not have empty segments"]
    assert validate_relative_path("src/") == ["path must not have empty segments"]
    assert validate_relative_path("/src/foo.py") == [
        "path must be relative (no leading '/')",
        "path must not have empty segments",
    ]


def test_validate_relative_path_control_characters() -> None:
    assert validate_relative_path("src/\x00foo.py") == ["path contains control characters"]
    assert validate_relative_path("src/\nfoo.py") == ["path contains control characters"]


def test_check_denied_paths_allowed_path() -> None:
    allowed = {"src/foo.py", "README.md"}
    assert check_denied_paths("src/foo.py", allowed) == []


def test_check_denied_paths_denied_git_directory() -> None:
    allowed = {"src/foo.py"}
    issues = check_denied_paths(".git/config", allowed)
    assert len(issues) == 1
    assert "denied pattern" in issues[0]


def test_check_denied_paths_denied_github_directory() -> None:
    allowed = {"src/foo.py"}
    issues = check_denied_paths(".github/workflows/ci.yml", allowed)
    assert len(issues) == 1
    assert "denied pattern" in issues[0]


def test_check_denied_paths_denied_lock_files() -> None:
    allowed = {"src/foo.py"}
    for lock_file in [
        "package-lock.json",
        "pnpm-lock.yaml",
        "poetry.lock",
        "Cargo.lock",
        "yarn.lock",
    ]:
        issues = check_denied_paths(lock_file, allowed)
        assert len(issues) == 1, f"Failed for {lock_file}"


def test_check_denied_paths_denied_gitlab_ci() -> None:
    allowed = {"src/foo.py"}
    issues = check_denied_paths(".gitlab-ci.yml", allowed)
    assert len(issues) == 1


def test_check_denied_paths_denied_jenkinsfile() -> None:
    allowed = {"src/foo.py"}
    issues = check_denied_paths("Jenkinsfile", allowed)
    assert len(issues) == 1


def test_check_denied_paths_allowed_override_denied() -> None:
    allowed = {"package-lock.json"}
    assert check_denied_paths("package-lock.json", allowed) == []


def test_check_denied_paths_always_denied_extensions() -> None:
    allowed = {"secret.pem", "key.key"}
    for path in ["secret.pem", "path/to/key.key"]:
        issues = check_denied_paths(path, allowed)
        assert len(issues) == 1
        assert "always denied" in issues[0]


def test_check_denied_paths_always_denied_prefixes() -> None:
    allowed = {".env", ".env/production"}
    for path in [".env", ".env/production", ".env/local"]:
        issues = check_denied_paths(path, allowed)
        assert len(issues) == 1
        assert "always denied" in issues[0]


def test_check_scope_in_scope() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path="src/a.py", operation="create", content="a"),
        FileChange(path="src/b.py", operation="modify", content="b"),
    ))
    allowed = {"src/a.py", "src/b.py", "src/c.py"}
    assert check_scope(changeset, allowed) == []


def test_check_scope_out_of_scope() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path="src/a.py", operation="create", content="a"),
        FileChange(path="src/unauthorized.py", operation="create", content="b"),
    ))
    allowed = {"src/a.py"}
    issues = check_scope(changeset, allowed)
    assert len(issues) == 1
    assert "out-of-scope" in issues[0]
    assert "unauthorized.py" in issues[0]


def test_check_scope_multiple_out_of_scope() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path="src/a.py", operation="create", content="a"),
        FileChange(path="src/b.py", operation="create", content="b"),
        FileChange(path="src/c.py", operation="create", content="c"),
    ))
    allowed = {"src/a.py"}
    issues = check_scope(changeset, allowed)
    assert len(issues) == 1
    assert "b.py" in issues[0]
    assert "c.py" in issues[0]


def test_check_scope_denied_path_in_changeset() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path=".git/config", operation="create", content="x"),
    ))
    allowed = {".git/config"}
    issues = check_scope(changeset, allowed)
    assert issues == []

    changeset2 = ChangeSet(changes=(
        FileChange(path=".git/config", operation="create", content="x"),
    ))
    allowed2 = {"src/foo.py"}
    issues2 = check_scope(changeset2, allowed2)
    assert len(issues2) == 2
    assert any("denied pattern" in i for i in issues2)
    assert any("out-of-scope" in i for i in issues2)