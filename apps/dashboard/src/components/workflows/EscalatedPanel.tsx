import { useState } from 'react';
import { approveEscalation, resumeEscalation } from '../../features/workflow-monitoring';
import { escalationReasonError } from '../../lib/approvalSettings';
import {
  escalationButtonsFor,
  escalationSummaryFor,
  isTestStop,
  type EscalationButtonId,
} from '../../lib/escalationActions';
import type { Workflow } from '../../types/workflow';
import { Card } from '../common/Layout';
import { TestStopPanel } from './TestStopPanel';

interface Props {
  workflow: Workflow;
  onChanged: () => void;
  onCancel: () => void;
  cancelBusy: boolean;
}

type EscalationAction = 'resume' | 'approve';

interface ActParams {
  action: EscalationAction;
  workflowId: string;
  reason: string;
  guidance: string;
  onChanged: () => void;
  setError: (error: string | undefined) => void;
  setBusy: (busy: EscalationAction | undefined) => void;
}

async function runEscalationAction(params: ActParams): Promise<void> {
  const problem = escalationReasonError(params.reason);
  if (problem) {
    params.setError(problem);
    return;
  }
  params.setError(undefined);
  params.setBusy(params.action);
  try {
    if (params.action === 'resume') {
      await resumeEscalation(
        params.workflowId,
        params.reason.trim(),
        params.guidance.trim() || undefined,
      );
    } else {
      await approveEscalation(params.workflowId, params.reason.trim());
    }
    params.onChanged();
  } catch (err) {
    params.setError(err instanceof Error ? err.message : 'The action failed');
  } finally {
    params.setBusy(undefined);
  }
}

function EscalationSummary({ workflow }: { workflow: Workflow }) {
  return <p>{escalationSummaryFor(workflow)}</p>;
}

interface FieldsProps {
  reason: string;
  guidance: string;
  showGuidance: boolean;
  onReason: (value: string) => void;
  onGuidance: (value: string) => void;
}

function EscalationFields({ reason, guidance, showGuidance, onReason, onGuidance }: FieldsProps) {
  return (
    <div className="form-grid">
      <label className="field">
        <span>Reason (required, recorded with the decision)</span>
        <input
          value={reason}
          onChange={(e) => onReason(e.target.value)}
          placeholder="Why are you resuming / approving?"
          maxLength={500}
        />
      </label>
      {showGuidance ? (
        <label className="field">
          <span>Guidance for the producer (optional, resume only)</span>
          <input
            value={guidance}
            onChange={(e) => onGuidance(e.target.value)}
            placeholder="What should the agent do differently?"
            maxLength={4000}
          />
        </label>
      ) : null}
    </div>
  );
}

interface ButtonsProps {
  buttons: EscalationButtonId[];
  busy: EscalationAction | undefined;
  cancelBusy: boolean;
  onAct: (action: EscalationAction) => void;
  onCancel: () => void;
}

function EscalationButtons({ buttons, busy, cancelBusy, onAct, onCancel }: ButtonsProps) {
  const disabled = busy !== undefined || cancelBusy;
  return (
    <div className="filters">
      {buttons.includes('resume') ? (
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => onAct('resume')}
          disabled={disabled}
        >
          {busy === 'resume' ? 'Resuming…' : 'Resume with a fresh budget'}
        </button>
      ) : null}
      {buttons.includes('approve') ? (
        <button type="button" className="btn" onClick={() => onAct('approve')} disabled={disabled}>
          {busy === 'approve' ? 'Approving…' : 'Approve anyway'}
        </button>
      ) : null}
      {buttons.includes('cancel') ? (
        <button type="button" className="btn" onClick={onCancel} disabled={disabled}>
          {cancelBusy ? 'Cancelling…' : 'Cancel run'}
        </button>
      ) : null}
    </div>
  );
}

interface EscalationForm {
  reason: string;
  guidance: string;
  error?: string;
  busy: EscalationAction | undefined;
  setReason: (value: string) => void;
  setGuidance: (value: string) => void;
  setError: (error: string | undefined) => void;
  setBusy: (busy: EscalationAction | undefined) => void;
}

function useEscalationForm(): EscalationForm {
  const [reason, setReason] = useState('');
  const [guidance, setGuidance] = useState('');
  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState<EscalationAction | undefined>();
  return { reason, guidance, error, busy, setReason, setGuidance, setError, setBusy };
}

interface BodyProps {
  workflow: Workflow;
  form: EscalationForm;
  cancelBusy: boolean;
  onAct: (action: EscalationAction) => void;
  onCancel: () => void;
}

function EscalationBody({ workflow, form, cancelBusy, onAct, onCancel }: BodyProps) {
  const buttons = escalationButtonsFor(workflow.waiting);
  return (
    <>
      <EscalationFields
        reason={form.reason}
        guidance={form.guidance}
        showGuidance={buttons.includes('resume')}
        onReason={form.setReason}
        onGuidance={form.setGuidance}
      />
      {form.error && (
        <p className="alert" role="alert">
          {form.error}
        </p>
      )}
      <EscalationButtons
        buttons={buttons}
        busy={form.busy}
        cancelBusy={cancelBusy}
        onAct={onAct}
        onCancel={onCancel}
      />
    </>
  );
}

/**
 * The decision panel of an escalated run. The buttons are derived
 * from the backend's waiting.suggestedActions, so the panel only
 * ever offers actions this kind of escalation actually accepts: a
 * fresh-budget resume for fix and review escalations, approve
 * anyway only at approval gates, and — for a no-tests stop — the
 * dedicated test panel instead of this one. Both generic actions
 * need a reason; it lands in the run's audit trail.
 */
export function EscalatedPanel({ workflow, onChanged, onCancel, cancelBusy }: Props) {
  if (workflow.status !== 'ESCALATED') {
    return null;
  }
  if (isTestStop(workflow)) {
    return (
      <TestStopPanel
        workflow={workflow}
        onChanged={onChanged}
        onCancel={onCancel}
        cancelBusy={cancelBusy}
      />
    );
  }
  return (
    <GenericEscalationPanel
      workflow={workflow}
      onChanged={onChanged}
      onCancel={onCancel}
      cancelBusy={cancelBusy}
    />
  );
}

function GenericEscalationPanel({ workflow, onChanged, onCancel, cancelBusy }: Props) {
  const form = useEscalationForm();
  const act = (action: EscalationAction) =>
    runEscalationAction({
      action,
      workflowId: workflow.id,
      reason: form.reason,
      guidance: form.guidance,
      onChanged,
      setError: form.setError,
      setBusy: form.setBusy,
    });
  return (
    <Card title="Escalated — a human decision is needed">
      <EscalationSummary workflow={workflow} />
      <EscalationBody
        workflow={workflow}
        form={form}
        cancelBusy={cancelBusy}
        onAct={act}
        onCancel={onCancel}
      />
    </Card>
  );
}
