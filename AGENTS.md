# AGENTS.md

Working rules for any coding agent (human or AI) changing this
repository. The same text ships to the platform's own agents as the
`code-structure` skill (`skills/code-structure/SKILL.md`); the two
must not drift. Python is enforced by `ruff` plus
`scripts/check_code_structure.py` (ratchet baseline:
`.code-structure-baseline.json`); the dashboard is enforced by
ESLint + Prettier.

# Code Structure Rules

## Functions
- Max 30 lines per function (excluding comments, blank lines, docstring). Target 20 or fewer.
- Max 4 parameters. More means a parameter object / dataclass / DTO. Dataclass and pydantic fields are not parameters.
- Max nesting depth 3. Prefer guard clauses and early returns.
- Cyclomatic complexity 10 or less.
- One function does one thing at one level of abstraction. If you need "and" to describe it, split it.

## Classes and files
- Max 300 lines per class and 10 public methods.
- Max 7 injected dependencies or fields. More means the class has more than one responsibility.
- Single Responsibility Principle: one reason to change.
- Do not split a large class with mixins. Extract collaborators and compose them.
- Max 500 lines per file, one main class per file.

## Readability and explicit syntax
- ALWAYS use braces for every control-flow block (`if`, `else`, `for`, `while`, `foreach`, `do`) in braces-based languages (TypeScript, Java, C#), even for a single statement. Never write `if (x) return y;` or `for (...) count++;`.
- Always put the body of a control-flow statement on its own line. Python: no `if x: return y`, no `for ...: ...` on one line, no `a; b`. The only exemption is a `Protocol`/ABC stub whose entire body is `...`.
- One statement per line.
- No nested ternary / conditional expressions. A single trivially readable ternary is allowed; otherwise use `if`/`else`.
- No clever dense one-liners (stacked boolean tricks, long method chains with side effects, obscure operators) when a clearer multi-line version exists.
- Names are descriptive and intention-revealing. No cryptic abbreviations except conventional loop indices in tiny scopes.
- No magic numbers or magic strings. Use named constants or enums (`http.HTTPStatus` for HTTP codes).
- Extract complex boolean conditions into well-named variables or methods.

## Comments
- Default is NO comment. Code explains itself through clear names and small functions. If a comment is needed to explain WHAT code does, rename or extract instead.
- Write a comment ONLY for: (1) important or non-obvious library/framework usage, workarounds and version-specific behavior; (2) complex or hard-to-understand logic where the WHY is not visible from the code; (3) an intentional exception to these rules; (4) docstrings on public ports / `Protocol` methods and on behavior that is not obvious from the signature.
- NEVER write: comments that restate the code; section banners or dividers (`# ------`); numbered step comments (`# 1. ...`, they mean the function should be split); change history or ticket references; commented-out code; docstrings on trivial getters, setters, constructors or methods whose docstring just restates the name; TODO/FIXME unless the user explicitly asks.
- A comment explains WHY, never WHAT, in one or two lines.
- When modifying existing code, do not add comments to lines you did not change, and do not strip existing comments that are still accurate unless the task is exactly this cleanup.

## When limits are exceeded
- Do not leave a long function and add a comment. Refactor by extracting well-named private functions or collaborators before finishing the task.
- Allowed exceptions: pure data/config mappings, generated code, large dispatch tables, test fixtures and parametrized case tables. Mark each with a one-line comment explaining why. Exceptions never cover branching logic.

## Verification (before presenting any result)
- Check every new or modified function and class against ALL rules above.
- Scan the diff and remove every comment that does not meet the Comments criteria.
- If any rule is violated, fix it first. Never report a task as done with a known violation.

# Pull Request / Merge Request description

Applies to any PR (GitHub) or MR (GitLab) an AI agent writes, in any
repository, language or framework. The templates in
`.github/pull_request_template.md` and
`.gitlab/merge_request_templates/Default.md` carry the same structure.

A PR/MR description MUST contain these sections, in this order, with
these exact headings:

## What
## Why
## How
## Verification
## Risk & Rollback
## Context

- **What**: a one-line summary, then the changes grouped by requirement
  or feature (R1, R2, ... or short bullets, whichever fits the size).
  Describe user-visible behaviour, not implementation. State which
  tests were added or changed.
- **Why**: the problem or need, who is affected, what was wrong before.
  Give a reason, not a restatement of What.
- **How**: one bullet per changed area: `path` - what was done. Group
  generated files and lockfiles into a single line. Every area named
  must exist in the diff, and every significant diff area must be named.
- **Verification**: the commands that were actually run, each with its
  real result, using this repo's own commands (here: `ruff check src
  tests harness`, `ruff format --check src tests harness`, `mypy src`,
  `bandit -c .bandit -r src -q`, `pytest -q`,
  `python scripts/check_code_structure.py --baseline
  .code-structure-baseline.json`, and for the dashboard `npm run build`
  and `npm test` in `apps/dashboard`). List manual testing only if it
  was really performed; otherwise write "Manual: not performed" plus
  what a reviewer should check by hand. Never invent, round or copy
  test counts, results, OS names or versions. If something was not run,
  write "not run" and why.
- **Risk & Rollback**: classify as a two-way door (easy to revert,
  additive, backward compatible) or a one-way door (migration,
  schema/data change, breaking API or protocol, deletion), with one
  sentence why. Give the blast radius (what is affected, what is
  explicitly untouched) and the exact rollback steps.
- **Context**: Resolves (issue/ticket or "None"), Relates to (or
  "None"), ADR/RFC (or "None"). If stacked on other branches, say which
  and the merge order.

Formatting rules:
- Plain Markdown, plain ASCII punctuation, paths and commands in
  backticks.
- English by default unless the repo's rules say otherwise.
- Factual and compact: no marketing words, do not repeat the diff,
  target under about 80 lines (summarize and group for big changes).
- Small trivial changes may keep each section to one or two lines, but
  all six headings stay.
- Do not add bot-style summary sections (those are generated by review
  tools).
- No leftover placeholders, HTML comments, TODO or TBD in the final
  text.
- Title: Conventional Commits, `type(scope): imperative summary`, max
  72 characters.
- One PR/MR = one coherent change. If the work mixes unrelated changes,
  say so and propose splitting.
- Before submitting, compare the description with `git diff --stat`.
