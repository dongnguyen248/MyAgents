// Tests for the run label text and for the wiring that keeps an
// older run's pending decision reachable: every run-history row
// links to that run's workflow page, and that page renders the
// escalation / test-stop panels for the run it displays.
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runLabelText } from '../src/lib/currentRun.ts';

const STARTED = '10 Nov 2026, 09:15';

test('runLabelText names the run, its start and the earlier runs', () => {
  const text = runLabelText({ id: 'abcdef1234567890', parentTaskId: null }, STARTED, 12);
  assert.equal(text, 'Run abcdef12 · started 10 Nov 2026, 09:15 · 12 earlier runs');
});

test('runLabelText uses the singular for exactly one earlier run', () => {
  const text = runLabelText({ id: 'abcdef1234567890', parentTaskId: null }, STARTED, 1);
  assert.equal(text, 'Run abcdef12 · started 10 Nov 2026, 09:15 · 1 earlier run');
});

test('runLabelText omits the count when the caller does not know it', () => {
  const text = runLabelText({ id: 'abcdef1234567890', parentTaskId: null }, STARTED);
  assert.equal(text, 'Run abcdef12 · started 10 Nov 2026, 09:15');
});

test('runLabelText names the part for a split part run', () => {
  const run = { id: 'abcdef1234567890', parentTaskId: 'task-split', splitIndex: 2 };
  const text = runLabelText(run, STARTED, 4);
  assert.equal(text, 'Part 2 · run abcdef12 · started 10 Nov 2026, 09:15 · 4 earlier runs');
});

const taskPageSource = readFileSync(
  new URL('../src/pages/Tasks/TaskDetailPage.tsx', import.meta.url),
  'utf8',
);
const workflowPageSource = readFileSync(
  new URL('../src/pages/Workflows/WorkflowDetailPage.tsx', import.meta.url),
  'utf8',
);
const escalatedPanelSource = readFileSync(
  new URL('../src/components/workflows/EscalatedPanel.tsx', import.meta.url),
  'utf8',
);

test('both detail pages render the run label next to the status', () => {
  assert.match(taskPageSource, /<RunLabel workflow=\{workflow\}/);
  assert.match(workflowPageSource, /<RunLabel workflow=\{workflow\} \/>/);
});

test('the workflow page actions target the displayed run, not the URL param', () => {
  assert.match(workflowPageSource, /retryWorkflow\(displayedRunId\)/);
  assert.match(workflowPageSource, /resumeWorkflow\(displayedRunId\)/);
  assert.match(workflowPageSource, /cancelWorkflow\(displayedRunId\)/);
  assert.doesNotMatch(workflowPageSource, /retryWorkflow\(workflowId\)/);
  assert.doesNotMatch(workflowPageSource, /resumeWorkflow\(workflowId\)/);
  assert.doesNotMatch(workflowPageSource, /cancelWorkflow\(workflowId\)/);
});

test('every run-history row links to that run, whose page shows its panels', () => {
  // The history row is a link to the run's own workflow page...
  assert.match(taskPageSource, /to=\{`\/workflows\/\$\{run\.id\}`\}/);
  // ...and that page renders the escalation panel (which delegates
  // to the test-stop panel at a no-tests stop) for the displayed
  // run, so an older run's pending decision stays reachable even
  // when a newer run is the task's current run.
  assert.match(workflowPageSource, /<EscalatedPanel/);
  assert.match(escalatedPanelSource, /TestStopPanel/);
});
