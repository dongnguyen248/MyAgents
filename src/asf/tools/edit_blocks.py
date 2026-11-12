"""SEARCH/REPLACE edit blocks: the low-token code output format.

The JSON ChangeSet format makes the model re-emit every modified
file in full, inside a JSON string: a 3-line fix in a 1000-line
file costs the whole file in output tokens, risks JSON escaping
errors, and risks being cut by the output token limit. Edit
blocks only carry the changed regions:

    FILE: src/app.py
    <<<<<<< SEARCH
    (exact original text, verbatim)
    =======
    (replacement text)
    >>>>>>> REPLACE

    CREATE: src/new_module.py
    <<<<<<< FILE
    (the new file's complete content)
    >>>>>>> FILE

    DELETE: src/old_module.py

Grammar rules (strict — anything else is an EditBlockError):

- sections start with ``FILE: <path>`` (modify an existing file),
  ``CREATE: <path>`` (new file, followed by exactly one FILE
  block), or ``DELETE: <path>`` (a single line, no block);
- a FILE section holds one or more SEARCH/REPLACE blocks, applied
  in order, each against the result of the previous one;
- a SEARCH text must occur EXACTLY ONCE in the file's current
  content — zero or multiple matches are errors naming the file
  and the match count, because guessing which occurrence the
  model meant is how files get corrupted;
- the file's line endings are preserved: a CRLF file is matched
  and rewritten in CRLF even though the model writes LF blocks;
- paths are validated like everywhere else (relative POSIX, no
  traversal) and, when an expected-file list is given, must be on
  it.

The parser's output is a full-content :class:`ChangeSet` — the
exact shape the JSON format produces — so review, test, sandbox,
traceability and rendering downstream never see a difference.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping

from asf.tools.changeset import ChangeSet, FileChange

__all__ = ["BLOCKS_FORMAT_INSTRUCTIONS", "EditBlockError", "parse_edit_blocks"]

SEARCH_MARKER = "<<<<<<< SEARCH"
SEPARATOR = "======="
REPLACE_MARKER = ">>>>>>> REPLACE"
FILE_MARKER = "<<<<<<< FILE"
FILE_END_MARKER = ">>>>>>> FILE"

BLOCKS_FORMAT_INSTRUCTIONS = """Reply with edit blocks ONLY — no prose, no JSON, no code fences.

To MODIFY an existing file, write a FILE section with one or more
SEARCH/REPLACE blocks. The SEARCH text must be copied EXACTLY from
the file content shown (it must match one single place in the
file); the REPLACE text is what takes its place:

FILE: path/to/file.py
<<<<<<< SEARCH
def add(a, b):
    return a + b
=======
def add(a, b):
    return a + b  # sum of the two operands
>>>>>>> REPLACE

To CREATE a new file, write a CREATE section with one FILE block
holding the file's complete content:

CREATE: path/to/new_file.py
<<<<<<< FILE
def multiply(a, b):
    return a * b
>>>>>>> FILE

To DELETE a file, write a single line:

DELETE: path/to/old_file.py

Rules:
- Only touch the files listed as expected. Paths must match exactly.
- Every SEARCH text must match exactly once in its file; include
  enough context lines to make it unique.
