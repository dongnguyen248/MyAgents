# MyAgents (AI Software Agents / ASF) Constitution

This constitution codifies the non-negotiable engineering, security, verification, and Git workflow rules already enforced in this repository (`AGENTS.md`, `pyproject.toml`, `.bandit`, `.github/workflows/ci.yml`).

## Core Principles

### I. Code Structure & Readability (Ratchet-Enforced)
- **Functions**: Maximum 30 code lines (excluding comments, blank lines, docstrings; target 20 or fewer), maximum 4 parameters (`PLR0913`; use a parameter object/dataclass/DTO for more), maximum nesting depth 3, cyclomatic complexity 10 or less (`C901`), maximum 25 statements (`PLR0915`). One function does one thing at one level of abstraction.
- **Classes & Files**: Maximum 300 lines per class, 10 public methods, 7 injected dependencies/fields; maximum 500 lines per file, one main class per file. Extract collaborators instead of splitting with mixins.
- **Explicit Syntax**: Always use braces for every control-flow block (`if`, `else`, `for`, `while`, `foreach`, `do`) in braces-based languages (TypeScript, Java, C#). Put every control-flow body on its own line in Python (`E701`/`E702`). No nested ternaries, no magic numbers/strings (`PLR2004`; use named constants or enums).
- **Comments**: Default is NO comment; code explains itself through clear names and small functions. Write comments ONLY for non-obvious library/framework behavior, WHY-not-WHAT explanations (1-2 lines), intentional rule exceptions, or public `Protocol`/non-obvious docstrings. Never leave commented-out code (`ERA001`), section banners, or unrequested TODO/FIXMEs.
- **Ratchet Rule**: `.code-structure-baseline.json` and `pyproject.toml` `[tool.ruff.lint.per-file-ignores]` blocks may only shrink, never grow.

### II. Security First (Overrides Convenience & Style)
- **Fail Closed & Least Privilege**: Deny on error, missing config, or failed check; never weaken security controls silently.
- **Secrets**: Never hardcode or commit secrets, tokens, passwords, or provider-shaped fakes (including tests, fixtures, docs). Reuse `scan_secrets` and `redact_text` in `src/asf/agents/_shared/security.py`. Add new secret names to `.env.example` with empty/fake values. Report any discovered secret immediately for rotation.
- **Input/Output & Crypto**: Treat all external input as untrusted. Use parameterized SQL, safe YAML/JSON loaders, and path-traversal checks. Return generic errors to clients (no stack traces, internal paths, tokens, or prompts). Use Argon2id/bcrypt/scrypt for passwords, CSPRNG for tokens/IDs, constant-time comparison for secrets.
- **LLM & Agent Safety**: Delimit untrusted data from instructions, authorize tool calls, cap input/output/cost, and scan model output with `scan_secrets`.

### III. Verification Gates Before Completion
Every code change must pass the repository's real gates (no skipping, no unapproved `nosec`/`noqa` suppressions):
- **Python**: `ruff check src tests harness`, `ruff format --check src tests harness`, `mypy src` (strict mode enforced on `asf.orchestrator.*`, `asf.state_machine.*`, `asf.approval.*`), `bandit -c .bandit -r src -q`, `pytest -q` (CI runs `--cov=asf --cov-report=term-missing`), `python scripts/check_code_structure.py --baseline .code-structure-baseline.json`.
- **Secrets Scan**: `gitleaks git --redact .` (matches `.gitleaks.toml`).
- **Dashboard (`apps/dashboard`)**: `npm run build`, `npm test`, `npm run lint`, `npm run format:check` (plus `npm audit` when dependencies change).
- **Truthful Reporting**: Never claim a check passed without running it and observing real output. Note any unrun or blocked check explicitly.

### IV. Git & PR Discipline
- **Branch Safety**: Never reset, rebase, or amend unpushed/shared branches without explicit instruction. Never lose local unpushed branches.
- **Commits**: Use Conventional Commits (`type(scope): imperative summary`, max 72 chars). Stage and commit files individually; never run `git add -A` or `git commit -a`.
- **No Unsolicited Push or PR**: Never push to remote or create a PR/MR unless the user explicitly commands it.
- **PR/MR Format**: Every PR/MR description must contain the exact 6 headings in order: `## What`, `## Why`, `## How`, `## Verification`, `## Risk & Rollback` (with `Security impact:` and two-way/one-way door classification), and `## Context`.

## Development Workflow & Spec Kit Integration

- Feature tracking uses Spec Kit artifacts under `specs/NNN-<short-name>/` (`spec.md`, `plan.md`, `tasks.md`).
- Task status markers in `tasks.md` follow `docs/speckit-workflow.md`: `[ ]` pending, `[x]` completed (with commit hash), `[~]` implemented locally but unpushed, `[!]` / `[NEEDS DECISION]` awaiting owner decision.
- No implementation code may be written or modified during spec-only or infrastructure-only turns.

## Governance

- `AGENTS.md` and CI workflows (`.github/workflows/ci.yml`) are the authoritative sources; this constitution mirrors them and must not invent conflicting rules.
- Any exception to code-structure limits requires an explicit one-line justification comment and must fall under allowed exceptions (pure data/config mappings, generated code, dispatch tables, test fixtures).

**Version**: 1.0.0 | **Ratified**: 2026-11-26 | **Last Amended**: 2026-11-26
