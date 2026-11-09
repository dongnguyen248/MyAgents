import type { AgentMetrics } from '../types/metrics';

const SUCCESS_WEIGHT = 0.3;
const HUMAN_APPROVAL_WEIGHT = 0.2;
const CI_PASS_WEIGHT = 0.2;
const TEST_PASS_WEIGHT = 0.15;
const REVISION_WEIGHT = 0.15;
const NON_HUMAN_WEIGHT_TOTAL = 0.8;
const REVISION_SPAN = 3;
const PERCENT_SCALE = 100;
const TONE_OK_THRESHOLD = 85;
const TONE_WARN_THRESHOLD = 70;

/**
 * Agent Health Score (0..100). Combines outcome quality, not just volume:
 * success 30%, human approval 20%, CI pass 20%, test pass 15%, low revision count 15%.
 * Computed client-side for now; a backend can supply AgentMetrics.healthScore later.
 */
export function healthScore(m: AgentMetrics): number {
  const revisionScore = Math.max(0, 1 - (m.avgRevisions - 1) / REVISION_SPAN);
  // No human decisions (humanApprovalRate null — the AI-reviewed
  // case): the human 20% is not scored as zero; the remaining
  // weights re-normalise to 1 (÷ 0.8), mirroring the backend.
  const score = m.humanApprovalRate === null
    ? (SUCCESS_WEIGHT * m.successRate + CI_PASS_WEIGHT * m.ciPassRate + TEST_PASS_WEIGHT * m.testPassRate + REVISION_WEIGHT * revisionScore) / NON_HUMAN_WEIGHT_TOTAL
    : SUCCESS_WEIGHT * m.successRate + HUMAN_APPROVAL_WEIGHT * m.humanApprovalRate + CI_PASS_WEIGHT * m.ciPassRate + TEST_PASS_WEIGHT * m.testPassRate + REVISION_WEIGHT * revisionScore;
  return Math.round(score * PERCENT_SCALE);
}

export const healthTone = (score: number): 'ok' | 'warn' | 'danger' => (score >= TONE_OK_THRESHOLD ? 'ok' : score >= TONE_WARN_THRESHOLD ? 'warn' : 'danger');
