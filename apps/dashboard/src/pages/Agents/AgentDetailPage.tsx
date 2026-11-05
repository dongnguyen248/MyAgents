import { Link, useParams } from 'react-router-dom';
import { ActivityFeed } from '../../components/activity/ActivityFeed';
import { AgentCounters } from '../../components/agents/AgentCounters';
import { AgentStatusBadge } from '../../components/agents/AgentStatusBadge';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader, Stat } from '../../components/common/Layout';
import { useAgentDetail } from '../../features/agent-management';
import { clock, dateTime, duration, elapsed, ago, titleCase } from '../../utils/format';

export function AgentDetailPage() {
  const { agentId = '' } = useParams();
  const detail = useAgentDetail(agentId);
  return (
    <AsyncView {...detail}>
      {({ agent, runs, events }) =>
        !agent ? (
          <p className="muted">Agent not found.</p>
        ) : (
          <>
            <PageHeader
              title={agent.name}
              subtitle={agent.statusDetail}
              back={{ to: '/agents', label: 'Agents' }}
              actions={<><AgentStatusBadge status={agent.status} /><Link className="btn" to={`/agents/${agent.id}/settings`}>Configuration</Link></>}
            />
            <div className="grid two-col">
              <Card title="Agent information">
                <dl className="stats stats-2">
                  <Stat label="Type" value={titleCase(agent.type)} />
                  <Stat label="Version" value={agent.version} />
                  <Stat label="Model" value={agent.model} />
                  <Stat label="Skills" value={agent.skills?.length ? agent.skills.join(', ') : '–'} />
                  <Stat label="Current project" value={agent.currentProjectId?.toUpperCase() ?? '–'} />
                  <Stat label="Started at" value={agent.startedAt ? clock(agent.startedAt) : '–'} />
                  <Stat label="Last activity" value={ago(agent.lastActivityAt)} />
                </dl>
              </Card>
              <Card title="Current task">
                {agent.currentTaskId && agent.startedAt ? (
                  <>
                    <p><Link to={`/tasks/${agent.currentTaskId}`}><strong>{agent.currentTaskId}</strong></Link></p>
                    <p>“{agent.currentTaskTitle}”</p>
                    <dl className="stats stats-2">
                      <Stat label="Started" value={clock(agent.startedAt)} />
                      <Stat label="Elapsed" value={elapsed(agent.startedAt)} />
                    </dl>
                  </>
                ) : (
                  <p className="muted">No task in progress.</p>
                )}
              </Card>
            </div>

            <Card title="Performance"><AgentCounters m={agent.metrics} /></Card>

            <div className="grid two-col">
              <Card title="Task history" flush>
                <div className="table-wrap">
                  <table className="table">
                    <caption className="sr-only">Task history</caption>
                    <thead><tr><th scope="col">Task</th><th scope="col">Project</th><th scope="col">Status</th><th scope="col" className="num">Duration</th></tr></thead>
                    <tbody>
                      {runs.map((r) => (
                        <tr key={r.taskId}>
                          <th scope="row"><Link to={`/tasks/${r.taskId}`}>{r.taskId}</Link><div className="small">{r.title}</div></th>
                          <td>{r.projectId.toUpperCase()}</td>
                          <td>{r.status}</td>
                          <td className="num" title={dateTime(r.startedAt)}>{duration(r.durationSec)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <Card title="Activity timeline"><ActivityFeed events={events} /></Card>
            </div>
          </>
        )
      }
    </AsyncView>
  );
}
