import type { StepState, WorkflowStep } from '../../types/workflow';

const ICON: Record<StepState, [string, string]> = {
  done: ['✓', 'Done'],
  active: ['●', 'In progress'],
  pending: ['○', 'Pending'],
  rejected: ['✕', 'Rejected'],
  failed: ['✕', 'Failed'],
  cancelled: ['⊘', 'Cancelled'],
  skipped: ['»', 'Skipped'],
  escalated: ['⚠', 'Escalated'],
};

/** Vertical = full timeline (detail pages). Compact = one-line chips (lists). */
export function WorkflowStepper({ steps, compact }: { steps: WorkflowStep[]; compact?: boolean }) {
  return (
    <ol className={compact ? 'stepper compact' : 'stepper'} aria-label="Workflow progress">
      {steps.map((s) => {
        const [icon, text] = ICON[s.state];
        return (
          <li key={s.id} className={`step step-${s.state}`}>
            <span className="step-icon" aria-hidden="true">{icon}</span>
            <span className="step-label">{s.label}</span>
            <span className={compact ? 'sr-only' : 'step-state'}>{text}</span>
          </li>
        );
      })}
    </ol>
  );
}
