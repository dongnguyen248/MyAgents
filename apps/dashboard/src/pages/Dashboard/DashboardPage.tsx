import { Link } from 'react-router-dom';
import { ActivityFeed } from '../../components/activity/ActivityFeed';
import { AgentStatusBadge } from '../../components/agents/AgentStatusBadge';
import { ApprovalTable } from '../../components/approvals/ApprovalTable';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, EmptyState, HealthMeter, KpiCard, PageHeader } from '../../components/common/Layout';
import { CiBadge } from '../../components/common/Badge';
import { attentionReason, useAgents } from '../../features/agent-management';
import { useFactorySummary } from '../../features/agent-metrics';
import { useActivityFeed } from '../../features/activity-feed';
import { useApprovals } from '../../features/approval-management';
import { useProjects } from '../../features/project-management';
import { pct } from '../../utils/format';

export function DashboardPage() {
  const summary = useFactorySummary();
  const agents = useAgents();
  const projects = useProjects();
  const approvals = useApprovals();
  const feed = useActivityFeed({ limit: 8 });

  return (
    <>
      <PageHeader title="Dashboard" subtitle="What is the AI Software Agents doing right now?" />

      <AsyncView {...summary}>
        {(s) => (
          <div className="grid grid-kpi">
            <KpiCard label="Active agents" value={s.activeAgents} hint="online, busy or waiting" />
            <KpiCard label="Running tasks" value={s.runningTasks} />
            <KpiCard label="Completed today" value={s.completedToday} />
            <KpiCard label="Success rate" value={pct(s.successRate)} />
            <KpiCard label="Pending approval" value={s.pendingApprovals} tone={s.pendingApprovals ? 'warn' : undefined} />
            <KpiCard label="CI failures (24h)" value={s.ciFailures} tone={s.ciFailures ? 'danger' : 'ok'} />
          </div>
        )}
      </AsyncView>

      <div className="grid two-col">
        <Card title="Needs attention" actions={<Link to="/agents">All agents</Link>}>
          <AsyncView {...agents}>
            {(list) => {
              const flagged = list.map((a) => [a, attentionReason(a)] as const).filter(([, r]) => r);
              if (!flagged.length) return <EmptyState>All agents healthy.</EmptyState>;
              return (
                <ul className="plain">
                  {flagged.map(([a, reason]) => (
                    <li key={a.id}>
                      <AgentStatusBadge status={a.status} /> <Link to={`/agents/${a.id}`}><strong>{a.name}</strong></Link>
                      <div className="muted small">{reason}</div>
                    </li>
                  ))}
                </ul>
              );
            }}
          </AsyncView>
        </Card>

        <Card title="Projects by agent usage" actions={<Link to="/projects">All projects</Link>}>
          <AsyncView {...projects}>
            {(list) => (
              <ul className="plain">
                {[...list].sort((a, b) => b.metrics.activeAgents - a.metrics.activeAgents).map((p) => (
                  <li key={p.id}>
                    <div className="row-between"><strong>{p.name}</strong><span>{p.metrics.activeAgents} agents · <CiBadge status={p.ci} /></span></div>
                    <div className="bar"><span style={{ width: `${(p.metrics.activeAgents / 7) * 100}%` }} /></div>
                  </li>
                ))}
              </ul>
            )}
          </AsyncView>
        </Card>
      </div>

      <Card title="Agent fleet" actions={<Link to="/agents">Details</Link>} flush>
        <AsyncView {...agents}>
          {(list) => (
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Agent fleet</caption>
                <thead><tr><th scope="col">Agent</th><th scope="col">Status</th><th scope="col">Current task</th><th scope="col" className="num">Completed</th><th scope="col">Health</th></tr></thead>
                <tbody>
                  {list.map((a) => (
                    <tr key={a.id}>
                      <th scope="row"><Link to={`/agents/${a.id}`}>{a.name}</Link></th>
                      <td><AgentStatusBadge status={a.status} /></td>
                      <td>{a.currentTaskId ? <>{a.currentTaskId} <span className="muted small">{a.currentTaskTitle}</span></> : <span className="muted">–</span>}</td>
                      <td className="num">{a.metrics.completed}</td>
                      <td><HealthMeter score={a.metrics.healthScore} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AsyncView>
      </Card>

      <div className="grid two-col">
        <Card title="Pending approvals" actions={<Link to="/approvals">Review</Link>} flush>
          <AsyncView {...approvals}>{(list) => <ApprovalTable approvals={list.filter((a) => a.status === 'PENDING')} />}</AsyncView>
        </Card>
        <Card title="Live activity" actions={<Link to="/activity">Open feed</Link>}>
          <ActivityFeed events={feed.events.slice(0, 8)} />
        </Card>
      </div>
    </>
  );
}
