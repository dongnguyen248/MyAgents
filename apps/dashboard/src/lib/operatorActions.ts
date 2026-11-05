import type { Workflow } from '../types/workflow';

/**
 * The operator control cluster for a run, chosen purely from the
 * run's status and waiting state. Kept free of React imports so
 * the selection rules can be unit-tested directly (tests/).
 *
 * - ESCALATED: resume with a fresh fix budget (reason required) or
 *   fail the run under operator control.
 * - STALLED (waiting kind): recover (replay the interrupted step,
 *   or mark it failed) and restart the driver.
 * - PAUSED: continue or cancel.
 * - FAILED: resume from the failed step, or run again fresh.
 * - Any other live run: pause and cancel.
 * Terminal runs have no operator actions.
 */
export type OperatorActionId =
  | 'resume-escalation'
  | 'fail-run'
  | 'recover-replay'
  | 'recover-fail'
  | 'restart-driver'
  | 'pause'
  | 'continue'
  | 'cancel'
  | 'resume-failed'
  | 'run-again';

export interface OperatorAction {
  id: OperatorActionId;
  label: string;
  /** Dangerous actions render in the danger style and confirm first. */
  danger?: boolean;
  /** The action needs an operator reason (sent to the audit event). */
  needsReason?: boolean;
  /** Ask for an explicit confirmation before running the action. */
  confirm?: string;
}

const CANCEL: OperatorAction = {
  id: 'cancel',
  label: 'Cancel run',
  danger: true,
  confirm:
    'Cancel this run permanently? It cannot be resumed afterwards — you can Run again from scratch, and this run stays as the record. A step already in progress finishes first.',
};

export function operatorActionsFor(workflow: Workflow): OperatorAction[] {
  const { status } = workflow;
  if (status === 'COMPLETED' || status === 'CANCELLED') return [];
  if (status === 'ESCALATED') {
    return [
      { id: 'resume-escalation', label: 'Resume with new fix budget', needsReason: true },
      {
        id: 'fail-run',
        label: 'Fail run',
        danger: true,
        needsReason: true,
        confirm:
          'Fail this run? It ends as Failed with your reason recorded, and can then be resumed from the failed step with a reset fix budget.',
      },
      CANCEL,
    ];
  }
  if (status === 'PAUSED') {
    return [{ id: 'continue', label: 'Continue' }, CANCEL];
  }
  if (status === 'FAILED') {
    return [
      { id: 'resume-failed', label: 'Resume from failure' },
      { id: 'run-again', label: 'Run again' },
    ];
  }
  if (workflow.waiting?.kind === 'STALLED') {
    return [
      { id: 'recover-replay', label: 'Recover — replay interrupted step', needsReason: true },
      {
        id: 'recover-fail',
        label: 'Recover — mark failed',
        danger: true,
        needsReason: true,
        confirm: 'Mark the interrupted step as failed? The run ends as Failed and can be resumed from there.',
      },
      { id: 'restart-driver', label: 'Restart driver' },
      CANCEL,
    ];
  }
  // RUNNING, WAITING_APPROVAL, WAITING_RETRY.
  return [{ id: 'pause', label: 'Pause' }, CANCEL];
}

/** The latest review/test findings an operator should see before
 * granting an escalated run a fresh fix budget. */
export function latestFindingsSummary(workflow: Workflow): string | undefined {
  const artifacts = workflow.artifacts ?? [];
  for (const type of ['CODE_REVIEW', 'TEST_REPORT']) {
    const artifact = [...artifacts].reverse().find((a) => a.type === type && a.content);
    if (artifact?.content) {
      const text = artifact.content.trim();
      return text.length > 600 ? `${text.slice(0, 600)}…` : text;
    }
  }
  return undefined;
}
