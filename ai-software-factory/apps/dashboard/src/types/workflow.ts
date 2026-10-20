import type { WorkflowType } from './task';

export type WorkflowStepId =
  | 'requirement' | 'spec' | 'spec_approval' | 'plan' | 'plan_approval' | 'task' | 'task_approval'
  | 'implementation' | 'code_review' | 'testing' | 'ci' | 'merge';

export type StepState = 'done' | 'active' | 'pending' | 'rejected' | 'failed' | 'cancelled';

export interface WorkflowStep {
  id: WorkflowStepId;
  label: string;
  state: StepState;
}

export type WorkflowStatus = 'RUNNING' | 'WAITING_APPROVAL' | 'COMPLETED' | 'FAILED' | 'CANCELLED';

export interface Workflow {
  id: string;
  taskId: string;
  title: string;
  projectId: string;
  type: WorkflowType;
  status: WorkflowStatus;
  steps: WorkflowStep[];
  startedAt: string;
  updatedAt: string;
}
