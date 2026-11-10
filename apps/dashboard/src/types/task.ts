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
  /** The run every surface must show for this task (backend-selected). */
  currentRunId?: string;
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
  /** Auto-split parent: aggregated from its part runs by the backend. */
  isSplitParent?: boolean;
  splitTotal?: number;
  splitCompleted?: number;
  /** Auto-split part: the parent task it belongs to, and its position. */
  parentTaskId?: string;
  splitIndex?: number;
  ci?: CiStatus;
  mergeRequest?: string; // e.g. "!214"
}

/** Payload for starting a task: creates a workflow run on a project. */
export interface StartRunInput {
  taskId: string;
  projectId: string;
  title?: string;
  requirement: string;
  priority?: TaskPriority;
  workflowType?: WorkflowType;
  /** Approval steps to skip for this task: 'spec' | 'plan' | 'task'. */
  skipApprovals?: string[];
}

export interface TaskFilter {
  projectId?: string;
  agentId?: string;
  status?: TaskStatus;
  workflowType?: WorkflowType;
  priority?: TaskPriority;
  sinceHours?: number;
}
