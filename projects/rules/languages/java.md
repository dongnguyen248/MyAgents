# Java Coding Rules (p-vhpc)

> **Scope:** Backend Java code (the project currently uses Java 21 and Spring
> Boot 3.5.16). The [Constitution](../constitution.md) takes precedence;
> [API](api-rules.md) and [security](security-rules.md) rules add layer-specific
> detail. Match the architecture already used by the module being changed.

## 1. Readability and Structure

- Use descriptive `UpperCamelCase` types, `lowerCamelCase` methods and variables,
  `UPPER_SNAKE_CASE` constants, and lowercase package names under
  `com.poscodx.ebidding`. Avoid abbreviations that hide business meaning.
- Give methods a focused purpose and keep them within the shared
  code-structure limits (see the `code-structure` skill: max 30 lines
  per method, max 4 parameters, nesting depth at most 3, complexity
  at most 10); extract helpers to meet them. Favor straightforward
  control flow, early validation, and minimal nesting over
  speculative abstractions.
- Keep classes cohesive and dependencies explicit. Prefer constructor injection
  for required collaborators; do not add field injection to new production code.
- Follow the existing module's layered or clean/hexagonal structure. Reuse
  established services, repositories, DTO mappers, and enums rather than
  duplicating domain behavior in controllers or introducing needless patterns.
- Use named constants, enums, or configuration for domain values and limits.
  Do not encode business states as undocumented string or numeric literals.

## 2. Formatting and Java Idioms

- Use the repository's Spotless configuration (`palantirJavaFormat`, import
  ordering, unused-import removal) as the formatting source of truth. Keep
  imports at the top; avoid fully qualified names inside business logic.
- Prefer `final` for dependencies and values that do not change. Keep local
  variables in the narrowest useful scope, including inside a loop when they
  belong to one iteration. Prefer enhanced `for` when it makes the code clearer.
- Use `Optional<T>` for absent single-entity lookup results, not for fields or
  collections. Return empty collections for valid empty results; reject invalid
  inputs explicitly. Do not use null or a generic fallback to hide failures.
- Preserve the `BaseEntity`, audit, `@Version`, soft-delete, money, timezone,
  migration, and repository-query conventions stated in the Constitution.

## 3. Errors, Transactions, and Logging

- For expected client-facing business failures, throw `BusinessException` with
  a semantic `ErrorCode`. Add its HTTP mapping in `ErrorHttpStatusMapper`.
  Do not introduce bare `IllegalArgumentException`, `RuntimeException`, or
  numeric status codes for these failures.
- Catch specific exceptions only where the code can add context, recover, or
  compensate; otherwise let the centralized handler translate failures.
  Never swallow exceptions or return success-shaped defaults on failure.
- Put state-changing business rules in services and define transaction
  boundaries deliberately. A database transaction does not roll back MinIO,
  Redis, email, or other external effects; design their failure/compensation
  behavior explicitly when a workflow spans systems.
- Use SLF4J (including the project's existing Lombok `@Slf4j` usage) with
  parameterized messages. Do not use `System.out.println` or log secrets or
  sensitive payloads. Preserve the Constitution's audit requirements for
  critical actions: user ID, action, and IP address.

## 4. Tests and Review

- Test meaningful public behavior and failure boundaries rather than imposing
  one test per method. Cover authorization, validation, state transitions,
  rollback/retry behavior, and semantic error-code/HTTP-status mapping where
  those paths change. Use the project's JUnit 5 and Spring test conventions.
- Keep code comments focused on non-obvious invariants. Verify that changes
  preserve existing module behavior and do not broaden cross-team edits
  without the confirmations required by the Constitution.
