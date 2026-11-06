---
name: code-structure
description: The numeric code-structure rules every produced or reviewed file must satisfy — function size, parameters, nesting and complexity limits; class and file limits; explicit syntax (braces, one statement per line); the comments policy; and the self-verification pass. Applies when planning, breaking down, writing or reviewing code in any language.
---

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
