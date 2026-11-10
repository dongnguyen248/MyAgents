import type { Workflow } from '../types/workflow';

/**
 * The dashboard's half of the single current-run definition (the
 * backend selector in api/service/run_selection.py is the other):
 * the current run of a task is the maximum by (startedAt,
 * updatedAt, position in the list as returned by the API). The API
 * returns runs ascending by (started_at, id), so the later position
 * wins a full tie — matching the backend exactly.
 *
 * Timestamps are compared as parsed instants, never as strings:
 * ISO values with different offsets (Z vs +07:00) do not sort
 * lexicographically. An unparseable timestamp sorts lowest.
 */

function timeOf(value: string): number {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return Number.NEGATIVE_INFINITY;
  }
  return parsed;
}

interface ScoredRun {
  run: Workflow;
  started: number;
  updated: number;
  index: number;
}

function isLater(candidate: ScoredRun, best: ScoredRun | undefined): boolean {
  if (!best) {
    return true;
  }
  if (candidate.started !== best.started) {
    return candidate.started > best.started;
  }
  if (candidate.updated !== best.updated) {
    return candidate.updated > best.updated;
  }
  return candidate.index > best.index;
}

/** The current run among `runs`, in API list order. */
export function pickCurrentRun(runs: Workflow[]): Workflow | undefined {
  let best: ScoredRun | undefined;
  runs.forEach((run, index) => {
    const candidate: ScoredRun = {
      run,
      started: timeOf(run.startedAt),
      updated: timeOf(run.updatedAt),
      index,
    };
    if (isLater(candidate, best)) {
      best = candidate;
    }
  });
  return best?.run;
}

/**
 * The run a task page displays: the one the backend named as
 * current when it is in the pool, else the pool's current run.
 * The fallback matters because the task view and the workflow list
 * are fetched in parallel — the named run may not have landed yet.
 */
export function pickTaskWorkflow(
  runs: Workflow[],
  currentRunId?: string,
): Workflow | undefined {
  const named = currentRunId ? runs.find((run) => run.id === currentRunId) : undefined;
  return named ?? pickCurrentRun(runs);
}
