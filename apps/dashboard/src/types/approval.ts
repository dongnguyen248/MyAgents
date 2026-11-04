export type ApprovalType = 'SPEC' | 'PLAN' | 'TASK' | 'CODE_REVIEW' | 'DEPLOYMENT';
export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'CHANGES_REQUESTED';
export type ApprovalDecisionKind = 'APPROVE' | 'REJECT' | 'REQUEST_CHANGES' | 'COMMENT';

export interface ApprovalComment {
  author: string;
  at: string;
  text: string;
}

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
}

export interface ApprovalDecisionInput {
  decision: ApprovalDecisionKind;
  comment?: string;
}
