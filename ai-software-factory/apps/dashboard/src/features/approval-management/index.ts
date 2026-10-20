import { useCallback, useState } from 'react';
import { useAsync } from '../../hooks/useAsync';
import * as svc from '../../services/approvals/approvalService';
import type { ApprovalDecisionInput } from '../../types/approval';

export const useApprovals = () => useAsync(svc.listApprovals);

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
