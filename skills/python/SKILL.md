---
name: python
description: Idiomatic modern Python — type hints on public APIs, dataclasses for data, specific exceptions with context, context managers for resources, and structure that stays testable with pytest. Applies when planning, implementing, reviewing or fixing Python code.
---

# Python craft

## Types and data

- Annotate public functions and module boundaries with types;
  use `X | None` and modern built-in generics (`list[str]`,
  `dict[str, Any]`). Code that type-checks cleanly under a strict
  checker is the bar, not an aspiration.
- Model data with `@dataclass(frozen=True)` (or a pydantic model
  at system boundaries) instead of loose dicts passed between
  functions. A dict whose keys are a contract deserves a type.
- Prefer immutable structures and pure functions; keep I/O, clock
  and randomness at the edges and pass values in, so logic can be
  tested without patching the world.

## Errors and resources

- Raise specific exceptions with messages that state what was
  expected and what was found; define a small exception hierarchy
  per module instead of raising bare `Exception`/`ValueError`
  everywhere. Chain with `from` when wrapping.
- Never use a bare `except:` or `except Exception: pass`. Catch
  the narrowest exception you can handle meaningfully; everything
  else propagates. Broad catches at process boundaries must log
  with traceback.
- Every file, socket, lock and transaction is opened in a `with`
  block (or an explicit context manager). Generators that hold
  resources document who closes them.
- Avoid mutable default arguments, and never use `assert` for
  runtime validation — asserts disappear under `-O`.

## Structure and style

- Follow PEP 8 and the project's formatter/linter configuration;
  imports are grouped and absolute; no wildcard imports outside
  `__init__` re-exports.
- Strings that are data contracts (keys, codes, statuses) become
  named constants or enums defined once, not literals repeated
  across modules.
- Write functions that fit on a screen and do one thing; extract
  a helper when a block needs a comment to explain its purpose.
- Tests use pytest idioms: plain `assert`, fixtures for setup,
  `parametrize` for case tables, and `tmp_path`/fakes instead of
  touching the real filesystem or network (see the testing skill).
