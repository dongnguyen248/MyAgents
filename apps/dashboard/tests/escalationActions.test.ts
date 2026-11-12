// Pure-function tests for the escalation panel's button/summary
// derivation and the test-command input mirror.
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  escalationButtonsFor,
  escalationSummaryFor,
  isTestStop,
  providerMessageLine,
} from '../src/lib/escalationActions.ts';
import { parseTestCommands, testCommandError } from '../src/lib/testCommands.ts';
import type { Workflow, WorkflowWaiting } from '../src/types/workflow.ts';

function workflow(partial: Partial<Workflow>): Workflow {
  return {
    id: 'run-1',
    taskId: 'task-1',
    title: 'Task',
    projectId: 'vhpc',
    type: 'feature',
    status: 'ESCALATED',
    steps: [],
    startedAt: '2026-11-09T00:00:00Z',
    updatedAt: '2026-11-09T00:00:00Z',
    ...partial,
  } as Workflow;
}

function waiting(partial: Partial<WorkflowWaiting>): WorkflowWaiting {
  return {
    kind: 'ESCALATED',
    since: '2026-11-09T00:00:00Z',
    suggestedActions: [],
    ...partial,
  };
}

test('buttons come from suggestedActions, in backend order, unknowns dropped', () => {
  assert.deepEqual(escalationButtonsFor(waiting({ suggestedActions: ['resume', 'cancel'] })), [
    'resume',
    'cancel',
  ]);
  assert.deepEqual(
    escalationButtonsFor(waiting({ suggestedActions: ['resume', 'approve', 'cancel'] })),
    ['resume', 'approve', 'cancel'],
  );
  assert.deepEqual(
    escalationButtonsFor(
      waiting({ suggestedActions: ['skip_tests', 'replace_test_commands', 'cancel'] }),
    ),
    ['skip_tests', 'replace_test_commands', 'cancel'],
  );
  assert.deepEqual(escalationButtonsFor(waiting({ suggestedActions: ['teleport'] })), []);
  assert.deepEqual(escalationButtonsFor(undefined), []);
});

test('a test stop is recognised by its skip_tests action', () => {
  const stopped = workflow({
    waiting: waiting({ suggestedActions: ['skip_tests', 'replace_test_commands', 'cancel'] }),
  });
  assert.equal(isTestStop(stopped), true);
  const fix = workflow({ waiting: waiting({ suggestedActions: ['resume', 'cancel'] }) });
  assert.equal(isTestStop(fix), false);
});

test('the test-stop summary never mentions the AI review loop', () => {
  const stopped = workflow({
    waiting: waiting({
      suggestedActions: ['skip_tests', 'replace_test_commands', 'cancel'],
      escalationReason: 'NO_TESTS',
    }),
  });
  const summary = escalationSummaryFor(stopped);
  assert.match(summary, /collected no tests/);
  assert.doesNotMatch(summary, /AI review loop/);
});

test('the review summary keeps its gate, reason and blocker wording', () => {
  const review = workflow({
    waiting: waiting({
      suggestedActions: ['resume', 'approve', 'cancel'],
      stage: 'SPEC',
      escalationReason: 'MAX_REVISIONS',
      openBlockers: 2,
    }),
  });
  assert.equal(
    escalationSummaryFor(review),
    'The AI review loop escalated this run at the Spec gate (Max Revisions) ' +
      'with 2 blocker(s) still open.',
  );
});

test('a reviewer failure summary names the error code and message', () => {
  const failed = workflow({
    waiting: waiting({
      suggestedActions: ['resume', 'cancel'],
      stage: 'PLAN',
      escalationReason: 'REVIEWER_FAILED',
      openBlockers: 0,
      errorCode: 'LLM_MODEL_NOT_SUPPORTED',
      errorMessage: "Model 'claude-sonnet-5.5' (source: shared) is not supported by the provider.",
    }),
  });
  assert.equal(
    escalationSummaryFor(failed),
    'Reviewer failed: LLM_MODEL_NOT_SUPPORTED — ' +
      "Model 'claude-sonnet-5.5' (source: shared) is not supported by the provider.",
  );
});

