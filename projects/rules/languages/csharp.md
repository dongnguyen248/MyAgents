# C# Coding Rules

> **Scope:** C# / .NET code (ASP.NET Core backends and shared libraries).
> This is the shared language rule pack: it applies to every project whose
> profile uses C#. Project-specific rules and the project's own conventions
> add detail on top; match the architecture already used by the module
> being changed.

## 1. Naming and Structure

- Use `PascalCase` for types, methods, properties, events, and constants;
  `camelCase` for parameters and local variables; `_camelCase` for private
  instance fields; `s` prefix is not used for static fields (use
  `s_camelCase` only where the project already does). Prefix interfaces
  with `I` (`IBoardRepository`). Suffix asynchronous methods with `Async`.
- Use descriptive names that carry business meaning; avoid abbreviations
  and Hungarian notation. Name booleans as conditions (`isActive`,
  `hasPermission`, `canEdit`).
- One primary type per file, file name matching the type name. Use
  file-scoped namespaces. Keep namespaces aligned with the folder
  structure and the project's root namespace.
- Keep classes cohesive with explicit dependencies. Prefer constructor
  injection for required collaborators; do not add property or service
  locator injection to new production code.

## 2. Language and Type Safety

- Enable nullable reference types in new projects and respect the
  project's setting; do not disable nullable analysis or sprinkle `!`
  (null-forgiving) to silence warnings without a proven invariant.
- Prefer `record` for immutable data carriers and DTOs, `class` for
  entities with identity and behavior, `struct` only for small value
  semantics with a measured reason. Prefer `init` accessors and
  `readonly` members where mutation is not part of the design.
- Do not use `dynamic` in business logic. Validate untrusted values at
  the boundary before converting them to domain types.
- Prefer pattern matching and switch expressions over long `if/else`
  chains on type or state; keep control flow straightforward with early
  returns instead of deep nesting.

## 3. Constants and Magic Values

- Do not hardcode values that carry domain or protocol meaning inline:
  HTTP status codes (return or compare `HttpStatusCode` values or the
  framework result helpers, never a raw `200`), error codes, business
  states, limits, page sizes, timeouts, retry counts, and thresholds.
- Constants live in dedicated constants files under the project's common
  layer (for example a `Common/Constants` folder), grouped by concern,
  declared `const` or `static readonly`, named in `PascalCase`
  (`MaxFileSizeBytes`, `TokenTtlMinutes`), and defined exactly once —
  shared values are promoted to the common constants instead of copied.
- Closed sets of states or outcomes use an `enum` (or a dedicated type),
  not parallel string or numeric constants.

## 4. Async and Error Handling

- Asynchronous all the way: never block on `.Result`, `.Wait()`, or
  `GetAwaiter().GetResult()` in request or library code. Accept and
  forward `CancellationToken` on public asynchronous APIs.
- In library code, use
  `ConfigureAwait(false)` where the project convention does; in ASP.NET
  Core request code, do not capture a synchronization context that does
  not exist.
- Throw specific exceptions for specific failures; do not catch bare
  `Exception` except at a boundary that logs and translates it. Never
  swallow exceptions or return success-shaped defaults on failure. Do
  not use exceptions for ordinary control flow.
- For expected request-facing business failures, follow the project's
  established error contract (semantic error codes mapped centrally to
  HTTP status); do not invent per-endpoint error shapes or return raw
  numeric status codes from services.

## 5. Data Access and LINQ

- Use EF Core (or the project's established data layer) with parameterized
  queries; never concatenate untrusted values into SQL. Watch for
  client evaluation, N+1 queries, and unbounded `ToList()` on large sets —
  page list queries deliberately.
- Keep LINQ readable: one clear pipeline per statement; extract a named
  method when a query encodes a business rule instead of repeating it.

## 6. API and Contracts (ASP.NET Core)

- Define request and response DTOs deliberately; never expose EF entities
  directly on the wire. Apply validation attributes / FluentValidation
  (whichever the project uses) to inputs and validate business invariants
  and ownership in services, not by trusting the client.
- Follow the project's established response envelope and status mapping;
  keep authorization enforced on the server (`[Authorize]` / policies) —
  UI role checks never replace backend enforcement.

## 7. Logging and Security

- Use `ILogger<T>` with structured message templates
  (`logger.LogInformation("Created {TaskId}", id)`), never string
  interpolation into log messages, and never `Console.WriteLine` in
  production code.
- Never log or hardcode secrets, passwords, tokens, connection strings,
  or sensitive personal data. Read secrets from configuration /
  environment / the team's secrets manager.
- Treat all client input as untrusted; encode for the output context and
  rely on the framework's protections rather than hand-rolled escaping.

## 8. Tests and Review

- Test meaningful public behavior and failure boundaries with the
  project's established framework (xUnit or NUnit) and naming
  conventions. Cover authorization, validation, and state transitions
  where those paths change.
- Keep comments focused on non-obvious invariants. Verify changes
  preserve existing behavior and follow the project's `.editorconfig`
  formatting as the source of truth.
