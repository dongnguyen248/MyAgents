// View-model tests for the AI review timeline (Phase 12 Stage E).
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reviewHistory, stageSummary, verdictTone } from '../src/lib/reviewViews.ts';
import type { ReviewFinding, ReviewStage, Workflow } from '../src/types/workflow.ts';

function finding(partial: Partial<ReviewFinding>): ReviewFinding {
  return {
    id: 'F-001',
    severity: 'BLOCKER',
    category: 'COMPLETENESS',
    location: '## Scope',
    problem: 'Missing.',
    requiredChange: 'Add it.',
    status: 'NEW',
    source: 'ai',
    waiverReason: null,
    ...partial,
  };
}

function stage(partial: Partial<ReviewStage>): ReviewStage {
  return { stage: 'spec', stepId: 'spec', rounds: [], ...partial };
}

function round(verdict: string | null, findings: ReviewFinding[]) {
  return {
    round: 1,
    verdict,
    reviewArtifactId: 'rev-1',
    reviewedArtifactId: 'spec-1',
    reviewedArtifactVersion: '1',
    counts: {
      BLOCKER: findings.filter((f) => f.severity === 'BLOCKER').length,
      MAJOR: findings.filter((f) => f.severity === 'MAJOR').length,
      MINOR: 0,
      NIT: 0,
    },
    summary: '',
    findings,
  };
}

function workflow(partial: Partial<Workflow>): Workflow {
  return {
    id: 'run-1',
    taskId: 'task-1',
    title: 'Task',
    projectId: 'vhpc',
    type: 'feature',
    status: 'COMPLETED',
    steps: [],
    startedAt: '2026-11-06T00:00:00Z',
    updatedAt: '2026-11-06T00:00:00Z',
    ...partial,
  } as Workflow;
}

test('verdict tones: approve ok, request-changes warn, rest neutral', () => {
  assert.equal(verdictTone('APPROVE'), 'ok');
  assert.equal(verdictTone('REQUEST_CHANGES'), 'warn');
  assert.equal(verdictTone(null), 'neutral');
  assert.equal(verdictTone('ESCALATED'), 'neutral');
});

test('stage summary counts open blockers from the LATEST round only', () => {
  const summary = stageSummary(
    stage({
      rounds: [
        round('REQUEST_CHANGES', [finding({ id: 'F-001' }), finding({ id: 'F-002' })]),
        round('REQUEST_CHANGES', [
          finding({ id: 'F-001', status: 'STILL_OPEN' }),
          finding({ id: 'F-002', status: 'RESOLVED' }),
          finding({ id: 'F-003', severity: 'MAJOR', status: 'NEW' }),
        ]),
      ],
    }),
  );
  assert.equal(summary.rounds, 2);
  assert.equal(summary.latestVerdict, 'REQUEST_CHANGES');
  assert.equal(summary.openBlockers, 1);
});

test('an empty stage summarises to zero rounds and no verdict', () => {
  assert.deepEqual(stageSummary(stage({})), { rounds: 0, latestVerdict: null, openBlockers: 0 });
});

test('review history keeps only runs with at least one reviewed stage', () => {
  const entries = reviewHistory(
    [workflow({ id: 'a' }), workflow({ id: 'b' }), workflow({ id: 'c' })],
    [
      { runId: 'a', stages: [stage({})] },
      { runId: 'b', stages: [] },
      undefined,
    ],
  );
  assert.deepEqual(entries.map((e) => e.runId), ['a']);
  assert.equal(entries[0].taskId, 'task-1');
});
