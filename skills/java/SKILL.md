---
name: java
description: Idiomatic modern Java — immutability and records for data, Optional only as a return type, disciplined streams, precise exceptions, correct equals/hashCode, and explicit concurrency. Applies when planning, implementing, reviewing or fixing Java code on any framework.
---

# Java craft

## Types and data

- Prefer `record` for immutable data carriers and `final` fields
  everywhere else; mutate state deliberately and locally, never
  through shared static state.
- Return `Optional<T>` from methods that may find nothing; never
  use `Optional` as a field or parameter type, never call `get()`
  without a presence check, and never return null where the caller
  must guess. Return empty collections instead of null collections.
- Implement `equals`/`hashCode` together or not at all, and never
  base them on mutable fields. Use enums for closed sets instead
  of string/int constants.
- Seal hierarchies (`sealed`/`permits`) when the set of subtypes
  is closed; pattern matching over them beats instanceof chains.

## APIs and exceptions

- Program to interfaces at module boundaries; keep implementations
  package-private where possible. Validate arguments at public
  boundaries with clear messages (`Objects.requireNonNull`,
  explicit range checks).
- Throw specific unchecked exceptions for programming errors and
  domain failures; reserve checked exceptions for recoverable
  conditions the caller must handle. Never catch `Exception` or
  `Throwable` broadly, never swallow an exception silently, and
  preserve the cause when wrapping.
- Never use exceptions for normal control flow, and never return
  sentinel values (-1, null) that duplicate what `Optional` or an
  exception expresses safely.

## Streams, concurrency, resources

- Use streams for transformations of collections, loops for logic
  with early exit or side effects. A stream pipeline that needs a
  comment to be understood should be a loop. Beware stateful or
  side-effecting lambdas and parallel streams on shared state.
- Close every resource with try-with-resources. Prefer
  `java.time` over `Date`/`Calendar`; use `BigDecimal` for money.
- Shared mutable state needs an explicit concurrency story:
  immutable objects, synchronization, or `java.util.concurrent`
  structures — chosen and documented, never accidental. Prefer
  constructor injection of dependencies over static access so code
  stays testable.
