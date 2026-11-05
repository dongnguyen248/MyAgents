---
name: general
description: Core working agreements for every agent on any task — read the existing material before writing, keep changes minimal and scoped, make assumptions explicit, verify results instead of assuming them, and communicate uncertainty honestly. Applies to all specification, planning, coding, review and fixing work.
---

# General working agreements

## Before you write anything

- Read the inputs you were given completely — requirement, spec, plan,
  existing files — before producing output. Most defects come from
  solving a problem adjacent to the one actually asked.
- Restate the goal in your own structure: what is being built, for
  whom, and what "done" looks like. If the inputs contradict each
  other, name the contradiction explicitly instead of silently
  picking a side.
- Prefer the smallest change that fully satisfies the requirement.
  Do not refactor, rename or reformat code outside the task's scope.

## While you work

- Make every assumption visible. An assumption written down can be
  reviewed; one buried in code cannot.
- Follow the conventions already present in the project — naming,
  layout, error handling, logging — over your own preferences.
  Consistency inside a codebase beats theoretical purity.
- Handle the failure paths, not only the happy path: invalid input,
  empty collections, missing files, dependency errors, timeouts.
- Never invent facts you cannot derive from the inputs: no made-up
  API signatures, configuration keys, file paths or version numbers.
  If something is unknown, mark it as an open question.

## Before you finish

- Re-read your output against the original requirement, line by
  line. Check that every requirement is addressed and nothing extra
  was added.
- Verify mechanically what can be verified: identifiers referenced
  exist, counts add up, cross-references resolve.
- Say what you did NOT verify. A result that states its own limits
  is more useful than one that implies total certainty.
