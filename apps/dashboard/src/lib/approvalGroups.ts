import type { Approval } from '../types/approval';
import type { Workflow } from '../types/workflow';

/**
 * How the Approvals page splits its world (Phase 12):
 *
 * - needsHuman: pending gates a person must decide (human mode, or
 *   no mode recorded, which predates the field) plus the runs
 *   parked at ESCALATED, whose decision lives on the run page.
 * - aiReviewing: pending gates the AI reviewer is deciding. A
 *   human may still override them, but nobody is waiting on one.
 */
export interface ApprovalGroups {
  needsHuman: Approval[];
  aiReviewing: Approval[];
  escalated: Workflow[];
}

export function groupApprovals(approvals: Approval[], workflows: Workflow[]): ApprovalGroups {
  const pending = approvals.filter((a) => a.status === 'PENDING');
  return {
    needsHuman: pending.filter((a) => a.mode !== 'ai'),
    aiReviewing: pending.filter((a) => a.mode === 'ai'),
    escalated: workflows.filter((w) => w.status === 'ESCALATED'),
  };
}
