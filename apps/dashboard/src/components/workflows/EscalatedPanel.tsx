import { useState } from 'react';
import { approveEscalation, resumeEscalation } from '../../features/workflow-monitoring';
import { escalationReasonError } from '../../lib/approvalSettings';
import type { Workflow } from '../../types/workflow';
import { Card } from '../common/Layout';
import { titleCase } from '../../utils/format';

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
  const waiting = workflow.waiting;
  const reason = waiting?.escalationReason ?? null;
  const blockers = waiting?.openBlockers ?? null;
  return (
    <p>
      The AI review loop escalated this run
      {waiting?.stage ? ` at the ${titleCase(waiting.stage)} gate` : ''}
      {reason ? (
        <>
          {' '}
          (<strong>{titleCase(reason.replace('_', ' '))}</strong>)
        </>
      ) : null}
      {blockers !== null ? ` with ${blockers} blocker(s) still open.` : '.'}
    </p>
  );
}

interface FieldsProps {
  reason: string;
  guidance: string;
  onReason: (value: string) => void;
  onGuidance: (value: string) => void;
}

function EscalationFields({ reason, guidance, onReason, onGuidance }: FieldsProps) {
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
      <label className="field">
        <span>Guidance for the producer (optional, resume only)</span>
        <input
          value={guidance}
          onChange={(e) => onGuidance(e.target.value)}
          placeholder="What should the agent do differently?"
          maxLength={4000}
        />
      </label>
    </div>
  );
}

interface ButtonsProps {
  busy: EscalationAction | undefined;
  cancelBusy: boolean;
  onAct: (action: EscalationAction) => void;
  onCancel: () => void;
}

function EscalationButtons({ busy, cancelBusy, onAct, onCancel }: ButtonsProps) {
  const disabled = busy !== undefined || cancelBusy;
  return (
    <div className="filters">
      <button
        type="button"
        className="btn btn-primary"
        onClick={() => onAct('resume')}
        disabled={disabled}
      >
        {busy === 'resume' ? 'Resuming…' : 'Resume with a fresh budget'}
      </button>
      <button type="button" className="btn" onClick={() => onAct('approve')} disabled={disabled}>
        {busy === 'approve' ? 'Approving…' : 'Approve anyway'}
      </button>
      <button type="button" className="btn" onClick={onCancel} disabled={disabled}>
        {cancelBusy ? 'Cancelling…' : 'Cancel run'}
      </button>
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
  form: EscalationForm;
  cancelBusy: boolean;
  onAct: (action: EscalationAction) => void;
  onCancel: () => void;
}

function EscalationBody({ form, cancelBusy, onAct, onCancel }: BodyProps) {
  return (
    <>
      <EscalationFields
        reason={form.reason}
        guidance={form.guidance}
        onReason={form.setReason}
        onGuidance={form.setGuidance}
      />
      {form.error && (
        <p className="alert" role="alert">
          {form.error}
        </p>
      )}
      <EscalationButtons
        busy={form.busy}
        cancelBusy={cancelBusy}
        onAct={onAct}
        onCancel={onCancel}
      />
    </>
  );
}

/**
 * The decision panel of an escalated run (Phase 12): why the AI
 * review loop gave up, how many blockers are still open, and the
 * three human ways out — resume with a fresh budget (optionally
 * guiding the producer), approve the artifact anyway, or cancel.
 * Both actions need a reason; it lands in the run's audit trail.
 */
export function EscalatedPanel({ workflow, onChanged, onCancel, cancelBusy }: Props) {
  const form = useEscalationForm();
  if (workflow.status !== 'ESCALATED') {
    return null;
  }
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
      <EscalationBody form={form} cancelBusy={cancelBusy} onAct={act} onCancel={onCancel} />
    </Card>
  );
}
