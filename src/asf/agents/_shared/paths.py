from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asf.tools.changeset import ChangeSet

__all__ = [
    "validate_relative_path",
    "check_denied_paths",
    "check_scope",
    "DENIED_PATH_PATTERNS",
    "ALWAYS_DENIED_EXTENSIONS",
    "ALWAYS_DENIED_PREFIXES",
]


# Patterns for paths that are always denied (even if in expectedFiles)
ALWAYS_DENIED_EXTENSIONS = (".pem", ".key")
ALWAYS_DENIED_PREFIXES = (".env",)

# Patterns for paths denied unless explicitly in expectedFiles
DENIED_PATH_PATTERNS = [
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
    - Not a denied path (unless explicitly allowed by caller)
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

    Args:
        path: The path to check.
        allowed_paths: Set of paths that are explicitly allowed (from expectedFiles).
                       These override the standard denied patterns, but NOT the
                       always-denied extensions/prefixes.

    Returns:
        List of issue strings (empty if not denied or explicitly allowed).
    """
    issues: list[str] = []
    allowed = allowed_paths or set()

    # Always-denied extensions (rejected even if in expectedFiles)
    for ext in ALWAYS_DENIED_EXTENSIONS:
        if path.endswith(ext):
            issues.append(f"path '{path}' has forbidden extension '{ext}' (always denied)")
            return issues

    # Always-denied prefixes (rejected even if in expectedFiles)
    for prefix in ALWAYS_DENIED_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            issues.append(f"path '{path}' has forbidden prefix '{prefix}' (always denied)")
            return issues

    # Standard denied patterns (allowed if in expectedFiles)
    if path in allowed:
        return issues

    for pattern, description in DENIED_PATH_PATTERNS:
        if pattern.search(path):
            issues.append(f"path '{path}' matches denied pattern: {description}")
            break

    return issues


def check_scope(changeset: "ChangeSet", allowed_paths: set[str]) -> list[str]:
    """Check that all changes in a ChangeSet are within allowed paths.

    Args:
        changeset: The ChangeSet to validate.
        allowed_paths: Set of allowed paths from task's expectedFiles.

    Returns:
        List of issue strings for out-of-scope paths.
    """

    issues: list[str] = []
    out_of_scope: list[str] = []

    for fc in changeset.changes:
        # Check scope
        if fc.path not in allowed_paths:
            out_of_scope.append(fc.path)
        # Check denied paths
        issues.extend(check_denied_paths(fc.path, allowed_paths))

    if out_of_scope:
        issues.append(f"out-of-scope paths (not in expectedFiles): {out_of_scope}")

    return issues