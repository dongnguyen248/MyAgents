import { useState } from 'react';
import type { Workflow } from '../../types/workflow';
import {
  latestFindingsSummary,
  operatorActionsFor,
  type OperatorAction,
} from '../../lib/operatorActions';
import {
  continueWorkflow,
  driveWorkflow,
  failWorkflow,
  pauseWorkflow,
  recoverWorkflow,
  resumeEscalation,
} from '../../features/workflow-monitoring';
import { Card } from '../common/Layout';

interface OperatorControlsProps {
  workflow: Workflow;
  onChanged: () => void;
  /** FAILED-state actions stay wired to the page (they navigate). */
  onResumeFailed: () => void;
  onRunAgain: () => void;
  resumeBusy: boolean;
  runAgainBusy: boolean;
  /** Cancel runs through the page's handler (mid-step semantics). */
  onCancel: () => void;
  cancelBusy: boolean;
}

/**
 * The operator control cluster: exactly the actions that make
 * sense for the run's current state (see lib/operatorActions).
 * Reason-bearing and dangerous actions ask first, inline.
 */
export function OperatorControls({
  workflow,
  onChanged,
  onResumeFailed,
  onRunAgain,
  resumeBusy,
  runAgainBusy,
  onCancel,
  cancelBusy,
}: OperatorControlsProps) {
  const [selected, setSelected] = useState<OperatorAction | undefined>();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const actions = operatorActionsFor(workflow);
  if (actions.length === 0) return null;

  const findings =
    workflow.status === 'ESCALATED' ? latestFindingsSummary(workflow) : undefined;

  const run = async (action: OperatorAction) => {
    if (action.id === 'resume-failed') return onResumeFailed();
    if (action.id === 'run-again') return onRunAgain();
    if (action.id === 'cancel') return onCancel();
    setBusy(true);
    setError(undefined);
    try {
      switch (action.id) {
        case 'resume-escalation':
          await resumeEscalation(workflow.id, reason.trim());
          break;
        case 'fail-run':
          await failWorkflow(workflow.id, reason.trim());
          break;
        case 'recover-replay':
          await recoverWorkflow(workflow.id, reason.trim(), true);
          break;
        case 'recover-fail':
          await recoverWorkflow(workflow.id, reason.trim(), false);
          break;
        case 'restart-driver':
          await driveWorkflow(workflow.id);
          break;
        case 'pause':
          await pauseWorkflow(workflow.id);
          break;
        case 'continue':
          await continueWorkflow(workflow.id);
          break;
      }
      setSelected(undefined);
      setReason('');
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed');
    } finally {
      setBusy(false);
    }
  };

  const needsPrompt = (action: OperatorAction) =>
    Boolean(action.needsReason || action.confirm);

  return (
    <Card title="Operator controls">
      {findings && (
        <div className="stack">
          <p className="muted small">
            Latest review/test findings — the run escalated after these:
          </p>
          <pre className="artifact-content">{findings}</pre>
        </div>
      )}
      {workflow.status === 'FAILED' && (
        <p className="muted small">
          Resume keeps the approved spec, plan and task breakdown and re-runs only the
          failed step — a run that died in the fix loop gets a fresh fix budget. Run
          again starts over from the spec; either way this failed run stays as the
          record.
        </p>
      )}
      {selected ? (
        <div className="stack">
          {selected.confirm && <p className="muted small">{selected.confirm}</p>}
          {selected.needsReason && (
            <label className="stack">
              <span className="small">Reason (recorded in the run's audit events)</span>
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                maxLength={500}
                rows={2}
                placeholder="Why are you doing this?"
              />
            </label>
          )}
          <div className="filters">
            <button
              type="button"
              className={selected.danger ? 'btn btn-danger' : 'btn btn-primary'}
              disabled={busy || cancelBusy || (selected.needsReason && !reason.trim())}
              onClick={() => void run(selected)}
            >
              {busy ? 'Working…' : `Yes, ${selected.label.toLowerCase()}`}
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => setSelected(undefined)}
            >
              Back
            </button>
          </div>
        </div>
      ) : (
        <div className="filters">
          {actions.map((action) => (
            <button
              key={action.id}
              type="button"
              className={action.danger ? 'btn btn-danger' : 'btn'}
              disabled={
                busy ||
                (action.id === 'resume-failed' && (resumeBusy || runAgainBusy)) ||
                (action.id === 'run-again' && (resumeBusy || runAgainBusy)) ||
                (action.id === 'cancel' && cancelBusy)
              }
              onClick={() => (needsPrompt(action) ? setSelected(action) : void run(action))}
            >
              {action.id === 'resume-failed' && resumeBusy
                ? 'Resuming…'
                : action.id === 'run-again' && runAgainBusy
                  ? 'Starting…'
                  : action.id === 'cancel' && cancelBusy
                    ? 'Cancelling…'
                    : action.label}
            </button>
          ))}
        </div>
      )}
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
    </Card>
  );
}
