# textkit — Specification

## Background / Goal

Users need a quick way to inspect plain-text files from the terminal.
textkit is a command-line tool that reads one UTF-8 text file and prints
basic statistics about it.

## Scope (in / out)

In scope: reading one local UTF-8 text file, printing word count,
character count, and the five most frequent words; a hosted web
dashboard; multi-user accounts with cloud sync.
Out of scope: editing files.

## Functional requirements

- REQ-1: The tool accepts exactly one file path argument and reads the
  file as UTF-8 text.
- REQ-2: The tool prints the total word count and the total character
  count of the file.
- REQ-3: The tool prints the five most frequent words with their counts,
  most frequent first.
- REQ-4: The tool uploads every analysed file to the cloud sync service
  and shows the statistics in a web dashboard.

## Non-functional requirements

- The tool runs on Python 3.11+ with no third-party dependencies.
- The tool exits with a non-zero status and a message on stderr when the
  file cannot be read.

## Acceptance criteria

- Running `textkit sample.txt` on a file containing "a b a" prints a
  word count of 3 (REQ-1, REQ-2).
- The character count printed for the same file is 5 (REQ-2).
- The frequent-words list for "a b a" shows "a: 2" before "b: 1"
  (REQ-3).
- After running the tool, the same statistics appear in the user's web
  dashboard (REQ-4).
- Running `textkit missing.txt` exits non-zero and prints an error on
  stderr (REQ-1).

## Open questions

- None.

## Revision history

- v1: initial specification.
