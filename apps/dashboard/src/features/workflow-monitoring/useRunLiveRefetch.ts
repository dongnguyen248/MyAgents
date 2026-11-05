import { useEffect, useRef } from 'react';
import { subscribeActivity } from '../../services/activity/activityService';

/**
 * Keeps a detail page fresh while its run is live — without polling.
 *
 * The page refetches when the activity stream reports an event for
 * the run's task (the stream's events carry taskId, which is exactly
 * the granularity the detail pages render). A 30-second watchdog is
 * the fallback for a dead stream: it refetches only when no stream
 * event of any kind has arrived for a full interval, which is what
 * "the SSE connection is down" looks like from here (EventSource
 * reconnects silently and reports nothing when it gives up).
 */
export function useRunLiveRefetch(
  taskId: string | undefined,
  active: boolean,
  reload: () => void,
) {
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  const lastStreamEventAt = useRef(0);

  useEffect(() => {
    if (!active) return;
    lastStreamEventAt.current = Date.now();
    const unsubscribe = subscribeActivity((event) => {
      lastStreamEventAt.current = Date.now();
      if (taskId && event.taskId === taskId) reloadRef.current();
    });
    const watchdog = setInterval(() => {
      if (Date.now() - lastStreamEventAt.current >= 30_000) {
        reloadRef.current();
      }
    }, 30_000);
    return () => {
      unsubscribe();
      clearInterval(watchdog);
    };
  }, [taskId, active]);
}
