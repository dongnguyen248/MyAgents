# Constants and Magic Values Rules (p-vhpc)

> **Scope:** Backend Java and frontend TypeScript production code.
> The [Constitution](../constitution.md) takes precedence; the
> [Java](coding-rules.md), [API](api-rules.md), and
> [TypeScript](typescript-coding-rules.md) rules add layer-specific detail.

## 1. No Magic Values in Business Logic

- Do not hardcode values that carry domain or protocol meaning inline in
  business logic: HTTP status codes (for example `status = 200` or a raw
  `200` passed or compared as a status), error codes, business states and
  types, limits, page sizes, timeouts, retry counts, TTLs, file-size limits,
  money or percentage thresholds, and queue or topic names.
- Every such value is defined once as a named constant, an enum, or a
  configuration property, and referenced by name everywhere it is used.
  The same literal must never be repeated in more than one place.
- Closed sets of states, types, or outcomes use an enum or a union type,
  not a bag of string or numeric constants, so invalid values are
  unrepresentable or fail fast.

## 2. Where Constants Live

- Constants are defined in dedicated constants files, never scattered
  through controllers, services, or components. Backend: a dedicated
  constants class in the module's common layer (for example under a
  `common` or `constants` package such as
  `com.poscodx.ebidding.common.constants`), grouped by concern
  (HTTP, pagination, file limits, workflow). Frontend: the shared
  constants location `frontend/src/shared/constants/` (endpoint URLs
  already live in `frontend/src/shared/constants/api.ts`).
- A constants file contains only constant declarations (and, in Java,
  a private constructor); it must not grow business logic, helper
  behavior, or mutable state.
- A constant used by more than one module is promoted to the shared
  common constants location instead of being copied. Duplicated
  definitions of the same value are a defect even when the values
  currently agree.

## 3. Naming

- Java constants are `UPPER_SNAKE_CASE` `static final` fields; TypeScript
  module-level constants are `UPPER_SNAKE_CASE`. Names state the meaning
  and, where relevant, the unit (`MAX_FILE_SIZE_BYTES`,
  `TOKEN_TTL_MINUTES`), never the bare value (`TWO_HUNDRED`).
- Semantic `ErrorCode` values follow the [API rules](api-rules.md):
  business failures use `BusinessException` with an `ErrorCode`, and HTTP
  status mapping stays in `ErrorHttpStatusMapper`. A constants file must
  not become a back door for returning raw numeric status codes from
  services or controllers.

## 4. Review Severity

- A hardcoded HTTP status code, error code, business state, or threshold
  in production code is an `ERROR` finding.
- A repeated literal or a domain-meaning number or string defined inline
  (limits, sizes, durations) is at least a `WARNING` finding, with a
  suggestion naming the constants location it belongs in.
- Not violations: expected values in test assertions, `0`/`1` loop indexes
  and empty checks, and mathematical constants in a purely local
  computation whose meaning is obvious from the immediate context.
