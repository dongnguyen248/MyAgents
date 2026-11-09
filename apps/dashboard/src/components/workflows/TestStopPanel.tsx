import { useState } from 'react';
import { replaceTestCommands, skipTests } from '../../features/workflow-monitoring';
import { escalationReasonError } from '../../lib/approvalSettings';
import { parseTestCommands, testCommandError } from '../../lib/testCommands';
import type { Workflow } from '../../types/workflow';
import { Card } from '../common/Layout';

interface Props {
  workflow: Workflow;
  onChanged: () => void;
  onCancel: () => void;
  cancelBusy: boolean;
}

type TestStopAction = 'skip-item' | 'skip-run' | 'replace';

interface FormState {
  reason: string;
  commandsText: string;
  error?: string;
  busy: TestStopAction | undefined;
  setReason: (value: string) => void;
  setCommandsText: (value: string) => void;
  setError: (error: string | undefined) => void;
  setBusy: (busy: TestStopAction | undefined) => void;
}

function useTestStopForm(workflow: Workflow): FormState {
  const initial = (workflow.waiting?.testCommands ?? []).map((argv) => argv.join(' ')).join('\n');
  const [reason, setReason] = useState('');
  const [commandsText, setCommandsText] = useState(initial);
  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState<TestStopAction | undefined>();
  return {
    reason,
    commandsText,
    error,
    busy,
    setReason,
    setCommandsText,
    setError,
    setBusy,
  };
}

interface ActParams {
  form: FormState;
  workflowId: string;
  onChanged: () => void;
}

async function runSkip(params: ActParams, scope: 'item' | 'run'): Promise<void> {
  const problem = escalationReasonError(params.form.reason);
  if (problem) {
    params.form.setError(problem);
    return;
  }
  params.form.setError(undefined);
  params.form.setBusy(scope === 'run' ? 'skip-run' : 'skip-item');
  try {
    await skipTests(params.workflowId, params.form.reason.trim(), scope);
    params.onChanged();
  } catch (err) {
    params.form.setError(err instanceof Error ? err.message : 'The action failed');
  } finally {
    params.form.setBusy(undefined);
  }
}

async function runReplace(params: ActParams): Promise<void> {
  const commands = parseTestCommands(params.form.commandsText);
  const problem = testCommandError(commands);
  if (problem) {
    params.form.setError(problem);
    return;
  }
  params.form.setError(undefined);
  params.form.setBusy('replace');
  try {
    await replaceTestCommands(params.workflowId, commands, params.form.reason.trim() || undefined);
    params.onChanged();
  } catch (err) {
    params.form.setError(err instanceof Error ? err.message : 'The action failed');
  } finally {
    params.form.setBusy(undefined);
  }
}

function TestStopFields({ form }: { form: FormState }) {
  return (
    <div className="form-grid">
      <label className="field">
        <span>Reason (required for a skip, recorded with the decision)</span>
        <input
          value={form.reason}
          onChange={(e) => form.setReason(e.target.value)}
          placeholder="Why are there no tests to run?"
          maxLength={500}
        />
      </label>
      <label className="field">
        <span>Test commands (for Replace)</span>
        <textarea
          value={form.commandsText}
          onChange={(e) => form.setCommandsText(e.target.value)}
          rows={3}
        />
        <small>
          One command per line; arguments are split on spaces, so an argument containing spaces
          cannot be entered here. The executable must be bare or relative — no absolute paths, no
          '..'.
        </small>
      </label>
    </div>
  );
}

interface ButtonsProps {
  form: FormState;
  cancelBusy: boolean;
  onSkip: (scope: 'item' | 'run') => void;
  onReplace: () => void;
  onCancel: () => void;
}

function TestStopButtons({ form, cancelBusy, onSkip, onReplace, onCancel }: ButtonsProps) {
  const disabled = form.busy !== undefined || cancelBusy;
  return (
    <div className="filters">
      <button
        type="button"
        className="btn btn-primary"
        onClick={() => onSkip('item')}
        disabled={disabled}
      >
        {form.busy === 'skip-item' ? 'Skipping…' : 'Skip tests for this item'}
      </button>
      <button type="button" className="btn" onClick={() => onSkip('run')} disabled={disabled}>
        {form.busy === 'skip-run' ? 'Skipping…' : 'Skip tests for the rest of this run'}
      </button>
      <button type="button" className="btn" onClick={onReplace} disabled={disabled}>
        {form.busy === 'replace' ? 'Replacing…' : 'Replace test command'}
      </button>
      <button type="button" className="btn" onClick={onCancel} disabled={disabled}>
        {cancelBusy ? 'Cancelling…' : 'Cancel run'}
      </button>
    </div>
  );
}

/**
 * The decision panel of a no-tests stop (TEST_ESCALATED): the test
 * step ran but collected nothing, so there is nothing for a fix to
 * repair. The operator either replaces the run's test commands and
 * retests, or skips the test step — for this item only, or, as a
 * separate explicit choice, for the rest of the run. No fix budget
 * exists at this stop and none is shown.
 */
export function TestStopPanel({ workflow, onChanged, onCancel, cancelBusy }: Props) {
  const form = useTestStopForm(workflow);
  const params: ActParams = { form, workflowId: workflow.id, onChanged };
  return (
    <Card title="No tests were collected — a decision is needed">
      {workflow.waiting?.reason ? <p>{workflow.waiting.reason}</p> : null}
      <p>
        Skipping means the run continues as if the tests had passed; no tests were collected, so
        nothing was verified by them. Skip for this item decides only the current item — the run
        stops again if a later item also collects no tests. Skip for the rest of this run records
        the decision once and applies it to every later item that collects no tests; it never
        applies to an item whose tests actually run. Every skip and its reason are recorded on the
        run and stated in the merge request.
      </p>
      <TestStopFields form={form} />
      {form.error && (
        <p className="alert" role="alert">
          {form.error}
        </p>
      )}
      <TestStopButtons
        form={form}
        cancelBusy={cancelBusy}
        onSkip={(scope) => void runSkip(params, scope)}
        onReplace={() => void runReplace(params)}
        onCancel={onCancel}
      />
    </Card>
  );
}
