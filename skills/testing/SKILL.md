---
name: testing
description: How to design tests that actually prove behaviour — test observable behaviour rather than implementation, cover boundaries and failure paths, keep tests independent and deterministic, and write acceptance criteria that can be verified mechanically. Applies when breaking work into tasks, implementing features, reviewing test quality, or fixing failing tests.
---

# Testing discipline

## What to test

- Test behaviour through the public interface: given this input
  and state, the system produces this output or effect. Do not
  test private helpers, call counts or internal ordering — those
  break on every refactor while proving nothing.
- For every behaviour, cover at minimum: the normal case, the
  boundary cases (empty, zero, one, maximum, just past the limit),
  and the failure cases (invalid input, missing dependency,
  downstream error).
- Every bug fix gets a regression test that fails without the fix
  and passes with it. State that pairing explicitly.
- Acceptance criteria must be mechanically checkable: "returns
  HTTP 422 with error code X when field Y is empty" is a criterion;
  "works correctly" is not.

## How to write tests

- Arrange–Act–Assert, one behaviour per test. A test that verifies
  five things reports one failure and hides four.
- Name tests after the behaviour and condition:
  `test_login_with_expired_token_is_rejected`, not `test_login_3`.
- Tests must be independent and deterministic: no shared mutable
  state, no reliance on execution order, wall-clock time, network
  or randomness — inject or fake those at the boundary.
- Fake at the system's edges (HTTP, filesystem, clock, external
  services), never by mocking the unit under test itself. A test
  whose mocks encode the implementation passes even when the
  behaviour is wrong.
- Assert on the strongest available signal: exact output or state
  change over "no exception was raised"; error type *and* message
  content over just the type.
- Test data should be minimal and readable: build the smallest
  fixture that exercises the case, and make the relevant values
  visible in the test, not buried in a shared setup.

## What to avoid

- No assertions inside loops that can pass with zero iterations.
- No tests that always pass (swallowed exceptions, assertions in
  dead branches, comparing a value to itself).
- No sleeping to "wait for" asynchronous work — wait on a signal.
- Do not delete or weaken a failing test to make a suite green;
  either the code is wrong or the test's expectation is, and the
  fix must say which.
