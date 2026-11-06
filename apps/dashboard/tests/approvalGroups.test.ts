// Grouping tests for the Approvals page split (Phase 12 Stage E).
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { groupApprovals } from '../src/lib/approvalGroups.ts';
import type { Approval } from '../src/types/approval.ts';
import type { Workflow } from '../src/types/workflow.ts';

function approval(partial: Partial<Approval>): Approval {
  return {
    id: 'ap-1',
    projectId: 'vhpc',
    taskId: 'task-1',
    type: 'SPEC',
    status: 'PENDING',
    requestedAt: '2026-11-06T00:00:00Z',
    requestedByAgentId: 'agent-spec',
    artifact: 'SPEC.md',
    summary: '',
    comments: [],
    ...partial,
  };
}

function workflow(partial: Partial<Workflow>): Workflow {
  return {
    id: 'run-1',
    taskId: 'task-1',
    title: 'Task',
    projectId: 'vhpc',
    type: 'feature',
    status: 'RUNNING',
    steps: [],
    startedAt: '2026-11-06T00:00:00Z',
    updatedAt: '2026-11-06T00:00:00Z',
    ...partial,
  } as Workflow;
}

test('human-mode and modeless pending gates need a human; ai-mode gates do not', () => {
  const groups = groupApprovals(
    [
      approval({ id: 'h', mode: 'human' }),
      approval({ id: 'legacy' }),
      approval({ id: 'ai', mode: 'ai' }),
      approval({ id: 'done', mode: 'human', status: 'APPROVED' }),
    ],
    [],
  );
  assert.deepEqual(groups.needsHuman.map((a) => a.id), ['h', 'legacy']);
  assert.deepEqual(groups.aiReviewing.map((a) => a.id), ['ai']);
});

test('escalated runs join the needs-human group', () => {
  const groups = groupApprovals(
    [],
    [workflow({ id: 'esc', status: 'ESCALATED' }), workflow({ id: 'run', status: 'RUNNING' })],
  );
  assert.deepEqual(groups.escalated.map((w) => w.id), ['esc']);
  assert.equal(groups.needsHuman.length, 0);
});
