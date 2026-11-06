import type { Agent } from '../../types/agent';
import { healthScore } from '../../utils/health';
import { api } from '../api';

const withHealth = (a: Agent): Agent => ({ ...a, metrics: { ...a.metrics, healthScore: a.metrics.healthScore ?? healthScore(a.metrics) } });

export async function listAgents(): Promise<Agent[]> {
  return (await api.listAgents()).map(withHealth);
}

export async function getAgentDetail(id: string) {
  const [agent, runs, events] = await Promise.all([api.getAgent(id), api.getAgentRuns(id), api.listActivity({ agentId: id, limit: 15 })]);
  return { agent: agent && withHealth(agent), runs, events };
}

export const getAgentConfig = (id: string) => api.getAgentConfig(id);

/** Answers "which agent is stuck or failing?" — returns a human-readable reason, or undefined if healthy. */
export function attentionReason(a: Agent): string | undefined {
  const idleMin = (Date.now() - new Date(a.lastActivityAt).getTime()) / 60000;
  if (a.status === 'ERROR') {return a.statusDetail ?? 'Agent reported an error';}
  if (a.status === 'OFFLINE') {return 'Agent is offline';}
  if (a.status === 'WAITING') {return a.statusDetail ?? 'Waiting on a dependency';}
  if (a.status === 'BUSY' && idleMin > 10) {return `No activity for ${Math.round(idleMin)} min (possibly stuck)`;}
  if ((a.metrics.healthScore ?? 100) < 70) {return `Low health score (${a.metrics.healthScore})`;}
  return undefined;
}
