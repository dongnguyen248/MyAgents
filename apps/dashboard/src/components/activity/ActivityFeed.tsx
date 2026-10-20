import { Link } from 'react-router-dom';
import type { ActivityEvent, ActivityLevel } from '../../types/activity';
import { clock } from '../../utils/format';
import { EmptyState } from '../common/Layout';

const LEVEL: Record<ActivityLevel, [string, string]> = {
  info: ['•', 'Info'],
  success: ['✓', 'Success'],
  warn: ['!', 'Warning'],
  error: ['✕', 'Error'],
};

export function ActivityFeed({ events, showTask = true }: { events: ActivityEvent[]; showTask?: boolean }) {
  if (!events.length) return <EmptyState>No events recorded.</EmptyState>;
  return (
    <ul className="feed" aria-live="off">
      {events.map((e) => {
        const [icon, label] = LEVEL[e.level];
        return (
          <li key={e.id} className={`feed-item feed-${e.level}`}>
            <time dateTime={e.timestamp} className="feed-time">{clock(e.timestamp, true)}</time>
            <span className="feed-level" title={label}><span aria-hidden="true">{icon}</span><span className="sr-only">{label}</span></span>
            <div>
              <div className="feed-source">{e.sourceLabel}</div>
              <div>
                {e.message}
                {showTask && e.taskId && <> · <Link to={`/tasks/${e.taskId}`}>{e.taskId}</Link></>}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
