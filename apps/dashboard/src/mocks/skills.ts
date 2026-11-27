import type { Skill } from '../types/skill';

/**
 * The platform's skill catalogue: one folder per skill under the repository's
 * `skills/` directory, each with a SKILL.md whose frontmatter carries the
 * description. `appliesTo` mirrors SKILL_AGENTS in asf/agents/_shared/skills.py;
 * `stackOnly` marks the skills gated by the project's technology stack.
 */
export const skills: Skill[] = [
  {
    id: 'code-review',
    name: 'code-review',
    description:
      'How to review a changeset rigorously — verify correctness against the specification first, then hunt for defects in logic, error handling, security, concurrency and resource use, check the tests actually prove the behaviour, and report findings by severity with precise locations. Applies when reviewing code or fixing code in response to review findings.',
    appliesTo: ['review', 'fix'],
    stackOnly: false,
    path: 'skills/code-review/SKILL.md',
  },
  {
    id: 'code-structure',
    name: 'code-structure',
    description:
      'The numeric code-structure rules every produced or reviewed file must satisfy — function size, parameters, nesting and complexity limits; class and file limits; explicit syntax (braces, one statement per line); the comments policy; and the self-verification pass. Applies when planning, breaking down, writing or reviewing code in any language.',
    digest:
      'Max 30 lines per function, 4 parameters, nesting depth 3, complexity 10; max 300 lines per class, 500 per file; explicit syntax and braces; no comments that restate code.',
    appliesTo: ['plan', 'task', 'implement', 'review', 'fix'],
    stackOnly: false,
    path: 'skills/code-structure/SKILL.md',
  },
  {
    id: 'database',
    name: 'database',
    description:
      'Relational data design and access discipline — model constraints in the schema, write migrations that are safe to run and roll back, avoid N+1 queries and unbounded result sets, use transactions around multi-step writes, and parameterize every query. Applies when planning data changes, implementing persistence, reviewing data-access code, or fixing data bugs.',
    appliesTo: ['plan', 'implement', 'review', 'fix'],
    stackOnly: false,
    path: 'skills/database/SKILL.md',
  },
  {
    id: 'general',
    name: 'general',
    description:
      'Core working agreements for every agent on any task — read the existing material before writing, keep changes minimal and scoped, make assumptions explicit, verify results instead of assuming them, and communicate uncertainty honestly. Applies to all specification, planning, coding, review and fixing work.',
    digest:
      'Keep changes minimal and scoped, make assumptions explicit, verify results mechanically, and respect agreed boundaries.',
    appliesTo: ['spec', 'plan', 'task', 'implement', 'review', 'fix'],
    stackOnly: false,
    path: 'skills/general/SKILL.md',
  },
  {
    id: 'git',
    name: 'git',
    description:
      'Version-control hygiene for produced changesets — small atomic changes that each do one thing, messages that explain why, no secrets or generated artefacts in the change, and file organisation that merges cleanly. Applies when implementing features or fixes whose result is committed or handed over as a changeset or pull request.',
    appliesTo: ['implement', 'fix'],
    stackOnly: false,
    path: 'skills/git/SKILL.md',
  },
  {
    id: 'java',
    name: 'java',
    description:
      'Idiomatic modern Java — immutability and records for data, Optional only as a return type, disciplined streams, precise exceptions, correct equals/hashCode, and explicit concurrency. Applies when planning, implementing, reviewing or fixing Java code on any framework.',
    digest:
      'Use records, final fields, Optional only as return type, and constructor injection; validate public inputs, throw specific exceptions, and avoid shared mutable state.',
    appliesTo: ['plan', 'implement', 'review', 'fix'],
    stackOnly: true,
    path: 'skills/java/SKILL.md',
  },
  {
    id: 'python',
    name: 'python',
    description:
      'Idiomatic modern Python — type hints on public APIs, dataclasses for data, specific exceptions with context, context managers for resources, and structure that stays testable with pytest. Applies when planning, implementing, reviewing or fixing Python code.',
    digest:
      'Follow Python standard library conventions, explicit type hints, pure functions without hidden side effects, and pytest testability.',
    appliesTo: ['plan', 'implement', 'review', 'fix'],
    stackOnly: true,
    path: 'skills/python/SKILL.md',
  },
  {
    id: 'react',
    name: 'react',
    description:
      'React and TypeScript component discipline — small typed components, state kept as local as possible, hooks used lawfully, effects only for true side effects, stable keys, accessible markup, and server state kept out of component state. Applies when planning, implementing, reviewing or fixing React front-ends.',
    digest:
      'Build small typed components, keep state local, derive values during render, use stable keys, and isolate side effects in hooks.',
    appliesTo: ['plan', 'implement', 'review', 'fix'],
    stackOnly: true,
    path: 'skills/react/SKILL.md',
  },
  {
    id: 'security',
    name: 'security',
    description:
      'Secure-by-default engineering — validate and encode untrusted input, prevent injection and broken access control, handle credentials and secrets correctly, use cryptography only through established libraries, and never leak sensitive detail in errors or logs. Applies when specifying security requirements, implementing anything that touches input, auth, data or external systems, reviewing code, and fixing vulnerabilities.',
    digest:
      'Specify explicit security requirements: who can access each record and operation (object-level authorization), how sensitive data is handled and protected, and which security-relevant events must be audited and logged.',
    appliesTo: ['spec', 'implement', 'review', 'fix'],
    stackOnly: false,
    path: 'skills/security/SKILL.md',
  },
  {
    id: 'software-development',
    name: 'software-development',
    description:
      'Software design and implementation craft — decompose before coding, design interfaces and data first, build in small verifiable increments, handle errors and configuration deliberately, and keep changes backward-compatible unless the task says otherwise. Applies to planning, task breakdown, implementation, review and fixing on any stack.',
    appliesTo: ['plan', 'task', 'implement', 'review', 'fix'],
    stackOnly: false,
    path: 'skills/software-development/SKILL.md',
  },
  {
    id: 'spring',
    name: 'spring',
    description:
      'Spring Boot application discipline — constructor injection and clear layering, transactions on the service layer, Bean Validation at the boundary, centralised exception handling, externalised configuration, and persistence without leaking JPA entities into APIs. Applies when planning, implementing, reviewing or fixing Spring Boot services.',
    digest:
      'Enforce controller/service/repository layering with constructor injection, DTOs at API boundaries, Bean Validation, @RestControllerAdvice, and @Transactional on service writes.',
    appliesTo: ['plan', 'implement', 'review', 'fix'],
    stackOnly: true,
    path: 'skills/spring/SKILL.md',
  },
  {
    id: 'testing',
    name: 'testing',
    description:
      'How to design tests that actually prove behaviour — test observable behaviour rather than implementation, cover boundaries and failure paths, keep tests independent and deterministic, and write acceptance criteria that can be verified mechanically. Applies when breaking work into tasks, implementing features, reviewing test quality, or fixing failing tests.',
    digest:
      'Define verifiable acceptance criteria, test observable behavior across boundaries and failure paths, and ensure deterministic test execution.',
    appliesTo: ['task', 'implement', 'review', 'fix', 'test'],
    stackOnly: false,
    path: 'skills/testing/SKILL.md',
  },
];
