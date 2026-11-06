"""A bounded map of the repository for code-generating agents.

Implement/Fix used to see ONLY the expected files' contents: no
directory tree, no neighbouring APIs, so models invented imports
and helper signatures. The repo map gives them, within a hard
character budget:

- the repository tree (paths only, depth- and count-capped,
  vendor/build directories pruned);
- OUTLINES (class/function names and signatures, never bodies)
  for the files that matter: neighbours sharing a directory with
  an expected file, and repo files an expected file imports
  directly (simple per-language import regexes for Python,
  TypeScript/JavaScript and Java).

Pure with respect to the repository port: reads go through
``RepositoryPort`` only, and import resolution only ever names
paths that ``list_tree`` returned — the map can never read
outside the repository.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from asf.tools.ports import RepositoryPort

__all__ = ["build_repo_map"]

MAX_TREE_PATHS = 200
MAX_TREE_DEPTH = 6
MAX_OUTLINE_FILES = 12
MAX_OUTLINE_ENTRIES = 14
MAX_IMPORT_LINES = 400
READ_MAX_BYTES = 65536
_PRUNED_DIRS = {
    "node_modules",
    ".git",
    ".hg",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".venv",
    "venv",
    "vendor",
    ".idea",
    ".next",
    "coverage",
    "out",
    "bin",
    "obj",
}

_PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))")
_TS_IMPORT = re.compile(r"""^\s*(?:import|export)\s+(?:[^'\"]*\sfrom\s+)?['\"]([^'\"]+)['\"]""")
_JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w\.]+);")

_PY_DEF = re.compile(r"^(?:async\s+def|def|class)\s+[^\n(]*\(?[^\n]*")
_PY_DEF_INDENTED = re.compile(r"^    (?:async\s+def|def)\s+[^\n(]*\(")
_TS_DEF = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?"
    r"(?:class|interface|function|enum)\s+[^\n{]*",
)
_TS_ARROW = re.compile(r"^(?:export\s+)?(?:const|let)\s+\w+\s*=\s*(?:async\s*)?\([^\n]*\)\s*=>")
_JAVA_TYPE = re.compile(
    r"^(?:public\s+|final\s+|abstract\s+)*"
    r"(?:class|interface|enum|record)\s+[^\n{]*",
)
_JAVA_METHOD = re.compile(
    r"^    (?:public|protected|private)\s+[^\n(]*\([^\n]*\)\s*(?:throws\s+[\w,\s]+)?\{?\s*$",
)


def _kept_paths(tree: tuple[str, ...]) -> list[str]:
    kept: list[str] = []
    for path in tree:
        parts = path.split("/")
        if any(part in _PRUNED_DIRS for part in parts[:-1]):
            continue
        if len(parts) > MAX_TREE_DEPTH:
            continue
        kept.append(path)
    return sorted(kept)


def _imported_paths(
    path: str,
    content: str,
    tree_set: set[str],
) -> list[str]:
    """Repo paths this file imports directly (best-effort, regex)."""
    directory = posixpath.dirname(path)
    found: list[str] = []
    for line in content.splitlines()[:MAX_IMPORT_LINES]:
        found.extend(_line_imports(path, line, directory, tree_set))
    return found


def _line_imports(path: str, line: str, directory: str, tree_set: set[str]) -> list[str]:
    if path.endswith(".py"):
        return _python_imports(line, tree_set)
    if path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs")):
        return _typescript_imports(line, directory, tree_set)
    if path.endswith(".java"):
        return _java_imports(line, tree_set)
    return []


def _python_imports(line: str, tree_set: set[str]) -> list[str]:
    match = _PY_IMPORT.match(line)
    if not match:
        return []
    module = (match.group(1) or match.group(2) or "").strip(".")
    if not module:
        return []
    base = module.replace(".", "/")
    candidates = (f"{base}.py", f"{base}/__init__.py")
    return [candidate for candidate in candidates if candidate in tree_set]


