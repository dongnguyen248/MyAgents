from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asf.tools.changeset import ChangeSet

__all__ = [
    "validate_relative_path",
    "check_denied_paths",
    "check_scope",
    "find_out_of_scope",
    "DENIED_PATH_PATTERNS",
    "ALWAYS_DENIED_EXTENSIONS",
    "ALWAYS_DENIED_PREFIXES",
]


# Patterns for paths that are always denied (even if in expectedFiles)
ALWAYS_DENIED_EXTENSIONS = (".pem", ".key")
# ".env*" means any path whose BASENAME starts with ".env"
# Per D9: ".env", ".env.local", "config/.env.production", ".envrc", ".env.example"
ALWAYS_DENIED_PREFIXES = (".env",)

# Patterns for paths that are always denied (rejected even if in expectedFiles)
# Per D9: ".git/", ".github/", ".gitlab-ci.yml", "Jenkinsfile",
# "package-lock.json", "poetry.lock", "Cargo.lock", "pnpm-lock.yaml", "yarn.lock"
ALWAYS_DENIED_PATTERNS = [
    (re.compile(r"(^|/)\.git(/|$)"), ".git directory"),
    (re.compile(r"(^|/)\.github(/|$)"), ".github directory"),
    (re.compile(r"\.gitlab-ci\.yml$"), "GitLab CI config"),
    (re.compile(r"Jenkinsfile$"), "Jenkinsfile"),
    (re.compile(r"package-lock\.json$"), "npm lock file"),
    (re.compile(r"pnpm-lock\.yaml$"), "pnpm lock file"),
    (re.compile(r"poetry\.lock$"), "poetry lock file"),
    (re.compile(r"Cargo\.lock$"), "Cargo lock file"),
    (re.compile(r"yarn\.lock$"), "yarn lock file"),
]

# Legacy alias for compatibility
DENIED_PATH_PATTERNS = ALWAYS_DENIED_PATTERNS


def validate_relative_path(path: str) -> list[str]:
    """Validate a path follows the expectedFiles rules.

    Returns a list of issue strings (empty if valid).
    Rules:
    - Relative POSIX path (no leading "/")
    - No drive letters (e.g., "C:")
    - No ".." segments
    - No backslashes
    - No empty segments or "//"
    - No NUL or control characters (except newline in content, not paths)
    - Not a denied path
    """
    issues: list[str] = []

    if not path:
        issues.append("path must not be empty")
        return issues

    # No leading "/"
    if path.startswith("/"):
        issues.append("path must be relative (no leading '/')")

    # No drive letters
    if re.match(r"^[A-Za-z]:[/\\]", path):
        issues.append("path must not contain drive letters")

    # No backslashes
    if "\\" in path:
        issues.append("path must not contain backslashes")

    # No ".." segments
    segments = path.split("/")
    if ".." in segments:
        issues.append("path must not contain '..' segments")

    # No empty segments or "//"
    if "//" in path or any(seg == "" for seg in segments):
        issues.append("path must not have empty segments")

    # No NUL or control characters
    if any(ord(c) < 32 for c in path):
        issues.append("path contains control characters")

    return issues


def check_denied_paths(path: str, allowed_paths: set[str] | None = None) -> list[str]:
    """Check if a path is in the denied list.

    Per D9: Denied paths are ALWAYS rejected, even if listed in expectedFiles.
    The allowed_paths parameter is kept for signature compatibility but does NOT
    relax any denial checks.

    Args:
        path: The path to check.
        allowed_paths: Set of paths that are explicitly allowed (from expectedFiles).
                       Kept for compatibility; does NOT override denials.

    Returns:
        List of issue strings (empty if not denied).
    """
    issues: list[str] = []
    # allowed_paths is intentionally ignored per D9 - denied paths are always rejected

    # Always-denied extensions (rejected even if in expectedFiles)
    # Case-insensitive match on basename suffix
    basename = path.split("/")[-1]
    for ext in ALWAYS_DENIED_EXTENSIONS:
        if basename.lower().endswith(ext.lower()):
            issues.append(f"path '{path}' has forbidden extension '{ext}' (always denied)")
            return issues

    # Always-denied prefixes (rejected even if in expectedFiles)
    # ".env*" means any path whose basename starts with ".env"
    for prefix in ALWAYS_DENIED_PREFIXES:
        if basename.startswith(prefix):
            issues.append(f"path '{path}' has forbidden prefix '{prefix}*' (always denied)")
            return issues

    # Always-denied patterns (rejected even if in expectedFiles per D9)
    for pattern, description in ALWAYS_DENIED_PATTERNS:
        if pattern.search(path):
            issues.append(f"path '{path}' matches denied pattern: {description} (always denied)")
            break

    return issues


def find_out_of_scope(changeset: "ChangeSet", allowed_paths: set[str]) -> list[str]:
    """Find paths in changeset that are not in allowed_paths.

    This is a structural helper that returns plain paths (no message parsing needed).

    Args:
        changeset: The ChangeSet to validate.
        allowed_paths: Set of allowed paths from task's expectedFiles.

    Returns:
        List of out-of-scope paths (empty if all in scope).
    """
    out_of_scope: list[str] = []
    for fc in changeset.changes:
        if fc.path not in allowed_paths:
            out_of_scope.append(fc.path)
    return out_of_scope


def check_scope(changeset: "ChangeSet", allowed_paths: set[str]) -> list[str]:
    """Check that all changes in a ChangeSet are within allowed paths.

    Per D9: Denied paths are reported separately from out-of-scope paths.
    Both checks are performed and all issues are returned.

    Args:
        changeset: The ChangeSet to validate.
        allowed_paths: Set of allowed paths from task's expectedFiles.

    Returns:
        List of issue strings for out-of-scope and denied paths.
    """

    issues: list[str] = []

    # Check out-of-scope paths (structural helper)
    out_of_scope = find_out_of_scope(changeset, allowed_paths)
    if out_of_scope:
        issues.append(f"out-of-scope paths (not in expectedFiles): {out_of_scope}")

    # Check denied paths (always checked, never relaxed by allowed_paths)
    for fc in changeset.changes:
        issues.extend(check_denied_paths(fc.path, None))

    return issues