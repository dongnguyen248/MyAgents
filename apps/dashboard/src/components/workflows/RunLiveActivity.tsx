import type { Workflow } from '../../types/workflow';
import { clock, elapsed } from '../../utils/format';
import { Card } from '../common/Layout';

/**
 * Live strip for a running workflow: which step an agent is on right
 * now and since when. Backed by the workflow view's currentActivity,
 * which the backend derives from the run's in-flight marker — so it
 * stays truthful even while a single model call runs for minutes.
 * The detail pages re-fetch every few seconds while a run is RUNNING,
 * which is what advances the elapsed clock here.
 */
export function RunLiveActivity({ workflow }: { workflow: Workflow }) {
  const activity = workflow.currentActivity;
  if (!activity || workflow.status !== 'RUNNING') return null;
  const label = activity.stepLabel ?? activity.stage ?? 'Current step';
  return (
    <Card>
      <p className="live-activity">
        <span className="live-dot" aria-hidden="true" />
        {activity.kind === 'RETRY_WAIT' ? (
          <span>
            Waiting to retry <strong>{label}</strong>
            {activity.retryAt && <> — next attempt at {clock(activity.retryAt, true)}</>}
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