def _typescript_imports(line: str, directory: str, tree_set: set[str]) -> list[str]:
    match = _TS_IMPORT.match(line)
    if not match or not match.group(1).startswith("."):
        return []
    base = posixpath.normpath(posixpath.join(directory, match.group(1)))
    for suffix in ("", ".ts", ".tsx", ".js", "/index.ts", "/index.js"):
        if base + suffix in tree_set:
            return [base + suffix]
    return []


def _java_imports(line: str, tree_set: set[str]) -> list[str]:
    match = _JAVA_IMPORT.match(line)
    if not match:
        return []
    candidate = match.group(1).replace(".", "/") + ".java"
    return [candidate] if candidate in tree_set else []


def _outline(path: str, content: str) -> list[str]:
    entries: list[str] = []
    if path.endswith(".py"):
        patterns = (_PY_DEF, _PY_DEF_INDENTED)
    elif path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs")):
        patterns = (_TS_DEF, _TS_ARROW)
    elif path.endswith(".java"):
        patterns = (_JAVA_TYPE, _JAVA_METHOD)
    else:
        return entries
    for line in content.splitlines():
        stripped = line.rstrip()
        if any(pattern.match(stripped) for pattern in patterns):
            entries.append(stripped.strip()[:160])
            if len(entries) >= MAX_OUTLINE_ENTRIES:
                break
    return entries


def build_repo_map(
    repository: RepositoryPort,
    *,
    ref: str,
    expected_files: list[str],
    max_chars: int = 6000,
) -> str:
    """Builds the <<<REPO MAP>>> body ('' when there is nothing)."""
    if max_chars <= 0:
        return ""
    tree = _tree(repository, ref)
    if not tree:
        return ""
    kept = _kept_paths(tree)
    scan = _RepoScan(
        repository=repository,
        ref=ref,
        tree_set=set(tree),
        expected_set=set(expected_files),
    )
    neighbours = _neighbour_paths(scan, kept, expected_files)
    outlines = _outlines(scan, neighbours)
    text = _render_map(kept, outlines)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n… (repo map truncated)"
    return text


def _tree(repository: RepositoryPort, ref: str) -> tuple[str, ...]:
    try:
        return repository.list_tree(ref)
    except Exception:
        return ()


@dataclass(frozen=True)
class _RepoScan:
    repository: RepositoryPort
    ref: str
    tree_set: set[str]
    expected_set: set[str]


def _neighbour_paths(scan: _RepoScan, kept: list[str], expected_files: list[str]) -> list[str]:
    expected_dirs = {posixpath.dirname(path) for path in expected_files}
    neighbours = [
        path
        for path in kept
        if path not in scan.expected_set and posixpath.dirname(path) in expected_dirs
    ]
    for path in expected_files:
        neighbours.extend(_imports_of(scan, path, neighbours))
    return sorted(set(neighbours))[:MAX_OUTLINE_FILES]


def _imports_of(scan: _RepoScan, path: str, neighbours: list[str]) -> list[str]:
    if path not in scan.tree_set:
        return []
    try:
        content = scan.repository.read_file(path, scan.ref, max_bytes=READ_MAX_BYTES)
    except Exception:
        return []
    return [
        imported
        for imported in _imported_paths(path, content, scan.tree_set)
        if imported not in scan.expected_set and imported not in neighbours
    ]


def _outlines(scan: _RepoScan, neighbours: list[str]) -> dict[str, list[str]]:
    outlines: dict[str, list[str]] = {}
    for path in neighbours:
        try:
            content = scan.repository.read_file(path, scan.ref, max_bytes=READ_MAX_BYTES)
        except Exception:
            continue
        entries = _outline(path, content)
        if entries:
            outlines[path] = entries
    return outlines


def _render_map(kept: list[str], outlines: dict[str, list[str]]) -> str:
    lines: list[str] = ["Files in the repository:"]
    shown = kept[:MAX_TREE_PATHS]
    lines.extend(f"- {path}" for path in shown)
    if len(kept) > len(shown):
        lines.append(f"- … and {len(kept) - len(shown)} more files")
    if outlines:
        lines.append("")
        lines.append("Outlines of neighbouring files (signatures only):")
        for path in sorted(outlines):
            lines.append(f"## {path}")
            lines.extend(f"- {entry}" for entry in outlines[path])
    return "\n".join(lines)
