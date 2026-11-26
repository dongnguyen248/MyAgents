import assert from 'node:assert/strict';
import { test } from 'node:test';

import { workflowStatusBadge } from '../src/lib/workflowStatus.ts';

test('known statuses keep their tone, icon and label', () => {
  assert.deepEqual(workflowStatusBadge('RUNNING'), {
    tone: 'info',
    icon: '◐',
    label: 'Running',
  });
  assert.deepEqual(workflowStatusBadge('FAILED'), {
    tone: 'danger',
    icon: '✕',
    label: 'Failed',
  });
});

test('UNKNOWN renders as a warn badge labelled Unknown', () => {
  assert.deepEqual(workflowStatusBadge('UNKNOWN'), {
    tone: 'warn',
    icon: '?',
    label: 'Unknown',
  });
});

test('an arbitrary status string never throws', () => {
  const badge = workflowStatusBadge('SOME_FUTURE_STATUS');
  assert.equal(badge.tone, 'muted');
  assert.equal(badge.icon, '?');
  assert.equal(badge.label, 'Some Future Status');
});
