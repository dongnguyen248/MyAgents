# Code Structure Rules (all projects, all languages)

> **Scope:** All production code, every language. These rules bind the
> Implement and Fix agents when writing code and the Review agent when
> judging it. Exceeding a stated **maximum** is an ERROR finding;
> exceeding a **target** is a WARNING finding. Language packs and
> project rules add detail; on conflict the stricter limit wins.

## 1. Functions

- **Max 30 lines per function** (excluding comments and blank lines).
  Target ≤ 20 lines.
- **Max 4 parameters.** If more are needed, introduce a parameter
  object / DTO instead of a longer parameter list.
- **Max nesting depth of 3.** Prefer guard clauses and early returns
  over deeper nesting.
- **Cyclomatic complexity ≤ 10 per function.**
- One function does one thing at one level of abstraction. If you
  need the word "and" to describe what it does, split it.

## 2. Classes

- **Max 300 lines per class. Max 10 public methods.**
- **Max 5–7 injected dependencies.** More than that means the class
  has too many responsibilities — split it.
- Single Responsibility Principle: one class, one reason to change.

## 3. Readability and Explicit Syntax

- **Always use braces for every control-flow block** (`if` / `else` /
  `for` / `while` / `foreach` / `do`), even when the body is a single
  statement. Never write braceless or same-line forms such as
  `if (x) return y;`, `if (x) doSomething();`, or `for (...) count++;`.
  Write instead:

  ```java
  if (x) {
      return y;
  }
  ```

- Always put the body of a control-flow statement on its own line(s).
  No one-line compound statements — in Python: no `if x: return y`,
  no `for ...: ...` on a single line, no `a; b` on one line.
- One statement per line. Do not chain several side effects with `;`
  or `,`.
- No nested ternary / conditional expressions. A single simple
  ternary is allowed only when it is trivially readable; otherwise
  use if/else.
- Do not use clever or dense one-liners (stacked boolean tricks, long
  method chains with side effects, obscure operators) when a clearer
  multi-line version exists. Clarity beats brevity.
- Names must be descriptive and intention-revealing. No cryptic
  abbreviations (`d`, `tmp`, `x1`, `mgr`), except conventional loop
  indices in tiny scopes.
- No magic numbers or magic strings. Extract them to named constants
  or enums (see also the project constants rules where present).
- Extract complex boolean conditions into well-named variables or
  methods:

  ```java
  boolean isEligibleForDiscount = customer.isActive() && order.total() > MIN_TOTAL;
  if (isEligibleForDiscount) { ... }
  ```

## 4. Comments

- **Default is NO comment.** Code must explain itself through clear
  names and small functions. If a comment is needed to explain what
  the code does, rename or extract instead.
- Write a comment ONLY in these cases:
  1. Important or non-obvious library/framework usage (why this
     library, version-specific behavior, a workaround for a known
     bug).
  2. Complex, tricky, or hard-to-understand logic (business rules,
     algorithms, performance tricks) where the WHY is not obvious
     from the code.
  3. Intentional exceptions to these rules (see section 5).
  4. Public API / interface contracts when the project requires doc
     comments (Javadoc, docstring, XML doc), and only for public
     members.
- NEVER write:
  - Comments that restate the code (`// increment counter`,
    `// loop through list`, `# return the result`).
  - Section banners or dividers (`// ===== Helpers =====`).
  - Comments describing a change or history (`// added for
    ticket 123`, `// fixed bug`, `// new code`). That belongs in
    git, not in source.
  - Commented-out code. Delete it.
  - Docstrings/Javadoc on trivial getters, setters, constructors, or
    obvious methods.
  - TODO/FIXME unless the user explicitly asks for one.
- A comment explains WHY, never WHAT. Keep it to one or two lines.
- When modifying existing code, do not add comments to lines you did
  not change, and do not strip existing comments that are still
  accurate unless the user asks.

## 5. When a Limit Is Exceeded

- Do NOT leave a long function in place and add a comment about it.
  Refactor by extracting well-named private methods or collaborators
  before finishing the task.
- Exceptions (configuration mappers, generated code, large switch
  tables) must be marked with a one-line comment explaining why the
  exception is legitimate.

## 6. Self-Verification (Implement and Fix)

- After writing code, self-check every new or modified function
  against ALL rules above — including the brace rule, the
  one-statement-per-line rule, and the comment rules — before
  declaring the work done.
- Before presenting the result, scan the diff and remove every
  comment that does not meet the criteria in section 4.
- If any rule is violated, fix it before presenting the result. Do
  not report a task as done with known violations.