- Do not repeat the whole file for a small change — that is what
  the blocks are for."""


class EditBlockError(ValueError):
    """The model's edit blocks are malformed or cannot be applied.

    ``path`` and ``existing_content`` are set only by the
    create-for-an-existing-file failure, so a caller can show the
    model the content it collided with when asking for a repair.
    """

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        existing_content: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.existing_content = existing_content


def _check_path(path: str, expected: Collection[str] | None) -> None:
    # Structural path rules (the same subset the agents' expectedFiles
    # validation applies); denied-path policy is enforced downstream
    # by validate_changeset on the produced ChangeSet, exactly as in
    # the JSON format path.
    if not path:
        raise EditBlockError("Section header has an empty path")
    if path.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", path):
        raise EditBlockError(
            f"Invalid path {path!r}: path must be relative (no leading '/', no drive letters)",
        )
    if "\\" in path:
        raise EditBlockError(
            f"Invalid path {path!r}: path must not contain backslashes",
        )
    segments = path.split("/")
    if ".." in segments or any(segment == "" for segment in segments):
        raise EditBlockError(
            f"Invalid path {path!r}: no '..' or empty segments allowed",
        )
    if any(ord(char) < 32 for char in path):
        raise EditBlockError(
            f"Invalid path {path!r}: path contains control characters",
        )
    if expected is not None and path not in expected:
        raise EditBlockError(
            f"Path {path!r} is not in the expected files list"
            f" ({', '.join(sorted(expected)) or 'empty'})",
        )


def _detect_eol(content: str) -> str:
    return "\r\n" if "\r\n" in content else "\n"


def _apply_search_replace(
    path: str,
    content: str,
    search: str,
    replacement: str,
) -> str:
    if not search:
        raise EditBlockError(
            f"SEARCH block for {path!r} is empty; include the exact lines to replace",
        )
    eol = _detect_eol(content)
    needle = search.replace("\n", eol) if eol == "\r\n" else search
    count = content.count(needle)
    if count != 1:
        raise EditBlockError(
            f"SEARCH text matched {count} times in {path!r}"
            " (exactly 1 required); copy the text exactly from the"
            " file and include more context lines to make it unique",
        )
    new_text = replacement.replace("\n", eol) if eol == "\r\n" else replacement
    return content.replace(needle, new_text, 1)


class _Section:
    def __init__(self, kind: str, path: str) -> None:
        self.kind = kind  # "modify" | "create" | "delete"
        self.path = path
        self.blocks: list[tuple[str, str]] = []  # (search, replacement)
        self.file_content: str | None = None


def parse_edit_blocks(
    reply: str,
    *,
    existing_files: Mapping[str, str],
    expected_files: Collection[str] | None = None,
    replaceable_paths: Collection[str] = (),
) -> ChangeSet:
    """Parses an edit-block reply into a full-content ChangeSet.

    ``existing_files`` maps path -> current content for files that
    exist at the base ref (used to apply SEARCH/REPLACE blocks and
    to reject modifying files that do not exist).

    A CREATE section for a path in ``replaceable_paths`` is accepted
    even though the path appears in ``existing_files``: the caller
    vouches that the path exists only as a pending change, so the
    section is a wholesale replacement of that pending entry rather
    than a collision with a real file.
    """
    text = reply.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    sections: list[_Section] = []
    current: _Section | None = None
    index = 0

    def fail(message: str) -> EditBlockError:
        return EditBlockError(message)

    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip():
            continue
        if line.startswith(("FILE: ", "CREATE: ", "DELETE: ")):
            kind_word, _, path = line.partition(": ")
            path = path.strip()
            _check_path(path, expected_files)
            kind = {"FILE": "modify", "CREATE": "create", "DELETE": "delete"}[kind_word]
            current = _Section(kind, path)
            sections.append(current)
            continue
        if line == SEARCH_MARKER:
            if current is None or current.kind != "modify":
                raise fail(
                    "SEARCH block outside a FILE section; start the"
                    " file's section with 'FILE: <path>' first",
                )
            search_lines: list[str] = []
            while index < len(lines) and lines[index] != SEPARATOR:
                if lines[index] in (SEARCH_MARKER, REPLACE_MARKER, FILE_MARKER):
                    raise fail(
                        f"Unterminated SEARCH block for {current.path!r}:"
                        f" missing the '{SEPARATOR}' separator line",
                    )
                search_lines.append(lines[index])
                index += 1
            if index >= len(lines):
                raise fail(
                    f"Unterminated SEARCH block for {current.path!r}:"
                    f" missing the '{SEPARATOR}' separator line",
                )
            index += 1  # consume =======
            replacement_lines: list[str] = []
            while index < len(lines) and lines[index] != REPLACE_MARKER:
                replacement_lines.append(lines[index])
                index += 1
            if index >= len(lines):
                raise fail(
                    f"Unterminated SEARCH block for {current.path!r}:"
                    f" missing the '{REPLACE_MARKER}' end line",
                )
            index += 1  # consume >>>>>>> REPLACE
            current.blocks.append(
                ("\n".join(search_lines), "\n".join(replacement_lines)),
            )
            continue
        if line == FILE_MARKER:
            if current is None or current.kind != "create":
                raise fail(
                    "FILE block outside a CREATE section; start it with 'CREATE: <path>' first",
                )
            if current.file_content is not None:
                raise fail(
                    f"CREATE section for {current.path!r} has more than one FILE block",
                )
            content_lines: list[str] = []
            while index < len(lines) and lines[index] != FILE_END_MARKER:
                content_lines.append(lines[index])
                index += 1
            if index >= len(lines):
                raise fail(
                    f"Unterminated FILE block for {current.path!r}:"
                    f" missing the '{FILE_END_MARKER}' end line",
                )
            index += 1  # consume >>>>>>> FILE
            current.file_content = "\n".join(content_lines) + ("\n" if content_lines else "")
            continue
        raise fail(
            f"Unexpected line outside any block: {line[:80]!r}; reply"
            " with FILE:/CREATE:/DELETE: sections and edit blocks only",
        )

    if not sections:
        raise fail(
            "No edit blocks found in the reply; use FILE:/CREATE:/DELETE: sections as instructed",
        )

    changes: list[FileChange] = []
    seen: set[str] = set()
    for section in sections:
        if section.path in seen:
            raise fail(
                f"Path {section.path!r} appears in more than one"
                " section; combine its edits into a single section",
            )
        seen.add(section.path)
        if section.kind == "delete":
            changes.append(
                FileChange(
                    path=section.path,
                    operation="delete",
                    content=None,
                )
            )
        elif section.kind == "create":
            changes.append(_create_change(section, existing_files, replaceable_paths))
        else:
            if not section.blocks:
                raise fail(
                    f"FILE section for {section.path!r} contains no SEARCH/REPLACE blocks",
                )
            if section.path not in existing_files:
                raise fail(
                    f"Cannot modify {section.path!r}: the file does"
                    " not exist; use a CREATE section to add it",
                )
            content = existing_files[section.path]
            for search, replacement in section.blocks:
                content = _apply_search_replace(
                    section.path,
                    content,
                    search,
                    replacement,
                )
            changes.append(
                FileChange(
                    path=section.path,
                    operation="modify",
                    content=content,
                )
            )
    try:
        return ChangeSet(changes=changes)
    except ValueError as error:
        raise EditBlockError(str(error)) from None


def _create_change(
    section: _Section,
    existing_files: Mapping[str, str],
    replaceable_paths: Collection[str],
) -> FileChange:
    """Builds a CREATE section's change.

    A replaceable path (the caller vouches it exists only as a
    pending change) is a wholesale replacement of that pending
    entry, not a collision; any other existing path is the
    create-for-an-existing-file failure, carrying the path and its
    current content so the caller can show the model what it hit.
    """
    if section.file_content is None:
        raise EditBlockError(
            f"CREATE section for {section.path!r} has no FILE block with the file's content"
        )
    if section.path in existing_files and section.path not in replaceable_paths:
        raise EditBlockError(
            f"Cannot create {section.path!r}: the file already"
            " exists; use a FILE section with SEARCH/REPLACE"
            " blocks to modify it",
            path=section.path,
            existing_content=existing_files[section.path],
        )
    return FileChange(
        path=section.path,
        operation="create",
        content=section.file_content,
    )
