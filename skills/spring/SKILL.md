---
name: spring
description: Spring Boot application discipline — constructor injection and clear layering, transactions on the service layer, Bean Validation at the boundary, centralised exception handling, externalised configuration, and persistence without leaking JPA entities into APIs. Applies when planning, implementing, reviewing or fixing Spring Boot services.
---

# Spring Boot discipline

## Structure and injection

- Layer deliberately: controllers translate HTTP ↔ DTOs and hold
  no business logic; services own business rules and transactions;
  repositories own persistence. A controller that calls a
  repository directly is a defect.
- Constructor injection only — field injection hides dependencies
  and defeats testing. Keep configuration in `@Configuration`
  classes; components declare what they need, not where it lives.
- API payloads are DTOs, never JPA entities: entities leak lazy
  associations, internal fields and schema changes straight into
  the public contract. Map explicitly at the boundary.

## Web and validation

- Validate request DTOs with Bean Validation annotations and
  `@Valid` at the controller; cross-field and business rules live
  in the service. Validation failures return a consistent error
  body — one shape for the whole API.
- Handle exceptions centrally (`@RestControllerAdvice`): map
  domain exceptions to status codes deliberately (404 missing,
  409 conflict, 422 invalid), never let a stack trace or a default
  500 answer a predictable client error.
- Status codes and verbs follow REST semantics: POST creates (201
  with the resource), PUT/PATCH update, DELETE removes; GET never
  mutates. Pagination on every collection endpoint.

## Transactions and persistence

- `@Transactional` belongs on service methods that write; make
  read-only queries `@Transactional(readOnly = true)`. Know the
  propagation you are relying on instead of copying annotations.
- Beware lazy-loading outside a transaction (`LazyInitializationException`)
  and N+1 selects: use fetch joins or entity graphs for known
  access patterns, and check the generated SQL for new queries.
- Never call a remote system while holding a database transaction
  open.

## Configuration and operations

- All environment-specific values come from configuration
  (`application.yml` profiles / environment variables); secrets
  are never committed (see the security skill). Type-safe
  `@ConfigurationProperties` over scattered `@Value`.
- Expose health/readiness through Actuator where available, and
  log with correlation-friendly context (request id), not with
  `System.out` or printStackTrace.
