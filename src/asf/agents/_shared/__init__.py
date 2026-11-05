from __future__ import annotations

from asf.agents._shared.codegen import (
    FixContext,
    ImplementContext,
    build_fix_context,
    build_implement_context,
    generate_changeset,
)
from asf.agents._shared.contracts import (
    CommandResult,
    Finding,
    FindingSeverity,
    ReportContent,
    ReviewContent,
)
from asf.agents._shared.limits import (
    MAX_CHANGES_PER_CHANGESET,
    MAX_COMMAND_OUTPUT_BYTES,
    MAX_COMMAND_TIMEOUT_SECONDS,
    MAX_FILE_SIZE_BYTES,
    MAX_TOTAL_CONTENT_BYTES,
    check_changeset_limits,
    check_command_output_size,
    check_file_size,
)
from asf.agents._shared.parsing import ParseError, parse_json, strip_code_fence
from asf.agents._shared.paths import (
    ALWAYS_DENIED_EXTENSIONS,
    ALWAYS_DENIED_PREFIXES,
    DENIED_PATH_PATTERNS,
    check_denied_paths,
    check_scope,
    find_out_of_scope,
    validate_relative_path,
)
from asf.agents._shared.security import SecretMatch, scan_secrets
from asf.agents._shared.traceability import ArtifactKind, build_metadata
from asf.agents._shared.validation import (
    reject_whitespace_only,
    validate_list_no_whitespace,
    validate_no_duplicates,
)

__all__ = [
    # paths
    "validate_relative_path",
    "check_denied_paths",
    "check_scope",
    "find_out_of_scope",
    "DENIED_PATH_PATTERNS",
    "ALWAYS_DENIED_EXTENSIONS",
    "ALWAYS_DENIED_PREFIXES",
    # validation
    "reject_whitespace_only",
    "validate_no_duplicates",
    "validate_list_no_whitespace",
    # parsing
    "strip_code_fence",
    "parse_json",
    "ParseError",
    # traceability
    "build_metadata",
    "ArtifactKind",
    # limits
    "MAX_FILE_SIZE_BYTES",
    "MAX_COMMAND_OUTPUT_BYTES",
    "MAX_COMMAND_TIMEOUT_SECONDS",
    "MAX_CHANGES_PER_CHANGESET",
    "MAX_TOTAL_CONTENT_BYTES",
    "check_file_size",
    "check_command_output_size",
    "check_changeset_limits",
    # security
    "scan_secrets",
    "SecretMatch",
    # contracts
    "Finding",
    "FindingSeverity",
    "ReviewContent",
    "ReportContent",
    "CommandResult",
    # codegen
    "ImplementContext",
    "FixContext",
    "build_implement_context",
    "build_fix_context",
    "generate_changeset",
]
