// Pure-function tests for the Now card's segment, attempt,
// relative-time and quiet-hint rules (src/lib/nowActivity.ts),
// plus a source scan pinning the component's wiring to the lib.
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  MODEL_SEGMENT_TITLE,
  NOW_QUIET_HINT_MS,
  effectivePhase,
  lastActivityLine,
  nowSegments,
  phaseLabel,
  quietHint,
  relativeTime,
  showsAttempt,
} from '../src/lib/nowActivity.ts';
import type { WorkflowCurrentActivity, WorkflowWaiting } from '../src/types/workflow.ts';

const SINCE = '2026-11-12T03:00:00.000Z';
const NOW = new Date('2026-11-12T03:10:00.000Z').getTime();

function activity(partial: Partial<WorkflowCurrentActivity>): WorkflowCurrentActivity {
  return { kind: 'STEP_RUNNING', since: SINCE, ...partial };
}

function texts(segments: { text: string }[]): string[] {
  return segments.map((segment) => segment.text);
}

test('phaseLabel names every phase and nothing else', () => {
  const expected: Record<string, string> = {
    PRODUCING: 'Working',
    AI_REVIEWING: 'AI reviewing',
    WAITING_FOR_APPROVAL: 'Waiting for approval',
    RETRYING: 'Waiting to retry',
    RUNNING_TESTS: 'Running tests',
    FIXING: 'Fixing code',
    WAITING_ON_CI: 'Waiting on CI',
    WAITING_FOR_MERGE: 'Waiting for merge',
    ESCALATED: 'Escalated — needs operator',
    STALLED: 'Stalled',
    PAUSED: 'Paused by operator',
  };
  for (const [phase, label] of Object.entries(expected)) {
    assert.equal(phaseLabel(phase), label, phase);
  }
  assert.equal(phaseLabel(null), null);
  assert.equal(phaseLabel('WHATEVER'), null);
});

test('effectivePhase prefers the field and falls back to the kind', () => {
  assert.equal(effectivePhase(activity({ phase: 'FIXING', kind: 'STEP_RUNNING' })), 'FIXING');
  assert.equal(effectivePhase(activity({ kind: 'AI_REVIEW' })), 'AI_REVIEWING');
  assert.equal(effectivePhase(activity({ kind: 'APPROVAL' })), 'WAITING_FOR_APPROVAL');
  assert.equal(effectivePhase(activity({ kind: 'RETRY_WAIT' })), 'RETRYING');
  assert.equal(effectivePhase(activity({ kind: 'ESCALATED' })), 'ESCALATED');
  assert.equal(effectivePhase(activity({ kind: 'STEP_RUNNING' })), null);
});

test('segments for a producing step: agent, model with tooltip, phase', () => {
  const segments = nowSegments(
    activity({ phase: 'PRODUCING', agentName: 'Implementation Agent', model: 'claude-sonnet-5.5' }),
  );
  assert.deepEqual(texts(segments), ['Implementation Agent', 'claude-sonnet-5.5', 'Working']);
  assert.equal(segments[0].strong, true);
  assert.equal(segments[1].title, MODEL_SEGMENT_TITLE);
});

test('segments for AI reviewing carry the round as the attempt', () => {
  const segments = nowSegments(
    activity({
      kind: 'AI_REVIEW',
      phase: 'AI_REVIEWING',
      agentName: 'Artifact Review Agent',
      model: 'gpt-4.1',
      attempt: 2,
      attemptMax: 4,
    }),
  );
  assert.deepEqual(texts(segments), [
    'Artifact Review Agent',
    'gpt-4.1',
    'AI reviewing',
    'attempt 2 of 4',
  ]);
});

test('attempt never shows for approval, escalated, paused or stalled', () => {
  const waiting: WorkflowWaiting = {
    kind: 'ESCALATED',
    since: SINCE,
    suggestedActions: [],
    budget: { used: 3, max: 3 },
  };
  const human = nowSegments(
    activity({
      kind: 'APPROVAL',
      phase: 'WAITING_FOR_APPROVAL',
      attempt: 0,
      attemptMax: 3,
      reason: 'Needs a person',
    }),
  );
  assert.deepEqual(texts(human), ['Waiting for approval', 'Needs a person']);
  const escalated = nowSegments(
    activity({
      kind: 'ESCALATED',
      phase: 'ESCALATED',
      attempt: 3,
      attemptMax: 3,
      reason: 'Escalated',
    }),
    waiting,
  );
  assert.deepEqual(texts(escalated), ['Escalated — needs operator', 'Escalated', 'fix budget 3/3']);
  for (const phase of ['PAUSED', 'STALLED'] as const) {
    const segments = nowSegments(activity({ kind: phase, phase, attempt: 1, attemptMax: 3 }));
    assert.ok(!texts(segments).some((text) => text.startsWith('attempt')), phase);
  }
  assert.equal(
    showsAttempt(activity({ phase: 'WAITING_ON_CI', attempt: 5, attemptMax: 120 })),
    true,
  );
  assert.equal(
    showsAttempt(activity({ phase: 'RUNNING_TESTS', attempt: 1, attemptMax: 3 })),
    false,
  );
  assert.equal(showsAttempt(activity({ phase: 'PRODUCING' })), false);
});

