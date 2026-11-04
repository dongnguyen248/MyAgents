import type { Workflow } from '../../types/workflow';

/**
 * Red banner stating why a run failed — the failed step plus the exact
 * error the backend recorded — so a failure is diagnosable at a glance
 * instead of by digging through the execution history.
 */
export function WorkflowErrorBanner({ workflow }: { workflow: Workflow }) {
  if (workflow.status !== 'FAILED' || !workflow.error) return null;
  const failedStep = workflow.steps.find((s) => s.state === 'failed');
  return (
    <p className="alert" role="alert">
      Failed{failedStep ? ` at ${failedStep.label}` : ''}: {workflow.error.message}{' '}
      <span className="muted small">
        ({workflow.error.code} · {workflow.error.category})
      </span>
    </p>
  );
}
