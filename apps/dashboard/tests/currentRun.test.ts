// Pure-function tests for the dashboard's current-run pick: the
// shared (startedAt, updatedAt, API position) definition, compared
// as parsed instants, plus the backend-named run with its fallback.
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pickCurrentRun, pickTaskWorkflow } from '../src/lib/currentRun.ts';
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
    startedAt: '2026-11-09T00:00:00Z',
    updatedAt: '2026-11-09T00:00:00Z',
    ...partial,
  } as Workflow;
}

test('pickCurrentRun takes the newest started run in any order', () => {
  const older = workflow({ id: 'r-old', startedAt: '2026-11-09T01:00:00Z' });
  const newer = workflow({ id: 'r-new', startedAt: '2026-11-09T03:00:00Z' });
  const middle = workflow({ id: 'r-mid', startedAt: '2026-11-09T02:00:00Z' });
  assert.equal(pickCurrentRun([older, newer, middle])?.id, 'r-new');
  assert.equal(pickCurrentRun([newer, middle, older])?.id, 'r-new');
  assert.equal(pickCurrentRun([]), undefined);
});

test('pickCurrentRun ignores a late update of an older run', () => {
  const older = workflow({
    id: 'r-old',
    startedAt: '2026-11-09T01:00:00Z',
    updatedAt: '2026-11-09T09:00:00Z',
  });
  const newer = workflow({
    id: 'r-new',
    startedAt: '2026-11-09T04:00:00Z',
    updatedAt: '2026-11-09T04:00:00Z',
  });
  assert.equal(pickCurrentRun([older, newer])?.id, 'r-new');
});

test('equal startedAt falls to updatedAt, then to the later API position', () => {
  const first = workflow({
    id: 'aaa-first',
    startedAt: '2026-11-09T03:00:00Z',
    updatedAt: '2026-11-09T03:00:00Z',
  });
  const touched = workflow({
    id: 'bbb-touched',
    startedAt: '2026-11-09T03:00:00Z',
    updatedAt: '2026-11-09T06:00:00Z',
  });
  assert.equal(pickCurrentRun([first, touched])?.id, 'bbb-touched');
  assert.equal(pickCurrentRun([touched, first])?.id, 'bbb-touched');
  // Full tie: the later position in the API list wins. The previous
  // pick kept the smallest id here (stable string sort); that
  // behaviour is gone on purpose — the backend picks this way too.
  const twin = workflow({
    id: 'ccc-twin',
    startedAt: '2026-11-09T03:00:00Z',
    updatedAt: '2026-11-09T03:00:00Z',
  });
  assert.equal(pickCurrentRun([first, twin])?.id, 'ccc-twin');
});

test('timestamps compare as instants, not strings (mixed offsets)', () => {
  // 10:00 at +07:00 is 03:00Z — earlier than 04:00Z, although the
  // string '2026-11-10T10:00...' sorts after '2026-11-10T04:00...'.
  const offset = workflow({ id: 'r-offset', startedAt: '2026-11-10T10:00:00+07:00' });
  const zulu = workflow({ id: 'r-zulu', startedAt: '2026-11-10T04:00:00Z' });
  assert.equal(pickCurrentRun([offset, zulu])?.id, 'r-zulu');
});

test('an unparseable timestamp sorts lowest', () => {
  const broken = workflow({ id: 'r-broken', startedAt: 'not-a-date' });
  const valid = workflow({ id: 'r-valid', startedAt: '2026-11-09T01:00:00Z' });
  assert.equal(pickCurrentRun([broken, valid])?.id, 'r-valid');
  const otherBroken = workflow({ id: 'r-broken-2', startedAt: 'also-not-a-date' });
  assert.equal(pickCurrentRun([broken, otherBroken])?.id, 'r-broken-2');
});

test('pickTaskWorkflow prefers the backend-named run', () => {
  const older = workflow({ id: 'r-old', startedAt: '2026-11-09T01:00:00Z' });
  const newer = workflow({ id: 'r-new', startedAt: '2026-11-09T03:00:00Z' });
  assert.equal(pickTaskWorkflow([older, newer], 'r-old')?.id, 'r-old');
  assert.equal(pickTaskWorkflow([older, newer], undefined)?.id, 'r-new');
});

test('pickTaskWorkflow falls back when the named run is not in the pool yet', () => {
  // getTask and listWorkflows are fetched in parallel: the task
  // view can name a run the workflow list has not delivered yet.
  const older = workflow({ id: 'r-old', startedAt: '2026-11-09T01:00:00Z' });
  const newer = workflow({ id: 'r-new', startedAt: '2026-11-09T03:00:00Z' });
  assert.equal(pickTaskWorkflow([older, newer], 'r-not-landed')?.id, 'r-new');
  assert.equal(pickTaskWorkflow([], 'r-not-landed'), undefined);
});

test('a split parent pool picks the newest part attempt', () => {
  const partOneFirst = workflow({
    id: 'r-p1a',
    taskId: 'task-split-part-1',
    parentTaskId: 'task-split',
    startedAt: '2026-11-09T01:00:00Z',
    updatedAt: '2026-11-09T08:00:00Z',
  });
  const partTwo = workflow({
    id: 'r-p2',
    taskId: 'task-split-part-2',
    parentTaskId: 'task-split',
    startedAt: '2026-11-09T03:00:00Z',
  });
  const partOneSecond = workflow({
    id: 'r-p1b',
    taskId: 'task-split-part-1',
    parentTaskId: 'task-split',
    startedAt: '2026-11-09T05:00:00Z',
  });
  assert.equal(pickCurrentRun([partOneFirst, partTwo, partOneSecond])?.id, 'r-p1b');
});
