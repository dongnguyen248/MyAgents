# textkit — Specification

## Background / Goal

Users need a quick way to inspect plain-text files from the terminal.
textkit is a command-line tool that reads one UTF-8 text file and prints
basic statistics about it.

## Scope (in / out)

In scope: reading one local UTF-8 text file, printing word count,
character count, and the five most frequent words.
Out of scope: editing files, directories, non-UTF-8 encodings, graphical
output.

## Functional requirements

- REQ-1: The tool accepts exactly one file path argument and reads the
  file as UTF-8 text.
- REQ-2: The tool prints the total word count and the total character
  count of the file.
- REQ-3: The tool prints the five most frequent words with their counts,
  most frequent first.

## Non-functional requirements

- The tool runs on Python 3.11+ with no third-party dependencies.
- The tool exits with a non-zero status and a message on stderr when the
  file cannot be read.

## Acceptance criteria

- The tool feels fast and responsive on typical files (REQ-1, REQ-2).
- The output looks clear and professional (REQ-2, REQ-3).
- Users should generally be happy with the results (REQ-3).

## Open questions

- None.

## Revision history

- v1: initial specification.
