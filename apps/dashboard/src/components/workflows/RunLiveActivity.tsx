import type { Workflow } from '../../types/workflow';
import { clock, elapsed } from '../../utils/format';
import { Card } from '../common/Layout';

/**
 * Status strip at the top of a run's detail page: what the run is
 * doing or waiting for right now, for EVERY non-terminal state —
 * a step in flight, a scheduled retry, an approval gate, an
 * escalation, or a stall. Backed by the workflow view's
 * currentActivity/waiting, which the backend derives from state
 * the engine persists (in-flight marker, retry deadline, stage),
 * so the strip stays truthful even while a single model call runs
 * for minutes or a run sits escalated for days.
 */
export function RunLiveActivity({ workflow }: { workflow: Workflow }) {
  const activity = workflow.currentActivity;
  if (!activity || ['COMPLETED', 'FAILED', 'CANCELLED'].includes(workflow.status)) return null;
  const label = activity.stepLabel ?? activity.stage ?? 'Current step';
  const waiting = workflow.waiting;
  return (
    <Card>
      <p className="live-activity">
        <span className="live-dot" aria-hidden="true" />
        {activity.kind === 'RETRY_WAIT' ? (
          <span>
            Waiting to retry <strong>{label}</strong>
            {activity.retryAt && <> — next attempt at {clock(activity.retryAt, true)}</>}
          </span>
        ) : activity.kind === 'APPROVAL' ? (
          <span>
            <strong>Waiting for approval</strong>
            {activity.reason && <> — {activity.reason}</>} · since {clock(activity.since, true)} ({elapsed(activity.since)})
          </span>
        ) : activity.kind === 'ESCALATED' ? (
          <span>
            <strong>Escalated — needs operator</strong>
            {activity.reason && <> — {activity.reason}</>}
            {waiting?.budget && <> · fix budget {waiting.budget.used}/{waiting.budget.max}</>}
          </span>
        ) : activity.kind === 'STALLED' ? (
          <span>
            <strong>Stalled</strong>
            {activity.reason && <> — {activity.reason}</>} · last change {clock(activity.since, true)} ({elapsed(activity.since)} ago)
          </span>
        ) : (
          <span>
            <strong>{label}</strong> — agent is working · since {clock(activity.since, true)} ({elapsed(activity.since)})
          </span>
        )}
      </p>
    </Card>
  );
}
