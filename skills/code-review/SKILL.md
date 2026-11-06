---
name: code-review
description: How to review a changeset rigorously — verify correctness against the specification first, then hunt for defects in logic, error handling, security, concurrency and resource use, check the tests actually prove the behaviour, and report findings by severity with precise locations. Applies when reviewing code or fixing code in response to review findings.
---

# Code review method

## Review in this order

1. **Contract**: does the change do what the spec/task asked — all
   of it, and nothing beyond it? Missing requirements and silent
   scope creep are the highest-value findings.
2. **Correctness**: trace the changed logic with concrete values.
   Check boundary conditions (empty, zero, one, maximum), off-by-one
   errors, null/absence handling, ordering assumptions, and state
   that can be left inconsistent by a failure mid-operation.
3. **Error handling**: every failure path either recovers correctly
   or propagates a diagnosable error. Flag swallowed exceptions,
   fallback values that mask bugs, and resources (files, connections,
   locks) not released on the error path.
4. **Security**: untrusted input reaching queries, commands, HTML,
   file paths or deserialization; missing authorization checks;
   secrets in code or logs. (See the security skill.)
5. **Concurrency & resources**: shared mutable state, check-then-act
   races, unbounded growth (caches, lists, retries without limits),
   blocking calls on hot paths.
6. **Tests**: do the tests prove the behaviour, including failure
   cases? A test that cannot fail is a finding. Check that tests
   were not weakened to make the change pass.
7. **Readability**: names, structure and comments — only where they
   genuinely impede understanding. Style nits are the lowest
   priority and never block.

## Reporting findings

- One finding per defect, anchored to file and line, stating:
  what is wrong, the concrete scenario that triggers it, and the
  consequence. "This looks wrong" without a scenario is not a
  finding.
- Rate severity by impact: a defect that corrupts data, breaches
  security or breaks a stated requirement outranks everything else.
- Report violations of the code-structure limits (see the
  `code-structure` skill: function size, parameters, nesting,
  complexity, braces, one statement per line, the comments policy)
  as WARNING findings. Rate one ERROR only when the same violation
  would fail the CI structure checker — a new or worsened breach of
  a hard maximum, not a pre-existing one the ratchet tolerates.
- Do not report guesses as defects. If you suspect but cannot
  confirm an issue from the code provided, label it a question.
- Do not flag pre-existing issues outside the changeset as defects
  of this change; mention them separately, if at all.
- If the change is correct, say so plainly. A review that invents
  problems to look thorough is worse than useless.
