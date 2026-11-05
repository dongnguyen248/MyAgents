import { Link } from 'react-router-dom';
import type { Task } from '../../types/task';
import { ago, duration, titleCase } from '../../utils/format';
import { CiBadge } from '../common/Badge';
import { EmptyState } from '../common/Layout';
import { TaskStatusBadge } from './TaskStatusBadge';

export function TaskTable({ tasks, agentNames }: { tasks: Task[]; agentNames: Record<string, string> }) {
  if (!tasks.length) return <EmptyState>No tasks match the current filters.</EmptyState>;
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Tasks</caption>
        <thead>
          <tr>
            <th scope="col">Task</th>
            <th scope="col">Project</th>
            <th scope="col">Status</th>
            <th scope="col">Agent</th>
            <th scope="col">Workflow</th>
            <th scope="col">Priority</th>
            <th scope="col">CI</th>
            <th scope="col" className="num">Revisions</th>
            <th scope="col">Updated</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => (
            <tr key={t.id}>
              <th scope="row">
                <Link to={`/tasks/${t.id}`}>{t.id}</Link>
                <div className="small">{t.title}</div>
                {t.isSplitParent && (
                  <div className="muted small">Split task · {t.splitCompleted}/{t.splitTotal} parts completed</div>
                )}
              </th>
              <td>{t.projectId.toUpperCase()}</td>
              <td><TaskStatusBadge status={t.status} /></td>
              <td>{t.assignedAgentId ? agentNames[t.assignedAgentId] ?? t.assignedAgentId : <span className="muted">–</span>}</td>
              <td>{titleCase(t.workflowType)}</td>
              <td>{titleCase(t.priority)}</td>
              <td><CiBadge status={t.ci} /></td>
              <td className="num">{t.revisions}</td>
              <td title={t.durationSec ? `Took ${duration(t.durationSec)}` : undefined}>{ago(t.updatedAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
