import type { AgentMetrics } from '../types/metrics';

/**
 * Agent Health Score (0..100). Combines outcome quality, not just volume:
 * success 30%, human approval 20%, CI pass 20%, test pass 15%, low revision count 15%.
 * Computed client-side for now; a backend can supply AgentMetrics.healthScore later.
 */
export function healthScore(m: AgentMetrics): number {
  const revisionScore = Math.max(0, 1 - (m.avgRevisions - 1) / 3);
  // No human decisions (humanApprovalRate null — the AI-reviewed
  // case): the human 20% is not scored as zero; the remaining
  // weights re-normalise to 1 (÷ 0.8), mirroring the backend.
  const score = m.humanApprovalRate === null
    ? (0.3 * m.successRate + 0.2 * m.ciPassRate + 0.15 * m.testPassRate + 0.15 * revisionScore) / 0.8
    : 0.3 * m.successRate + 0.2 * m.humanApprovalRate + 0.2 * m.ciPassRate + 0.15 * m.testPassRate + 0.15 * revisionScore;
  return Math.round(score * 100);
}

export const healthTone = (score: number): 'ok' | 'warn' | 'danger' => (score >= 85 ? 'ok' : score >= 70 ? 'warn' : 'danger');