test('segments for a retry lead with the phase and keep the step label', () => {
  const segments = nowSegments(
    activity({
      kind: 'RETRY_WAIT',
      phase: 'RETRYING',
      stepLabel: 'Run pipeline',
      attempt: 2,
      attemptMax: 120,
    }),
  );
  assert.deepEqual(texts(segments), ['Waiting to retry', 'Run pipeline', 'attempt 2 of 120']);
});

test('old payloads without the new fields render the step label only', () => {
  const segments = nowSegments(activity({ stepLabel: 'Break down tasks' }));
  assert.deepEqual(texts(segments), ['Break down tasks']);
  assert.equal(segments[0].strong, true);
});

test('relativeTime buckets', () => {
  const at = (secondsAgo: number) => new Date(NOW - secondsAgo * 1000).toISOString();
  assert.equal(relativeTime(at(3), NOW), 'just now');
  assert.equal(relativeTime(at(42), NOW), '42s ago');
  assert.equal(relativeTime(at(180), NOW), '3 min ago');
  assert.equal(relativeTime(at(7200), NOW), '2h ago');
  assert.equal(relativeTime(at(90000), NOW), '1d ago');
  assert.equal(relativeTime(at(-30), NOW), 'just now');
});

test('lastActivityLine uses the newest event or nothing', () => {
  assert.equal(lastActivityLine(activity({}), NOW), null);
  const line = lastActivityLine(
    activity({
      recentEvents: [
        { type: 'NOTE', message: 'first', at: '2026-11-12T03:09:00.000Z' },
        { type: 'NOTE', message: 'latest', at: '2026-11-12T03:09:30.000Z' },
      ],
    }),
    NOW,
  );
  assert.equal(line, 'latest · 30s ago');
});

test('quietHint fires only for working phases past the threshold', () => {
  assert.equal(NOW_QUIET_HINT_MS, 300_000);
  const working = activity({ phase: 'PRODUCING', agentName: 'Spec Agent' });
  assert.equal(quietHint(working, new Date(SINCE).getTime() + NOW_QUIET_HINT_MS - 1), null);
  const hint = quietHint(working, new Date(SINCE).getTime() + NOW_QUIET_HINT_MS);
  assert.ok(hint?.startsWith('No activity for'));
  assert.ok(hint?.endsWith('long model calls can take a while.'));
  // A newer last event resets the clock.
  const withEvent = activity({
    phase: 'FIXING',
    lastEventAt: '2026-11-12T03:09:30.000Z',
  });
  assert.equal(quietHint(withEvent, NOW), null);
  // Human waits, stalls and stops never earn the hint.
  for (const phase of [
    'WAITING_FOR_APPROVAL',
    'STALLED',
    'ESCALATED',
    'PAUSED',
    'RUNNING_TESTS',
  ] as const) {
    assert.equal(quietHint(activity({ phase }), NOW + 86_400_000), null, phase);
  }
  // Nor does an old payload with no derivable phase.
  assert.equal(quietHint(activity({}), NOW + 86_400_000), null);
});

test('the component renders the card from the lib and ticks locally', () => {
  const source = readFileSync(
    new URL('../src/components/workflows/RunLiveActivity.tsx', import.meta.url),
    'utf8',
  );
  assert.ok(source.includes("from '../../lib/nowActivity'"), 'imports the lib helpers');
  assert.ok(source.includes('nowSegments(activity, workflow.waiting)'), 'segments from the lib');
  assert.ok(source.includes('quietHint(activity, now)'), 'quiet hint from the lib');
  assert.ok(source.includes('lastActivityLine(activity, now)'), 'last activity from the lib');
  assert.ok(source.includes('<details'), 'collapsible recent events');
  assert.ok(source.includes('clearInterval'), 'the tick timer is cleaned up');
  assert.ok(!source.includes('agent is working'), 'the old generic line is gone');
});
