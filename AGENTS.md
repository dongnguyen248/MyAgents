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
- **Risk & Rollback**: include a `Security impact:` line ("none" or the
  threat note, new dependencies, new secrets or config keys, changed
  permissions, new external inputs; see the Security rules section).
  Classify as a two-way door (easy to revert,
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

# Security rules

Applies to any code an AI agent writes, in any language or stack. A
rule applies when the code touches its area (the token rules apply
only when the code handles tokens, and so on).

## 0. Priority and scope

- Security rules override convenience, speed and style rules.
- If a task can only be done by weakening a security control, stop and ask; MUST NOT weaken it silently.
- MUST NOT write offensive tooling (keyloggers, C2, malware, credential stealers, working exploit code) or code whose purpose is attacking systems the user does not own; defensive code, detectors, tests with synthetic payloads and educational explanations are fine.

## 1. Design

- For any new feature touching auth, data or external input, MUST state what sensitive data it handles, who may access it, and how an attacker could reach it (a 3-5 line threat note in the PR "Risk & Rollback" section).
- MUST fail closed: on error, missing config or a failed check, deny; never default to allow.
- MUST apply least privilege: minimal scopes for tokens, database users, service accounts, file permissions and container users.

## 2. Secrets

- MUST NOT hardcode or commit secrets (keys, tokens, passwords, connection strings, certificates), including in tests, fixtures, docs and examples; examples MUST use obvious fake placeholders, never provider-shaped fakes.
- MUST read secrets from the environment or a secret manager; MUST NOT put secrets in images, logs, error messages, URLs or client-side code.
- MUST add new secret names to `.env.example` (or the example config) with an empty or fake value, never a real one.
- MUST reuse the repo's secret scanner and redactor (`scan_secrets`, `redact_text` in `src/asf/agents/_shared/security.py`); MUST NOT build a second mechanism.
- If a secret is found in the repo or its history, MUST report it immediately and recommend rotation; MUST NOT just delete the line and continue.

## 3. Input and output

- MUST treat all external input (user, files, network, database, environment, model output) as untrusted: validate type, length, range and allowlist.
- MUST use parameterized queries and safe APIs; MUST NOT build SQL, shell, LDAP or path strings by concatenation; MUST NOT pass untrusted data to a shell.
- MUST prevent path traversal: resolve paths and confirm they stay inside the allowed root.
- MUST NOT deserialize untrusted data with unsafe loaders (pickle, Marshal, unsafe YAML, native object deserialization); use safe formats and loaders.
- MUST encode output for its context (HTML, SQL, shell, logs) and MUST NOT render user input as HTML without escaping.
- MUST return generic errors to clients; MUST NOT expose stack traces, SQL, internal paths, tokens or system prompts.
- MUST make check-then-act sequences atomic (transaction, unique constraint, conditional update, lock) wherever money, stock, quotas, one-time codes or coupons are involved.

## 4. Authentication, sessions, authorization

- MUST distinguish authentication from authorization and check permission at object level (this user may access this record) and at function level.
- MUST NOT accept unsigned tokens or `alg: none`; MUST pin allowed algorithms; MUST validate `exp`, `iss`, `aud` and scope; MUST NOT reuse a public key as an HMAC secret.
- MUST revoke or invalidate sessions and refresh tokens on password change and on logout.
- Cookies MUST set HttpOnly, Secure and SameSite; MUST NOT place session ids or tokens in URLs or logs.
- MUST validate OAuth redirect URIs against an exact allowlist; no open redirects.
- MUST protect state-changing requests against CSRF when using cookie authentication.

## 5. Passwords and cryptography

- MUST hash passwords with Argon2id (or bcrypt/scrypt) with a per-user salt; MUST NOT use MD5, SHA-1 or plain SHA-256 for passwords.
- MUST use vetted libraries; MUST NOT invent cryptography. Use AES-256-GCM or ChaCha20-Poly1305 with a fresh random nonce per encryption; MUST NOT use ECB, static IVs or hardcoded keys.
- MUST use a cryptographically secure random source for tokens, ids and salts; MUST NOT use the language's non-crypto RNG for security values.
- MUST use constant-time comparison for secrets and signatures.

## 6. Web and API

- MUST enforce HTTPS and set security headers when building web responses: HSTS, CSP, `X-Content-Type-Options: nosniff`, frame protection.
- MUST add rate limiting to login, token, password-reset and expensive endpoints; respond 429 with `Retry-After`.
- MUST limit request body size, upload size and pagination size.

## 7. Dependencies and supply chain

- MUST use lockfiles and exact or hashed pins; MUST NOT use `*`, `latest` or unpinned installs.
- MUST NOT add a new dependency without stating why, what it does, its maintenance status and its license in the PR description; prefer the standard library or an existing dependency.
- MUST check new package names carefully (typosquatting, dependency confusion); internal packages MUST come from the private registry.
- MUST NOT run or add install hooks or download-and-execute scripts without explicit approval.
- MUST NOT disable audit, signature or TLS verification to make an install or a test pass.

## 8. Data and privacy

- MUST collect and store the minimum data; MUST classify PII and MUST NOT log passwords, tokens, card numbers, national ids or other personal data; mask a value when it must be logged.
- MUST encrypt sensitive data in transit and at rest, backups included.
- MUST NOT put real personal or production data in tests, fixtures or examples.

## 9. Infrastructure and containers

- Containers MUST run as non-root, MUST NOT be privileged, MUST NOT mount the Docker socket and MUST NOT bake secrets into images.
- Firewall and network rules MUST be default-deny with explicit allows; open only needed ports.
- MUST keep dev, staging and prod configuration and secrets separate.

## 10. Logging and monitoring

- MUST log security-relevant events with who, what, when, result and request id (auth failures, permission denials, token validation failures, rate-limit hits, admin actions), without sensitive data.
- MUST NOT log full request bodies or headers by default.

## 11. LLM and agent features (when the code calls a model or runs agents)

- MUST treat user text, uploaded files, web pages, tool results and database content as data, never as instructions; keep system instructions separate and delimit untrusted data.
- MUST authorize every tool call an agent can make; dangerous or irreversible actions need explicit allowlisting or human confirmation.
- MUST scan model output for secrets before it is stored, logged or shown (use `scan_secrets`), and MUST NOT let the model reveal system prompts or credentials.
- MUST cap input size, output size, tool-call count and cost per run.

## 12. Testing and CI

- MUST add tests for the security behaviour of the change (rejected input, denied access, expired or forged token, injection attempt, boundary values), not only the happy path.
- MUST NOT delete, skip, weaken or mark as expected-failure a security test to get a build green; MUST NOT add suppression comments for security linters (for example `nosec`, or `noqa` for security rules) without a written reason approved by a human.
- Before declaring work done, MUST run the repo's secrets scan (`gitleaks git --redact .`, see `.gitleaks.toml`), the SAST (`bandit -c .bandit -r src -q` and the ruff `S` rules in `ruff check`) and, when dependencies change, the dependency audit (`npm audit` in `apps/dashboard`), and report the real results in the PR "Verification" section.

## 13. Reporting

- In every PR/MR, the "Risk & Rollback" section MUST include a "Security impact" line: "none" or the threat note, new dependencies, new secrets or config keys, changed permissions, new external inputs.
- If a vulnerability is noticed while working, MUST report it with file and line and a suggested fix; MUST NOT silently fix unrelated code in the same change, and MUST NOT exploit or demonstrate it beyond a safe test.

## Before finishing (checklist)

- Secrets: no secret, token or provider-shaped fake added anywhere, including tests and docs; new secret names are in `.env.example` with fake values.
- Input validation: every new external input is validated; no string-built SQL, shell, LDAP or paths.
- Authz: every new endpoint or record access checks permission at function and object level.
- Dependencies: any new dependency is pinned, licensed and justified in the PR description.
- Logging: no sensitive data in new log lines or error responses.
- Tests: the attack case (rejected input, denied access, forged or expired token, injection) is covered by a test.
