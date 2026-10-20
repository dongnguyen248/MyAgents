import type { FactorySummary } from '../../types/metrics';
import { listAgents } from '../agents/agentService';
import { api } from '../api';

export const getMetricsOverview = () => api.getMetricsOverview();

/** KPI cards for the main dashboard, derived from the same API data the other pages use. */
export async function getFactorySummary(): Promise<FactorySummary> {
  const [agents, approvals, projects, overview] = await Promise.all([listAgents(), api.listApprovals(), api.listProjects(), api.getMetricsOverview()]);
  const done = agents.reduce((s, a) => s + a.metrics.completed, 0);
  const finished = agents.reduce((s, a) => s + a.metrics.completed + a.metrics.failed + a.metrics.cancelled, 0);
  return {
    activeAgents: agents.filter((a) => ['ONLINE', 'BUSY', 'WAITING'].includes(a.status)).length,
    runningTasks: agents.reduce((s, a) => s + a.metrics.running, 0),
    completedToday: overview.daily[overview.daily.length - 1]?.completed ?? 0,
    successRate: finished ? done / finished : 0,
    pendingApprovals: approvals.filter((a) => a.status === 'PENDING').length,
    ciFailures: projects.reduce((s, p) => s + p.ciFailures24h, 0),
  };
}
