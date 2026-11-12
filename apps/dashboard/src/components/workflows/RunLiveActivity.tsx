import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { lastActivityLine, nowSegments, quietHint, relativeTime } from '../../lib/nowActivity';
import type { NowSegment } from '../../lib/nowActivity';
import type { Workflow, WorkflowCurrentActivity } from '../../types/workflow';
import { clock, elapsed } from '../../utils/format';
import { Card } from '../common/Layout';

/**
 * The "Now" card at the top of a run's detail page: who is acting,
 * with which model, in which phase, on which attempt, and what the
 * run did last — for EVERY non-terminal state. Backed by the
 * workflow view's currentActivity/waiting, which the backend
 * derives from persisted state, so the card stays truthful while a
 * single model call runs for minutes or a run sits escalated for
 * days. Elapsed and relative times tick locally (1s) without
 * refetching; the timer stops when the card unmounts or the run
 * turns terminal.
 */
export function RunLiveActivity({ workflow }: { workflow: Workflow }) {
  const activity = workflow.currentActivity;
  const terminal = ['COMPLETED', 'FAILED', 'CANCELLED'].includes(workflow.status);
  const now = useNow(Boolean(activity) && !terminal);
  if (!activity || terminal) {
    return null;
  }
  const segments = nowSegments(activity, workflow.waiting);
  const events = activity.recentEvents ?? [];
  const lastLine = lastActivityLine(activity, now);
  const hint = quietHint(activity, now);
  return (
    <Card>
      <p className="live-activity">
        <span className="live-dot" aria-hidden="true" />
        <span>
          {segments.map((segment, index) => (
            <Segment key={index} segment={segment} first={index === 0} />
          ))}
          <TimeNote activity={activity} />
        </span>
      </p>
      {lastLine && <p className="live-last-activity">{lastLine}</p>}
      {hint && <p className="live-quiet-hint">{hint}</p>}
      {events.length > 1 && (
        <details className="live-events">
          <summary>Recent activity ({events.length})</summary>
          <ul>
            {events.map((event, index) => (
              <li key={index}>
                {event.message} · {relativeTime(event.at, now)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

const TICK_MS = 1000;

/** A locally ticking clock for elapsed/relative times. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) {
      return undefined;
    }
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

function Segment({ segment, first }: { segment: NowSegment; first: boolean }): ReactNode {
  const body = segment.strong ? (
    <strong title={segment.title}>{segment.text}</strong>
  ) : (
    <span title={segment.title}>{segment.text}</span>
  );
  return (
    <>
      {!first && ' · '}
      {body}
    </>
  );
}

/** The trailing time text each kind has always shown. */
function TimeNote({ activity }: { activity: WorkflowCurrentActivity }): ReactNode {
  if (activity.kind === 'STALLED') {
    return (
      <>
        {' '}
        · last change {clock(activity.since, true)} ({elapsed(activity.since)} ago)
      </>
    );
  }
  if (activity.kind === 'RETRY_WAIT') {
    if (!activity.retryAt) {
      return null;
    }
    return <> — next attempt at {clock(activity.retryAt, true)}</>;
  }
  if (activity.kind === 'ESCALATED' || activity.kind === 'PAUSED') {
    return null;
  }
  return (
    <>
      {' '}
      · since {clock(activity.since, true)} ({elapsed(activity.since)})
    </>
  );
}
