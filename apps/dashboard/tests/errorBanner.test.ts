// Pure-function tests for the failure banner text.
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { errorBannerText, errorDetailLines } from '../src/lib/errorBanner.ts';
import type { Workflow } from '../src/types/workflow.ts';

function workflow(partial: Partial<Workflow>): Workflow {
  return {
    id: 'run-1',
    taskId: 'task-1',
    title: 'Task',
    projectId: 'messenger',
    type: 'feature',
    status: 'RUNNING',
    steps: [],
    startedAt: '2026-11-06T00:00:00Z',
    updatedAt: '2026-11-06T00:00:00Z',
    ...partial,
  } as Workflow;
}

test('banner renders a sandbox apply failure with its cause details', () => {
  const banner = errorBannerText(
    workflow({
      status: 'FAILED',
      steps: [
        {
          id: 'test',
          label: 'Run tests',
          state: 'failed',
        } as Workflow['steps'][number],
      ],
      error: {
        code: 'SANDBOX_APPLY_FAILED',
        category: 'INTEGRATION',
        message: 'apply failed: cannot modify missing file docs/testing/decisions.md',
        details: {
          phase: 'start',
          exceptionType: 'SandboxApplyError',
          cwd: 'E:/develops/JAVA/MyAgents/data/worktrees/messenger/run-1',
          cwdExists: true,
          elapsedMs: 12,
        },
      },
    }),
  );
  assert.ok(banner);
  assert.equal(
    banner.headline,
    'Failed at Run tests: apply failed: cannot modify missing file docs/testing/decisions.md',
  );
  assert.equal(banner.codeLine, '(SANDBOX_APPLY_FAILED · INTEGRATION)');
  assert.deepEqual(banner.detailLines, [
    'phase: start',
    'exceptionType: SandboxApplyError',
    'cwd: E:/develops/JAVA/MyAgents/data/worktrees/messenger/run-1',
    'cwdExists: true',
    'elapsedMs: 12',
  ]);
});

test('detail lines render numbers and booleans, not only strings', () => {
  assert.deepEqual(
    errorDetailLines({ errno: 2, commandName: 'dotnet', cwdExists: false }),
    ['errno: 2', 'commandName: dotnet', 'cwdExists: false'],
  );
});

test('no banner for a run that has not failed', () => {
  assert.equal(errorBannerText(workflow({ status: 'RUNNING' })), null);
  assert.equal(errorBannerText(workflow({ status: 'FAILED', error: null })), null);
});
