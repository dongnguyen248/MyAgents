/** Rates are fractions in the range 0..1. Durations are seconds. */
export interface AgentMetrics {
  total: number;
  completed: number;
  running: number;
  failed: number;
  cancelled: number;
  successRate: number;
  avgDurationSec: number;
  avgRevisions: number;
  /** Null when the agent has no human decisions (AI-reviewed gates). */
  humanApprovalRate: number | null;
  humanDecisions?: number;
  aiDecisions?: number;
  testPassRate: number;
  ciPassRate: number;
  /** Platform-accumulated model usage across this agent's runs. */
  promptTokens: number;
  completionTokens: number;
  modelCalls: number;
  /** 0..100. Computed client-side today; a backend may provide it later. */
  healthScore?: number;
}

export interface ProjectMetrics {
  activeAgents: number;
  running: number;
  completed: number;
  failed: number;
  successRate: number;
  pendingApprovals: number;
}

export interface DailyPoint {
  date: string; // ISO date
  completed: number;
  failed: number;
  successRate: number;
  avgDurationSec: number;
}

export interface AgentComparisonRow {
  agentId: string;
  name: string;
  successRate: number;
  avgDurationSec: number;
  avgRevisions: number;
  humanApprovalRate: number | null;
  healthScore: number;
}

/** AI review loop metrics (Phase 12), computed from review events. */
export interface AiReviewMetrics {
  firstPassRate: number;
  avgRounds: number;
  escalationRate: number;
  stagnationRate: number;
  gates: number;
  escalations: number;
}

export interface MetricsOverview {
  daily: DailyPoint[];
  human: {
    /** Null when there are no human decisions at all. */
    approvalRate: number | null;
    rejectionRate: number | null;
    avgRevisions: number;
    avgApprovalMinutes: number;
    decisions?: number;
    aiDecisions?: number;
    daily: { date: string; approvalRate: number; rejectionRate: number }[];
  };
  quality: {
    codeReviewRejectionRate: number;
    testPassRate: number;
    ciPassRate: number;
    reworkRate: number;
    daily: { date: string; testPassRate: number; ciPassRate: number; reworkRate: number }[];
  };
  agents: AgentComparisonRow[];
  aiReview: AiReviewMetrics;
}

/** KPI summary for the main dashboard. */
export interface FactorySummary {
  activeAgents: number;
  runningTasks: number;
  completedToday: number;
  successRate: number;
  pendingApprovals: number;
  ciFailures: number;
}
