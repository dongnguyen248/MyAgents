import type { Project } from '../../types/project';
import { pct } from '../../utils/format';
import { CiBadge } from '../common/Badge';
import { Card, Stat } from '../common/Layout';

export function ProjectCard({ project: p }: { project: Project }) {
  return (
    <Card title={p.name} actions={<CiBadge status={p.ci} />}>
      <p className="muted small">{p.repositoryProvider} · {p.technologies.join(', ')}</p>
      <dl className="stats stats-2">
        <Stat label="Active agents" value={p.metrics.activeAgents} />
        <Stat label="Running tasks" value={p.metrics.running} />
        <Stat label="Completed" value={p.metrics.completed} />
        <Stat label="Failed" value={p.metrics.failed} />
        <Stat label="Success rate" value={pct(p.metrics.successRate, 0)} />
        <Stat label="Pending approvals" value={p.metrics.pendingApprovals} />
        <Stat label="CI failures (24h)" value={p.ciFailures24h} />
      </dl>
    </Card>
  );
}
