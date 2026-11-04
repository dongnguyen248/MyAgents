import type { Workflow } from '../../types/workflow';

/** Flatten an error's structured details into short readable lines. */
function detailLines(details: Record<string, unknown>): string[] {
  const lines: string[] = [];
  for (const [key, value] of Object.entries(details)) {
    if (typeof value === 'string') {
      lines.push(`${key}: ${value}`);
    } else if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === 'string') {
          lines.push(`${key}: ${item}`);
        } else if (item && typeof item === 'object') {
          const record = item as Record<string, unknown>;
          const path = typeof record.path === 'string' ? record.path : '';
          const why = [record.operation, record.reason ?? record.issue]
            .filter((part) => typeof part === 'string')
            .join(' — ');
          lines.push(`${key}: ${path}${why ? ` (${why})` : ''}`);
        }
      }
    }
  }
  return lines.slice(0, 6);
}

/**
 * Red banner stating why a run failed — the failed step plus the exact
 * error the backend recorded — so a failure is diagnosable at a glance
 * instead of by digging through the execution history.
 */
export function WorkflowErrorBanner({ workflow }: { workflow: Workflow }) {
  if (workflow.status !== 'FAILED' || !workflow.error) return null;
  const failedStep = workflow.steps.find((s) => s.state === 'failed');
  const lines = workflow.error.details ? detailLines(workflow.error.details) : [];
  return (
    <p className="alert" role="alert">
      Failed{failedStep ? ` at ${failedStep.label}` : ''}: {workflow.error.message}{' '}
      <span className="muted small">
        ({workflow.error.code} · {workflow.error.category})
      </span>
      {lines.length > 0 && (
        <span className="small">
          {lines.map((line) => (
            <span key={line}>
              <br />
              {line}
            </span>
          ))}
        </span>
      )}
    </p>
  );
}
