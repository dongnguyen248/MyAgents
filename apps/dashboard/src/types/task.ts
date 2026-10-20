export type TaskStatus =
  | 'NEW'
  | 'SPEC_DRAFT' | 'SPEC_REVIEW' | 'SPEC_REJECTED' | 'SPEC_APPROVED'
  | 'PLAN_DRAFT' | 'PLAN_REVIEW' | 'PLAN_REJECTED' | 'PLAN_APPROVED'
  | 'TASK_DRAFT' | 'TASK_REVIEW' | 'TASK_REJECTED' | 'TASK_APPROVED'
  | 'IMPLEMENTING' | 'CODE_REVIEW' | 'TESTING' | 'CI' | 'READY_TO_MERGE'
  | 'COMPLETED' | 'FAILED' | 'CANCELLED';

export type TaskPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type WorkflowType = 'feature-development' | 'bug-fix' | 'refactoring';
export type CiStatus = 'PASS' | 'FAIL' | 'RUNNING' | 'UNKNOWN';

export interface Task {
  id: string;
  title: string;
  projectId: string;
  workflowType: WorkflowType;
  status: TaskStatus;
  priority: TaskPriority;
  assignedAgentId?: string;
  createdAt: string;
  updatedAt: string;
  durationSec?: number; // set once finished
  revisions: number;
  ci?: CiStatus;
  mergeRequest?: string; // e.g. "!214"
}

export interface TaskFilter {
  projectId?: string;
  agentId?: string;
  status?: TaskStatus;
  workflowType?: WorkflowType;
  priority?: TaskPriority;
  sinceHours?: number;
}
