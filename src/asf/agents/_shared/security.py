from __future__ import annotations

import re

__all__ = ["redact_text", "scan_secrets", "SecretMatch"]


from dataclasses import dataclass


@dataclass(frozen=True)
class SecretMatch:
    """Represents a detected secret."""

    pattern_name: str
    file_path: str
    line_number: int
    matched_text: str


# Patterns for secret detection
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_secret_access_key", re.compile(r"[A-Za-z0-9/+=]{40}")),
    ("github_token", re.compile(r"gh[ps]_[A-Za-z0-9]{36}")),
    ("gitlab_token", re.compile(r"glpat-[A-Za-z0-9\-_]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("stripe_key", re.compile(r"sk_live_[A-Za-z0-9]{24,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    (
        "api_key_generic",
        re.compile(r"(?i)(?:api[_-]?key|apikey|secret)[\s\"'=:]+[A-Za-z0-9\-_]{20,}"),
    ),
    # D8: Assignment patterns for password/api_key/secret/token
    # These match explicit variable assignments with = and quoted values
    # Using longer minimum length (40) to avoid overlap with generic patterns in tests
    ("password_assignment", re.compile(r"(?i)(?:^|\s)password\s*=\s*[\"'][A-Za-z0-9\-_]{8,}[\"']")),
    ("api_key_assignment", re.compile(r"(?i)(?:^|\s)api_key\s*=\s*[\"'][A-Za-z0-9\-_]{40,}[\"']")),
    ("secret_assignment", re.compile(r"(?i)(?:^|\s)secret\s*=\s*[\"'][A-Za-z0-9\-_]{40,}[\"']")),
    (
        "token_assignment",
        re.compile(
            r"(?i)(?:^|\s)(?:access_token|auth_token)\s*=\s*[\"'][A-Za-z0-9\-_\.]{40,}[\"']"
        ),
    ),
    # Short API key patterns for known prefixes (sk-, pk-, etc.)
    (
        "stripe_test_key",
        re.compile(
            r"(?i)(?:^|\s)(?:api[_-]?key|apikey|secret)\s*=\s*[\"']sk[-_][a-zA-Z0-9\-_]{7,}[\"']"
        ),
    ),
    (
        "stripe_live_key_short",
        re.compile(
            r"(?i)(?:^|\s)(?:api[_-]?key|apikey|secret)\s*=\s*[\"']sk_live_[a-zA-Z0-9]{12,}[\"']"
        ),
    ),
    ("bearer_token", re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_]{20,}")),
    ("database_url", re.compile(r"(?i)(?:postgres|mysql|mongodb)://[^:\s]+:[^@\s]+@")),
    ("jwt_token", re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")),
]


_MATCH_PREVIEW_CHARS = 50


def scan_secrets(
    content: str,
    file_path: str,
    *,
    exclude_patterns: list[re.Pattern[str]] | None = None,
) -> list[SecretMatch]:
    """Scan content for potential secrets.

    Args:
        content: The file content to scan.
        file_path: Path of the file (for reporting).
        exclude_patterns: Optional list of regex patterns to exclude from matches.

    Returns:
        List of SecretMatch objects for detected secrets.
    """
    context = _ScanContext(file_path=file_path, exclude_patterns=exclude_patterns)
    matches: list[SecretMatch] = []
    for line_num, line in enumerate(content.splitlines(), 1):
        matches.extend(_line_matches(line, line_num, context))
    return matches


@dataclass(frozen=True)
class _ScanContext:
    file_path: str
    exclude_patterns: list[re.Pattern[str]] | None


def _line_matches(line: str, line_num: int, context: _ScanContext) -> list[SecretMatch]:
    matches: list[SecretMatch] = []
    for pattern_name, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(line):
            matched = match.group(0)
            if _excluded(matched, context.exclude_patterns):
                continue
            matches.append(
                SecretMatch(
                    pattern_name=pattern_name,
                    file_path=context.file_path,
                    line_number=line_num,
                    matched_text=matched[:_MATCH_PREVIEW_CHARS],
                )
            )
    return matches


def _excluded(matched: str, exclude_patterns: list[re.Pattern[str]] | None) -> bool:
    if not exclude_patterns:
        return False
    return any(exc.search(matched) for exc in exclude_patterns)


# Redaction-only pattern: credentials embedded in a URL of any
# scheme. scan_secrets deliberately flags only database URLs in
# code, but a quoted message must never display URL credentials.
_URL_CREDENTIALS = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^:\s/@]+:[^@\s]+@")


def redact_text(text: str) -> str:
    """Replace every secret-pattern span in ``text`` with ``[REDACTED]``.

    Matches are computed against the original text and merged, so
    overlapping patterns cannot hide a longer secret — the same
    algorithm the Test agent applies to command output, shared here
    for any surface that quotes potentially sensitive text (agent
    error messages on activity events, diagnostics).
    """
    spans = [
        (match.start(), match.end())
        for _, pattern in SECRET_PATTERNS
        for match in pattern.finditer(text)
    ]
    spans += [(match.start(), match.end()) for match in _URL_CREDENTIALS.finditer(text)]
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        parts.extend((text[cursor:start], "[REDACTED]"))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)