test('the provider line shows the provider words when the waiting block carries them', () => {
  const withProvider = waiting({
    escalationReason: 'REVIEWER_FAILED',
    errorCode: 'LLM_MODEL_NOT_SUPPORTED',
    providerMessage: 'The requested model is not supported.',
  });
  assert.equal(
    providerMessageLine(withProvider),
    'Provider: The requested model is not supported.',
  );
  assert.equal(providerMessageLine(waiting({ errorCode: 'LLM_TIMEOUT' })), null);
  assert.equal(providerMessageLine(waiting({ providerMessage: '' })), null);
  assert.equal(providerMessageLine(null), null);
  assert.equal(providerMessageLine(undefined), null);
});

test('the panel renders the provider line under the summary', () => {
  const source = readFileSync(
    new URL('../src/components/workflows/EscalatedPanel.tsx', import.meta.url),
    'utf8',
  );
  assert.ok(source.includes('providerMessageLine(workflow.waiting)'), 'panel uses the lib line');
});

test('a reviewer failure without a message names just the code', () => {
  const failed = workflow({
    waiting: waiting({
      suggestedActions: ['resume', 'cancel'],
      escalationReason: 'REVIEWER_FAILED',
      errorCode: 'LLM_TIMEOUT',
    }),
  });
  assert.equal(escalationSummaryFor(failed), 'Reviewer failed: LLM_TIMEOUT');
});

test('a reviewer failure without a cause keeps the generic wording', () => {
  const failed = workflow({
    waiting: waiting({
      suggestedActions: ['resume', 'cancel'],
      escalationReason: 'REVIEWER_FAILED',
      openBlockers: 0,
    }),
  });
  assert.equal(
    escalationSummaryFor(failed),
    'The AI review loop escalated this run (Reviewer Failed) with 0 blocker(s) still open.',
  );
});

test('an escalation without a review reason gets a neutral summary', () => {
  const fix = workflow({ waiting: waiting({ suggestedActions: ['resume', 'cancel'] }) });
  const summary = escalationSummaryFor(fix);
  assert.doesNotMatch(summary, /AI review loop/);
  assert.match(summary, /human decision/);
});

test('parseTestCommands splits lines on whitespace and skips blanks', () => {
  assert.deepEqual(parseTestCommands('python -m pytest -q\n\n  pytest -q  \n'), [
    ['python', '-m', 'pytest', '-q'],
    ['pytest', '-q'],
  ]);
  assert.deepEqual(parseTestCommands('   \n'), []);
});

test('testCommandError mirrors the backend argv rules', () => {
  assert.equal(testCommandError([['python', '-m', 'pytest', '-q']]), undefined);
  assert.equal(testCommandError([['tools/run-tests.sh']]), undefined);
  assert.equal(testCommandError([]), 'Provide at least one test command');
  assert.match(testCommandError([['C:\\tools\\pytest.exe', '-q']]) ?? '', /bare or relative/);
  assert.match(testCommandError([['/usr/bin/pytest', '-q']]) ?? '', /bare or relative/);
  assert.match(testCommandError([['py:test', '-q']]) ?? '', /bare or relative/);
  assert.match(testCommandError([['../pytest', '-q']]) ?? '', /bare or relative/);
  const many = Array.from({ length: 21 }, () => ['pytest', '-q']);
  assert.match(testCommandError(many) ?? '', /at most 20/);
});

import { readFileSync } from 'node:fs';

const panelSource = readFileSync(
  new URL('../src/components/workflows/EscalatedPanel.tsx', import.meta.url),
  'utf8',
);
const testStopSource = readFileSync(
  new URL('../src/components/workflows/TestStopPanel.tsx', import.meta.url),
  'utf8',
);

test('the escalation panel derives its buttons and delegates test stops', () => {
  assert.match(panelSource, /escalationButtonsFor\(workflow\.waiting\)/);
  assert.match(panelSource, /buttons\.includes\('resume'\)/);
  assert.match(panelSource, /buttons\.includes\('approve'\)/);
  assert.match(panelSource, /isTestStop\(workflow\)/);
  assert.match(panelSource, /TestStopPanel/);
});

test('the test-stop panel offers both skip scopes and never shows a budget', () => {
  assert.match(testStopSource, /Skip tests for this item/);
  assert.match(testStopSource, /Skip tests for the rest of this run/);
  assert.match(testStopSource, /Replace test command/);
  assert.match(testStopSource, /parseTestCommands/);
  assert.match(testStopSource, /testCommandError/);
  assert.doesNotMatch(testStopSource, /\.budget/);
});
