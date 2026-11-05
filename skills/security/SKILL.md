---
name: security
description: Secure-by-default engineering — validate and encode untrusted input, prevent injection and broken access control, handle credentials and secrets correctly, use cryptography only through established libraries, and never leak sensitive detail in errors or logs. Applies when specifying security requirements, implementing anything that touches input, auth, data or external systems, reviewing code, and fixing vulnerabilities.
---

# Security engineering

## Input and injection

- Treat everything from outside the process as hostile: request
  bodies, query strings, headers, file contents, environment
  variables, and data read back from databases or other services.
- Use parameterized queries — never build SQL, shell commands,
  LDAP filters or template strings by concatenating untrusted
  input. Prefer allowlists over denylists for values like sort
  fields, file types and redirect targets.
- Encode output for its context (HTML, JSON, URL, shell) instead of
  trying to strip "bad" characters from input.
- Validate type, length, range and format at the boundary; reject
  what does not conform rather than trying to repair it.

## Authentication and authorization

- Check authorization on the server for every protected operation,
  on the specific object being accessed — being logged in is not
  permission to touch another user's data (IDOR).
- Passwords are hashed with a dedicated password hash (bcrypt,
  scrypt, Argon2) with per-user salt — never MD5/SHA or reversible
  encryption. Session and reset tokens are random, expiring, and
  invalidated after use or password change.
- Apply least privilege everywhere: database accounts, API tokens,
  file permissions and service roles get only what they need.

## Secrets and data protection

- Secrets live in secret stores or environment variables — never
  in source code, configuration files committed to a repository,
  logs, error messages or test fixtures. If a secret was committed,
  it is compromised: rotate it, do not just delete the line.
- Use established cryptographic libraries and standard protocols
  (TLS, AES-GCM, HMAC, JWT with verified signatures and expiry).
  Never design your own cipher, hash or token format.
- Collect and retain the minimum personal data the feature needs;
  mask or omit it in logs and error reports.

## Errors, dependencies and defaults

- Error responses to users must not reveal stack traces, SQL,
  file paths, or whether a username exists. Detail goes to
  protected logs; the client gets a safe message and an error id.
- Keep dependencies patched; add a dependency only when it earns
  its maintenance and audit cost, and pin versions.
- Ship secure defaults: debug modes off, directory listing off,
  cookies HttpOnly/Secure/SameSite, security headers on, and
  administrative interfaces not exposed by default.
- When a specification is written, state its security-relevant
  requirements explicitly (who may do what, what is sensitive,
  what must be audited) instead of assuming them.
