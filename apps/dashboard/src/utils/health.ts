import type { AgentMetrics } from '../types/metrics';

/**
 * Agent Health Score (0..100). Combines outcome quality, not just volume:
 * success 30%, human approval 20%, CI pass 20%, test pass 15%, low revision count 15%.
 * Computed client-side for now; a backend can supply AgentMetrics.healthScore later.
 */
export function healthScore(m: AgentMetrics): number {
  const revisionScore = Math.max(0, 1 - (m.avgRevisions - 1) / 3);
  const score = 0.3 * m.successRate + 0.2 * m.humanApprovalRate + 0.2 * m.ciPassRate + 0.15 * m.testPassRate + 0.15 * revisionScore;
  return Math.round(score * 100);
}

export const healthTone = (score: number): 'ok' | 'warn' | 'danger' => (score >= 85 ? 'ok' : score >= 70 ? 'warn' : 'danger');
