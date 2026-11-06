"""Normalisation and validation for user-entered model ids.

Model providers match ids EXACTLY, but ids reach the settings store
by pasting from web pages and documents, which smuggles in look-alike
characters: non-breaking hyphens (U+2011) instead of "-", zero-width
spaces, a byte-order mark. To the eye the field reads
"claude-haiku-4.5"; to the provider it is a different, unknown id,
and it answers 400 model_not_supported. This module is the single
source of truth for cleaning ids up:

- :func:`normalize_model_id` removes invisible characters (the
  zero-width/format characters and the C0/C1 controls) anywhere in
  the id, folds Unicode dash variants to "-", and trims Unicode
  whitespace at the edges. Internal whitespace is NOT folded — it
  makes the id invalid.
- :func:`checked_model_id` additionally validates: only
  [A-Za-z0-9._:/-] may remain, and the id must not be one fragment
  repeated back to back (the classic double-paste). Violations raise
  ValueError naming the field and the offending character's code
  point. Case is preserved: ids are case-sensitive.
- :func:`normalize_stored_model_id` is the load path: it normalises,
  logs a WARNING when normalisation changed the value or when the
  value is still invalid, and never raises — a bad stored id must
  not stop the backend from starting; the settings test or the run
  reports it instead.
"""

from __future__ import annotations

import logging
import re
import unicodedata

__all__ = [
    "checked_model_id",
    "model_id_problem",
    "normalize_model_id",
    "normalize_stored_model_id",
    "repeated_fragment",
]

logger = logging.getLogger(__name__)

_ALLOWED = re.compile(r"[A-Za-z0-9._:/-]")

_FORMAT_CHARS = frozenset({0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF})

_DASH_FOLD = dict.fromkeys(
    (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212),
    "-",
)


def _is_invisible(code_point: int) -> bool:
    return code_point in _FORMAT_CHARS or code_point < 0x20 or 0x7F <= code_point <= 0x9F


def normalize_model_id(value: str) -> str:
    """Cleans an id without judging it; never raises for str input."""
    kept = "".join(char for char in value if not _is_invisible(ord(char)))
    return kept.translate(_DASH_FOLD).strip()


def repeated_fragment(value: str) -> str | None:
    """The fragment when `value` is one fragment repeated >= 2 times."""
    length = len(value)
    for size in range(1, length // 2 + 1):
        if length % size == 0 and value[:size] * (length // size) == value:
            return value[:size]
    return None


def model_id_problem(value: str) -> str | None:
    """Why `value` is not a usable model id, or None when it is."""
    for char in value:
        if not _ALLOWED.match(char):
            name = unicodedata.name(char, "UNKNOWN")
            return (
                f"character U+{ord(char):04X} ({name}) is not allowed "
                "in a model id; use only letters, digits and . _ : / -"
            )
    fragment = repeated_fragment(value)
    if fragment is not None:
        return (
            f"the id is the fragment {fragment!r} repeated "
            f"{len(value) // len(fragment)} times; use {fragment!r} alone"
        )
    return None


def checked_model_id(field: str, value: str) -> str:
    """Normalises `value` and returns it, or raises ValueError."""
    normalized = normalize_model_id(value)
    problem = model_id_problem(normalized)
    if problem is not None:
        raise ValueError(f"Invalid model id for {field}: {problem}")
    return normalized


def normalize_stored_model_id(field: str, raw: str) -> str:
    """Load path: normalise a stored id, warn, never raise."""
    normalized = normalize_model_id(raw)
    if normalized != raw:
        logger.warning(
            "model settings: %s id normalised on load: %s -> %s",
            field,
            ascii(raw),
            ascii(normalized),
        )
    problem = model_id_problem(normalized)
    if problem is not None:
        logger.warning(
            "model settings: stored %s id %s is invalid: %s "
            "(kept as stored; the settings test or a run will report it)",
            field,
            ascii(normalized),
            problem,
        )
    return normalized
