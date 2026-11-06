import type { MetricsOverview } from '../types/metrics';
import { agents } from './agents';
import { healthScore } from '../utils/health';
import { minutesAgo } from './time';

const day = (i: number) => minutesAgo((13 - i) * 1440).slice(0, 10);
const wave = (i: number, base: number, amp: number, seed: number) => base + Math.round(Math.sin(i * 1.3 + seed) * amp);
const frac = (i: number, base: number, amp: number, seed: number) => +(base + Math.sin(i * 1.1 + seed) * amp + i * 0.001).toFixed(3);

const daily = Array.from({ length: 14 }, (_, i) => {
  const completed = i === 13 ? 47 : wave(i, 38 + i, 6, 0);
  const failed = wave(i, 5, 2, 2);
  return {
    date: day(i), completed, failed,
    successRate: completed / (completed + failed),
    avgDurationSec: wave(i, 1080 - i * 10, 90, 1),
  };
});

export const metricsOverview: MetricsOverview = {
  daily,
  human: {
    approvalRate: 0.86, rejectionRate: 0.14, avgRevisions: 1.4, avgApprovalMinutes: 11.5,
    daily: daily.map((d, i) => ({ date: d.date, approvalRate: frac(i, 0.84, 0.04, 3), rejectionRate: 1 - frac(i, 0.84, 0.04, 3) })),
  },
  quality: {
    codeReviewRejectionRate: 0.17, testPassRate: 0.9, ciPassRate: 0.88, reworkRate: 0.09,
    daily: daily.map((d, i) => ({ date: d.date, testPassRate: frac(i, 0.89, 0.03, 4), ciPassRate: frac(i, 0.87, 0.04, 5), reworkRate: frac(i, 0.1, 0.02, 6) })),
  },
  agents: agents
    .filter((a) => ['spec', 'plan', 'implement', 'review', 'test'].includes(a.type))
    .map((a) => ({
      agentId: a.id, name: a.name, successRate: a.metrics.successRate, avgDurationSec: a.metrics.avgDurationSec,
      avgRevisions: a.metrics.avgRevisions, humanApprovalRate: a.metrics.humanApprovalRate, healthScore: healthScore(a.metrics),
    })),
  aiReview: { firstPassRate: 0.62, avgRounds: 1.6, escalationRate: 0.08, stagnationRate: 0.03, gates: 128, escalations: 10 },
};
