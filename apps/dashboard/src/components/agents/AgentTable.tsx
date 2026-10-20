import { Link } from 'react-router-dom';
import type { Agent } from '../../types/agent';
import { duration, pct } from '../../utils/format';
import { HealthMeter } from '../common/Layout';
import { AgentStatusBadge } from './AgentStatusBadge';

export function AgentTable({ agents }: { agents: Agent[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">AI agents and their current state</caption>
        <thead>
          <tr>
            <th scope="col">Agent</th>
            <th scope="col">Status</th>
            <th scope="col">Current task</th>
            <th scope="col" className="num">Running</th>
            <th scope="col" className="num">Completed</th>
            <th scope="col" className="num">Failed</th>
            <th scope="col" className="num">Success</th>
            <th scope="col" className="num">Avg duration</th>
            <th scope="col">Health</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((a) => (
            <tr key={a.id}>
              <th scope="row">
                <Link to={`/agents/${a.id}`}>{a.name}</Link>
                <div className="muted small">{a.model}</div>
              </th>
              <td><AgentStatusBadge status={a.status} /></td>
              <td>{a.currentTaskId ? <Link to={`/tasks/${a.currentTaskId}`}>{a.currentTaskId}</Link> : <span className="muted">–</span>}</td>
              <td className="num">{a.metrics.running}</td>
              <td className="num">{a.metrics.completed}</td>
              <td className="num">{a.metrics.failed}</td>
              <td className="num">{pct(a.metrics.successRate, 0)}</td>
              <td className="num">{duration(a.metrics.avgDurationSec)}</td>
              <td><HealthMeter score={a.metrics.healthScore} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
