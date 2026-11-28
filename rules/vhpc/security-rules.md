# Security Rules (p-vhpc)

> **Applies to:** Backend, frontend, configuration, and infrastructure changes.
> The [Constitution](../constitution.md) takes precedence. Follow its open
> security decisions rather than choosing a new policy in a feature.

---

## 1. No Hardcoded Secrets

Never hardcode API keys, passwords, connection strings, JWT secrets, or tokens in:
- Source code (.java, .py, .js, etc.)
- Configuration files (application.properties, application.yml)
- Comments or documentation

Use environment variables or the team's approved secrets manager.

---

## 2. Input Validation and Output Encoding

- Use Bean Validation on controller inputs and DTOs. Validate business
  invariants and authorization scope in services with `BusinessException` and
  semantic `ErrorCode` values; do not silently discard invalid input.
- Treat all client input as untrusted. Encode or escape it for its *output
  context* (HTML, SQL, URLs, file paths); do not indiscriminately strip
  characters from legitimate business data.

See the Constitution's file-upload requirements for MIME, size, and safe
object-key validation. Virus/malware scanning remains an **open decision**;
never silently assume it is enabled or unnecessary.

---

## 3. SQL / Injection Protection

- Use Spring Data JPA / Hibernate parameterized queries or ORM methods.
- Never concatenate untrusted values into native SQL or JPQL queries.
- Never use user-supplied values directly in query strings.

---

## 4. Authorization and Scope

- Secure endpoints with `@PreAuthorize` or the standard Spring Security
  configuration; enforce ownership, company, and business scope in services
  where endpoint-level roles alone are insufficient.
- UI role checks improve UX but never replace backend enforcement.
- Token storage, authentication, CORS, and CSRF changes require the separate
  cross-cutting review specified in the Constitution.

---

## 5. Audit Logging and Sensitive Data

- Never log passwords, tokens, payment data, national IDs, emails, phone
  numbers, or full request/response bodies containing these values.
- For critical actions, record the user ID, action, and IP address as the
  Constitution requires; restrict access and retention according to the
  team's audit policy. Mask or omit unrelated personal fields.

---

## 6. Dependency Security

- Review and update dependencies using the project's Gradle/npm tooling and
  approved security-audit process; do not assume Maven is configured.
- Do not import libraries from untrusted or unmaintained sources.

---

## 7. Error Message Disclosure

- Do NOT expose internal stack traces, database error messages, or system internals to the client.
- Return client-safe validation and business errors with semantic `ErrorCode`
  values in the standard `ApiErrorResponse` shape. For unexpected failures,
  return a generic `INTERNAL_ERROR` and log details server-side.
- Do not switch error formats or expose internal stack traces, database
  errors, object keys, or secrets in responses.
