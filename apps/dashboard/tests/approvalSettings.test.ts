// Validation tests for the project approval settings (Phase 12 Stage E).
// The bounds mirror the server's parse_approval_overrides.
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  escalationReasonError,
  parseMaxRevisions,
  validateApprovalSettings,
} from '../src/lib/approvalSettings.ts';

test('unset everything is valid (the workflow default applies)', () => {
  assert.deepEqual(validateApprovalSettings({ mode: '', maxRevisions: '', onExhausted: '' }), []);
});

test('each documented value is valid, including the revision bounds 1 and 10', () => {
  for (const mode of ['ai', 'human', 'none']) {
    assert.deepEqual(validateApprovalSettings({ mode, maxRevisions: '', onExhausted: '' }), []);
  }
  for (const onExhausted of ['escalate', 'accept_with_warnings']) {
    assert.deepEqual(validateApprovalSettings({ mode: '', maxRevisions: '', onExhausted }), []);
  }
  assert.deepEqual(validateApprovalSettings({ mode: '', maxRevisions: '1', onExhausted: '' }), []);
  assert.deepEqual(validateApprovalSettings({ mode: '', maxRevisions: '10', onExhausted: '' }), []);
});

test('out-of-range or non-integer revisions are rejected like the server rejects them', () => {
  for (const maxRevisions of ['0', '11', '2.5', 'abc', '-1']) {
    const errors = validateApprovalSettings({ mode: '', maxRevisions, onExhausted: '' });
    assert.equal(errors.length, 1, maxRevisions);
    assert.match(errors[0], /between 1 and 10/);
  }
});

test('unknown mode and on-exhausted values are rejected', () => {
  assert.equal(validateApprovalSettings({ mode: 'auto', maxRevisions: '', onExhausted: '' }).length, 1);
  assert.equal(
    validateApprovalSettings({ mode: '', maxRevisions: '', onExhausted: 'ignore' }).length,
    1,
  );
});

test('parseMaxRevisions maps blank to undefined and text to a number', () => {
  assert.equal(parseMaxRevisions(''), undefined);
  assert.equal(parseMaxRevisions(' 7 '), 7);
});

test('escalation reasons are required and capped at 500 characters', () => {
  assert.equal(escalationReasonError(''), 'A reason is required.');
  assert.equal(escalationReasonError('   '), 'A reason is required.');
  assert.equal(escalationReasonError('ship it'), undefined);
  assert.match(escalationReasonError('x'.repeat(501)) ?? '', /at most 500/);
});
