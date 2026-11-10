// Pure-function tests for the operator control cluster selection.
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  latestFindingsSummary,
  operatorActionsFor,
  type OperatorActionId,
} from '../src/lib/operatorActions.ts';
import type { Workflow } from '../src/types/workflow.ts';

function workflow(partial: Partial<Workflow>): Workflow {
  return {
    id: 'run-1',
    taskId: 'task-1',
    title: 'Task',
    projectId: 'vhpc',
    type: 'feature',
    status: 'RUNNING',
    steps: [],
    startedAt: '2026-11-05T00:00:00Z',
    updatedAt: '2026-11-05T00:00:00Z',
    ...partial,
  } as Workflow;
}

const ids = (w: Workflow): OperatorActionId[] => operatorActionsFor(w).map((a) => a.id);

test('escalated runs offer resume-with-budget and fail, both reasoned', () => {
  const actions = operatorActionsFor(workflow({ status: 'ESCALATED' }));
  assert.deepEqual(
    actions.map((a) => a.id),
    ['resume-escalation', 'fail-run', 'cancel'],
  );
  assert.equal(actions[0].needsReason, true);
  assert.equal(actions[1].needsReason, true);
  assert.equal(actions[1].danger, true);
});

test('stalled runs offer recover (both modes) and restart driver', () => {
  const stalled = workflow({
    status: 'RUNNING',
    waiting: {
      kind: 'STALLED',
      since: '2026-11-05T00:00:00Z',
      reason: 'No driver is working this run',
      retryAt: null,
      budget: null,
      suggestedActions: [],
    },
  });
  assert.deepEqual(ids(stalled), ['recover-replay', 'recover-fail', 'restart-driver', 'cancel']);
});

test('paused runs offer continue and cancel only', () => {
  assert.deepEqual(ids(workflow({ status: 'PAUSED' })), ['continue', 'cancel']);
});

test('running and waiting runs offer pause and cancel', () => {
  for (const status of ['RUNNING', 'WAITING_APPROVAL', 'WAITING_RETRY'] as const) {
    assert.deepEqual(ids(workflow({ status })), ['pause', 'cancel']);
  }
});

test('failed runs offer resume-from-failure and run again', () => {
  assert.deepEqual(ids(workflow({ status: 'FAILED' })), ['resume-failed', 'run-again']);
});

test('terminal runs offer nothing', () => {
  assert.deepEqual(ids(workflow({ status: 'COMPLETED' })), []);
  assert.deepEqual(ids(workflow({ status: 'CANCELLED' })), []);
});

test('cancel always carries the permanent warning as its confirm text', () => {
  for (const status of ['RUNNING', 'ESCALATED', 'PAUSED'] as const) {
    const cancel = operatorActionsFor(workflow({ status })).find((a) => a.id === 'cancel');
    assert.match(cancel?.confirm ?? '', /cannot be resumed/);
  }
});

test('findings summary prefers the latest review, then the test report', () => {
  const w = workflow({
    status: 'ESCALATED',
    artifacts: [
      { id: '1', type: 'TEST_REPORT', name: 't', version: '1', createdBy: 'test', content: 'tests failed' },
      { id: '2', type: 'CODE_REVIEW', name: 'r', version: '1', createdBy: 'review', content: 'review says no' },
    ],
  });
  assert.equal(latestFindingsSummary(w), 'review says no');
  const long = workflow({
    status: 'ESCALATED',
    artifacts: [
      { id: '3', type: 'TEST_REPORT', name: 't', version: '1', createdBy: 'test', content: 'x'.repeat(700) },
    ],
  });
  assert.equal(latestFindingsSummary(long)?.length, 601);
  assert.equal(latestFindingsSummary(workflow({ status: 'RUNNING' })), undefined);
});

test('escalated no-tests stops omit the fix-budget resume', () => {
  const stopped = workflow({
    status: 'ESCALATED',
    waiting: {
      kind: 'ESCALATED',
      since: '2026-11-09T00:00:00Z',
      suggestedActions: ['skip_tests', 'replace_test_commands', 'cancel'],
    },
  });
  assert.deepEqual(ids(stopped), ['fail-run', 'cancel']);
  const fixEscalated = workflow({
    status: 'ESCALATED',
    waiting: {
      kind: 'ESCALATED',
      since: '2026-11-09T00:00:00Z',
      suggestedActions: ['resume', 'cancel'],
    },
  });
  assert.deepEqual(ids(fixEscalated), ['resume-escalation', 'fail-run', 'cancel']);
});
