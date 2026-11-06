export type ApprovalType = 'SPEC' | 'PLAN' | 'TASK' | 'CODE_REVIEW' | 'DEPLOYMENT';
export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'CHANGES_REQUESTED';
export type ApprovalDecisionKind = 'APPROVE' | 'REJECT' | 'REQUEST_CHANGES' | 'COMMENT';

export interface ApprovalComment {
  author: string;
  at: string;
  text: string;
}

export type ApprovalMode = 'ai' | 'human' | 'none';

export interface Approval {
  id: string;
  projectId: string;
  taskId: string;
  type: ApprovalType;
  status: ApprovalStatus;
  requestedAt: string;
  requestedByAgentId: string;
  artifact: string; // e.g. "SPEC.md"
  summary: string;
  /** Full artifact text (or JSON rendering) so reviewers can read before deciding. */
  artifactContent?: string;
  comments: ApprovalComment[];
  /** The run this gate belongs to (Phase 12; links to the run view). */
  workflowId?: string;
  /** Who the gate is addressed to; ai-mode gates include "ai-reviewer". */
  reviewers?: string[];
  /** Resolved gate mode: human gates wait for a person, ai gates are reviewed by the AI reviewer. */
  mode?: ApprovalMode;
}

export interface ApprovalDecisionInput {
  decision: ApprovalDecisionKind;
  comment?: string;
}
