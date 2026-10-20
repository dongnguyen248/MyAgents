import { useEffect, useRef, useState } from 'react';
import * as svc from '../../services/activity/activityService';
import type { ActivityEvent, ActivityFilter } from '../../types/activity';

/**
 * Initial snapshot via listActivity, then live events via subscribeActivity.
 * The hook only sees "events arrive"; whether they come from a timer, SSE or
 * WebSocket is decided inside the API layer.
 */
export function useActivityFeed(filter: ActivityFilter = {}, live = true) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const key = JSON.stringify(filter);
  const filterRef = useRef(filter);
  filterRef.current = filter;

  useEffect(() => {
    let alive = true;
    svc.listActivity(filterRef.current).then((e) => {
      if (alive) {
        setEvents(e);
        setLoading(false);
      }
    });
    return () => {
      alive = false;
    };
  }, [key]);

  useEffect(() => {
    if (!live) return;
    return svc.subscribeActivity((e) => {
      const f = filterRef.current;
      if ((f.agentId && e.sourceId !== f.agentId) || (f.taskId && e.taskId !== f.taskId) || (f.projectId && e.projectId !== f.projectId)) return;
      setEvents((prev) => [e, ...prev].slice(0, 300));
    });
  }, [live, key]);

  return { events, loading };
}
