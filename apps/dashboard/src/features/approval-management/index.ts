import { useCallback, useState } from 'react';
import { useAsync } from '../../hooks/useAsync';
import { reviewHistory, type RunReviewHistory } from '../../lib/reviewViews';
import * as svc from '../../services/approvals/approvalService';
import * as workflowSvc from '../../services/workflows/workflowService';
import type { ApprovalDecisionInput } from '../../types/approval';

export const useApprovals = () => useAsync(svc.listApprovals);

const HISTORY_RUN_LIMIT = 20;

/** Read-only AI review history: the recent runs that went through AI review rounds. */
export const useAiReviewHistory = () =>
  useAsync(async (): Promise<RunReviewHistory[]> => {
    const workflows = await workflowSvc.listWorkflows();
    const subset = workflows.slice(0, HISTORY_RUN_LIMIT);
    const reviews = await Promise.all(subset.map((w) => workflowSvc.getRunReviews(w.id)));
    return reviewHistory(subset, reviews);
  });

/** Wraps decide() with pending/result state. Mock-only today: nothing is persisted. */
export function useApprovalDecision(onDone: () => void) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string>();
  const submit = useCallback(
    async (id: string, input: ApprovalDecisionInput) => {
      setBusy(true);
      try {
        await svc.decide(id, input);
        setMessage(`Recorded ${input.decision.toLowerCase().replace('_', ' ')} (mock action, not persisted).`);
        onDone();
      } catch (e) {
        setMessage((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [onDone],
  );
  return { submit, busy, message };
}
