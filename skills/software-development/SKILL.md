---
name: software-development
description: Software design and implementation craft — decompose before coding, design interfaces and data first, build in small verifiable increments, handle errors and configuration deliberately, and keep changes backward-compatible unless the task says otherwise. Applies to planning, task breakdown, implementation, review and fixing on any stack.
---

# Software development craft

## Design before code

- Identify the moving parts first: data model, interfaces between
  components, and the external contracts (APIs, files, events).
  Code structure follows from those decisions, not the reverse.
- Put each responsibility in exactly one place. If two components
  need the same rule, it belongs in a shared module, not copied.
- Design for the change that is actually requested. Do not build
  extension points, plugin systems or generic frameworks for
  hypothetical future requirements.

## Implementation discipline

- Work in small increments that each leave the system coherent:
  one behaviour, its error handling, and its tests together.
- Validate at the boundary (user input, file formats, external
  responses) and trust validated data inside. Never validate the
  same thing at every layer.
- Make errors explicit and diagnosable: distinct error types or
  codes, messages that state what was expected and what was found,
  and no silent catch-and-continue. Never swallow an exception
  without either handling it meaningfully or re-raising with context.
- Configuration comes from configuration — no hard-coded hosts,
  ports, credentials, timeouts or magic literals in logic. Define
  constants once, in the project's shared constants location, and
  use enums for closed sets of values.
- Log at decision points and failures with enough context to
  reconstruct what happened; never log secrets or personal data.
- Prefer immutable data and pure functions where the language
  allows; isolate side effects (I/O, clock, randomness) at the
  edges so the core logic stays testable.

## Compatibility and safety

- Treat existing public contracts as promises: changing a signature,
  a file format or an API response is a breaking change and must be
  called out as one.
- When fixing a bug, fix the root cause, and check whether the same
  pattern exists elsewhere in the touched code.
- Leave the code you touched at least as clear as you found it:
  names that say what things are, functions that do one thing,
  comments only where the *why* is not obvious from the code.
