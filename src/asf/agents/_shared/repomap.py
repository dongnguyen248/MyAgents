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

from asf.tools.ports import RepositoryPort

__all__ = ["build_repo_map"]

MAX_TREE_PATHS = 200
MAX_TREE_DEPTH = 6
MAX_OUTLINE_FILES = 12
MAX_OUTLINE_ENTRIES = 14
_PRUNED_DIRS = {
    "node_modules", ".git", ".hg", "dist", "build", "target",
    "__pycache__", ".venv", "venv", "vendor", ".idea", ".next",
    "coverage", "out", "bin", "obj",
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
    path: str, content: str, tree_set: set[str],
) -> list[str]:
    """Repo paths this file imports directly (best-effort, regex)."""
    found: list[str] = []
    directory = posixpath.dirname(path)
    for line in content.splitlines()[:400]:
        if path.endswith(".py"):
            match = _PY_IMPORT.match(line)
            if match:
                module = (match.group(1) or match.group(2) or "").strip(".")
                if module:
                    base = module.replace(".", "/")
                    for candidate in (f"{base}.py", f"{base}/__init__.py"):
                        if candidate in tree_set:
                            found.append(candidate)
        elif path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs")):
            match = _TS_IMPORT.match(line)
            if match and match.group(1).startswith("."):
                base = posixpath.normpath(
                    posixpath.join(directory, match.group(1)),
                )
                for suffix in ("", ".ts", ".tsx", ".js", "/index.ts", "/index.js"):
                    if base + suffix in tree_set:
                        found.append(base + suffix)
                        break
        elif path.endswith(".java"):
            match = _JAVA_IMPORT.match(line)
            if match:
                candidate = match.group(1).replace(".", "/") + ".java"
                if candidate in tree_set:
                    found.append(candidate)
    return found


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
    try:
        tree = repository.list_tree(ref)
    except Exception:
        return ""
    if not tree:
        return ""
    tree_set = set(tree)
    kept = _kept_paths(tree)

    expected_set = set(expected_files)
    neighbours: list[str] = []
    expected_dirs = {posixpath.dirname(path) for path in expected_files}
    for path in kept:
        if path in expected_set:
            continue
        if posixpath.dirname(path) in expected_dirs:
            neighbours.append(path)
    for path in expected_files:
        if path not in tree_set:
            continue
        try:
            content = repository.read_file(path, ref, max_bytes=65536)
        except Exception:
            continue
        for imported in _imported_paths(path, content, tree_set):
            if imported not in expected_set and imported not in neighbours:
                neighbours.append(imported)
    neighbours = sorted(set(neighbours))[:MAX_OUTLINE_FILES]

    outlines: dict[str, list[str]] = {}
    for path in neighbours:
        try:
            content = repository.read_file(path, ref, max_bytes=65536)
        except Exception:
            continue
        entries = _outline(path, content)
        if entries:
            outlines[path] = entries

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
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n… (repo map truncated)"
    return text
