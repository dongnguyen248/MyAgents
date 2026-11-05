---
name: git
description: Version-control hygiene for produced changesets — small atomic changes that each do one thing, messages that explain why, no secrets or generated artefacts in the change, and file organisation that merges cleanly. Applies when implementing features or fixes whose result is committed or handed over as a changeset or pull request.
---

# Git and changeset hygiene

## Shape of a change

- One changeset, one purpose. Do not mix a feature, a refactor and
  a formatting sweep in the same change — each becomes unreviewable
  and unrevertable.
- Keep the diff minimal and focused: touch only the files the task
  requires. Unrelated cleanups belong in a separate change.
- A change should leave the project buildable and its tests passing
  at every step; never commit a knowingly broken intermediate state
  as the final result.
- Delete dead code your change orphans (unused imports, functions,
  files) — but only code your change orphaned.

## What never goes in

- No secrets: credentials, tokens, private keys, `.env` files,
  personal data, or production data dumps.
- No generated artefacts that the build reproduces: build outputs,
  dependency folders, caches, IDE files, OS files. If the project
  has an ignore file, keep it accurate instead of working around it.
- No commented-out code "for later". Version control is the archive;
  the working tree should contain only live code.

## Messages and hand-over

- Write commit/merge-request messages that explain *why* the change
  exists and what it affects, in the imperative mood, with the
  first line a self-contained summary (the reader of a log should
  understand the change without opening it).
- Structure new files so future merges stay easy: one topic per
  file, shared constants and types in their established shared
  locations rather than appended to whichever file was open.
- When a change is intentionally breaking (API, schema, format),
  say so in the message and describe the migration, not just the
  new state.
- Before handing over, re-read your own diff as a reviewer would:
  every line should be explainable by the task. If a line cannot
  be explained, it does not belong.
