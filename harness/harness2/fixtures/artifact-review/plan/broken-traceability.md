# textkit — Plan

## Linked SPEC

Implements the textkit specification (SPEC artifact, version 1).

## Scope and out of scope

Scope: the single-file statistics CLI described by the SPEC.
Out of scope: editing, directories, non-UTF-8 encodings, graphical
output.

## Approach / architecture

A single Python package `textkit` with a small entry point. The reader
loads the file as UTF-8 (REQ-1); a pure statistics module computes the
counts (REQ-2); the CLI formats the results on stdout and reports read
errors on stderr with a non-zero exit code.

## Impacted components

- `src/textkit/__main__.py` — argument handling and exit codes.
- `src/textkit/stats.py` — counting logic.
- `tests/test_stats.py` — unit tests for the statistics module.

## Milestones

- M1: Reader and counts. The CLI reads a file and prints word and
  character counts (REQ-1, REQ-2). Done when the sample-file checks in
  the SPEC acceptance criteria pass.

## Testing strategy

Unit tests for the statistics module with fixed sample inputs, plus a
CLI-level test that runs the tool on a sample file and on a missing
file and asserts stdout, stderr, and exit codes.

## Risks & mitigations

- Ambiguous word boundaries: define a word as a maximal run of
  non-whitespace characters and pin the definition with tests.

## Open questions

- None.

## Revision history

- v1: initial plan.
