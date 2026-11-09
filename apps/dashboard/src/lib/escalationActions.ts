import type { Workflow, WorkflowWaiting } from '../types/workflow';

/**
 * Which decision buttons an escalated run offers, derived purely
 * from the backend's waiting.suggestedActions so the panel can
 * never offer an action the backend would reject (it used to offer
 * a fresh-budget resume and approve-anyway at every escalation,
 * including no-tests stops where both are wrong). Kept free of
 * React imports so the rules are unit-testable (tests/).
 */

export type EscalationButtonId =
  'resume' | 'approve' | 'skip_tests' | 'replace_test_commands' | 'cancel';

const KNOWN_BUTTONS: readonly string[] = [
  'resume',
  'approve',
  'skip_tests',
  'replace_test_commands',
  'cancel',
];

export function escalationButtonsFor(
  waiting: WorkflowWaiting | undefined | null,
): EscalationButtonId[] {
  if (!waiting) {
    return [];
  }
  return waiting.suggestedActions.filter((action): action is EscalationButtonId =>
    KNOWN_BUTTONS.includes(action),
  );
}

export function isTestStop(workflow: Workflow): boolean {
  return escalationButtonsFor(workflow.waiting).includes('skip_tests');
}

const TEST_STOP_SUMMARY =
  'The test step ran but collected no tests, so nothing was verified. ' +
  'That is not a code failure and no fix was attempted; the run is ' +
  'waiting for a decision about its test commands.';

/** The panel's opening line, worded for the kind of escalation. */
export function escalationSummaryFor(workflow: Workflow): string {
  if (isTestStop(workflow)) {
    return TEST_STOP_SUMMARY;
  }
  const waiting = workflow.waiting;
  const reason = waiting?.escalationReason ?? null;
  if (reason) {
    const gate = waiting?.stage ? ` at the ${displayLabel(waiting.stage)} gate` : '';
    const blockers =
      waiting?.openBlockers != null ? ` with ${waiting.openBlockers} blocker(s) still open.` : '.';
    const label = displayLabel(reason.replace('_', ' '));
    return `The AI review loop escalated this run${gate} (${label})${blockers}`;
  }
  return 'This run escalated and is waiting for a human decision.';
}

/** Mirrors utils/format.titleCase so this module stays import-free
 * for the node:test runner, which resolves value imports literally. */
function displayLabel(value: string): string {
  return value
    .toLowerCase()
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
