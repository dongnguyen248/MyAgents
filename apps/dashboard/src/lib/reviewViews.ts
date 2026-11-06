import type { ReviewRound, ReviewStage, RunReviews } from '../types/workflow';
import type { Workflow } from '../types/workflow';

/** Chip tone for a round verdict: approved, changes requested, or anything else. */
export function verdictTone(verdict: string | null): 'ok' | 'warn' | 'neutral' {
  if (verdict === 'APPROVE') {
    return 'ok';
  }
  if (verdict === 'REQUEST_CHANGES') {
    return 'warn';
  }
  return 'neutral';
}

export interface StageSummary {
  rounds: number;
  latestVerdict: string | null;
  openBlockers: number;
}

const OPEN_STATUSES = new Set(['NEW', 'STILL_OPEN']);

/** Round count, the latest verdict, and blockers still open after the last round. */
export function stageSummary(stage: ReviewStage): StageSummary {
  const last: ReviewRound | undefined = stage.rounds[stage.rounds.length - 1];
  const openBlockers = last
    ? last.findings.filter((f) => f.severity === 'BLOCKER' && OPEN_STATUSES.has(f.status)).length
    : 0;
  return { rounds: stage.rounds.length, latestVerdict: last?.verdict ?? null, openBlockers };
}

export interface RunReviewHistory {
  runId: string;
  taskId: string;
  projectId: string;
  status: Workflow['status'];
  stages: ReviewStage[];
}

/**
 * Zip the workflow list with per-run review payloads into the
 * read-only history the Approvals page renders: only runs that
 * actually went through at least one AI review round appear.
 */
export function reviewHistory(
  workflows: Workflow[],
  reviews: (RunReviews | undefined)[],
): RunReviewHistory[] {
  const entries: RunReviewHistory[] = [];
  workflows.forEach((workflow, index) => {
    const payload = reviews[index];
    if (!payload || payload.stages.length === 0) {
      return;
    }
    entries.push({
      runId: workflow.id,
      taskId: workflow.taskId,
      projectId: workflow.projectId,
      status: workflow.status,
      stages: payload.stages,
    });
  });
  return entries;
}
