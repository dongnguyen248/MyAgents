import { useEffect, useState } from 'react';
import { api } from '../../services/api';
import type { RunDiagnostics } from '../../types/workflow';
import { clock } from '../../utils/format';
import { Card } from '../common/Layout';

/**
 * Diagnostics panel: the backend's one-shot answer to "where is
 * this run, what is it waiting for, and why did it stop" — stage
 * and status, the wait derivation, the in-flight marker's age,
 * the fix budget, the drive's own state, the last error and the
 * most recent history events.
 */
export function WorkflowDiagnostics({ runId }: { runId: string }) {
  const [diagnostics, setDiagnostics] = useState<RunDiagnostics | undefined>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getRunDiagnostics(runId)
      .then((value) => {
        if (!cancelled) setDiagnostics(value);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (failed) return null;
  if (!diagnostics) return null;
  const d = diagnostics;
  return (
    <Card title="Diagnostics">
      <dl className="diag-grid">
        <dt>Stage</dt>
        <dd>
          {d.stage} <span className="muted">({d.stageKind})</span> · status {d.status}
        </dd>
        <dt>Waiting</dt>
        <dd>
          {d.waiting.kind}
          {d.waiting.reason && <> — {d.waiting.reason}</>}
          {d.waiting.retryAt && <> · retry at {clock(d.waiting.retryAt, true)}</>}
        </dd>
        <dt>In flight</dt>
        <dd>
          {d.inFlight ? `yes — ${Math.round(d.inFlight.ageSeconds)}s` : 'no'}
        </dd>
        <dt>Fix budget</dt>
        <dd>
          {d.fixBudget.used}/{d.fixBudget.max} used
        </dd>
        <dt>Driver</dt>
        <dd>
          {d.driver.alive ? 'alive' : 'not driving'}
          {d.driver.lastTickAt && <> · last tick {clock(d.driver.lastTickAt, true)}</>}
          {d.driver.lastStopReason && <> · last stop: {d.driver.lastStopReason}</>}
        </dd>
        {d.lastError && (
          <>
            <dt>Last error</dt>
            <dd>
              {d.lastError.code} — {d.lastError.message}{' '}
              <span className="muted">
                ({d.lastError.category}
                {d.lastError.retryable ? ', retryable' : ''})
              </span>
            </dd>
          </>
        )}
        {d.suggestedActions.length > 0 && (
          <>
            <dt>Suggested</dt>
            <dd>{d.suggestedActions.join(' · ')}</dd>
          </>
        )}
      </dl>
      {d.lastEvents.length > 0 && (
        <details>
          <summary>Last {d.lastEvents.length} events</summary>
          <ul className="diag-events">
            {d.lastEvents.map((event, index) => (
              <li key={index}>
                <time>{clock(event.at, true)}</time> {event.type} — {event.message}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}
