# API Design Rules (p-vhpc)

> **Scope:** New or changed Spring REST endpoints and their frontend contracts.
> The [Constitution](../constitution.md) takes precedence. Do not silently
> change existing clients or API shapes to satisfy a style example.

## 1. Resources and Operations

- Prefer plural resource nouns and kebab-case paths. Use HTTP methods according
  to their semantics: GET for reads, POST for creation or commands, PUT for full
  replacement, PATCH for partial updates, and DELETE for removal.
- Workflow transitions that are commands may use an explicit operation endpoint
  when that matches the established API (for example, `POST /{source}/{id}/submit`).
  Document authorization, state transitions, idempotency, and retry behavior;
  do not rename existing endpoints solely to avoid verbs.
- Use the established `page`, `size`, and `sort` contract for list endpoints.
  Do not invent feature-specific pagination parameters.

## 2. Request Contracts and Validation

- Define request and response DTOs deliberately; keep Java DTO fields and
  TypeScript contract fields in 1:1 camelCase parity, including required and
  nullable fields as prescribed by the Constitution.
- Apply `@Valid` and Bean Validation constraints to controller inputs, including
  applicable query or path inputs. Validate business invariants, ownership, and
  scope in services, not by trusting the frontend.
- Do not add fields to a request or response that the agreed contract has not
  defined. Keep frontend URLs in `frontend/src/shared/constants/api.ts` and
  Axios calls in feature `api/` modules.

## 3. Success Responses and Compatibility

- Follow the approved success-response contract. `ApiResponse<T>` currently
  exposes `success`, `code`, `errorCode`, `message`, `data`, and `timestamp`.
  Existing Purchase Request endpoints also have bare responses; do not rewrite
  their envelopes as part of an unrelated feature.
- Confirm the compatibility strategy for every new endpoint before implementing
  it. Do not add a new shape ad hoc or claim the legacy endpoints are already
  consistent. Ensure the HTTP status, response `code`, and client expectations
  agree; do not force 201 on an existing 200 contract or vice versa.

## 4. Errors and HTTP Status

- Use `BusinessException` with a semantic `ErrorCode` for expected request-facing
  business failures. Map every new code in `ErrorHttpStatusMapper`; keep HTTP
  status decisions out of services and business exceptions.
- Let `GlobalExceptionHandler` produce the project's standard
  `ApiErrorResponse` (`success`, `code`, `errorCode`, `message`, `timestamp`,
  `path`, optional `fieldErrors` and `correlationId`). Validation and known
  input failures map to 400; authentication to 401, authorization to 403,
  missing resources to 404, and conflicts to 409 as appropriate. Unexpected
  errors map to a client-safe 500 `INTERNAL_ERROR`.
- RFC 7807 Problem Details is **not** the current project error contract.
  Adopting it would be a cross-cutting API change requiring team approval,
  contract migration, and corresponding Constitution review.

## 5. Verification

- Cover changed endpoint authorization, validation, DTO shape, response status,
  and semantic error-code/status mappings with focused tests.
- Keep client-facing messages safe; never return stack traces, SQL details,
  storage keys, or other internal implementation information.
