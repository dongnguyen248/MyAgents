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
counts (REQ-2) and the word frequencies (REQ-3); the CLI formats the
results on stdout and reports read errors on stderr with a non-zero
exit code.

## Impacted components

- `src/textkit/__main__.py` — argument handling and exit codes.
- `src/textkit/stats.py` — counting and frequency logic.
- `tests/test_stats.py` — unit tests for the statistics module.

## Milestones

- M1: Reader and counts (REQ-1, REQ-2). Done when it looks finished.
- M2: Frequencies (REQ-3). Done when the output seems right.

## Testing strategy

Test the tool a bit before calling it done.

## Risks & mitigations

- Things might go wrong; handle problems if they come up.

## Open questions

- None.

## Revision history

- v1: initial plan.
