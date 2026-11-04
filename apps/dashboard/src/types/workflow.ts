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

/** The failure that ended a FAILED workflow run (absent otherwise). */
export interface WorkflowError {
  code: string;
  message: string;
  category: string;
  at?: string;
}

export interface WorkflowArtifact {
  id: string;
  type: string;
  name: string;
  version: string;
  createdBy: string;
  content?: string | null;
}

export interface Workflow {
  id: string;
  taskId: string;
  title: string;
  projectId: string;
  type: WorkflowType;
  status: WorkflowStatus;
  error?: WorkflowError | null;
  steps: WorkflowStep[];
  startedAt: string;
  updatedAt: string;
  artifacts?: WorkflowArtifact[];
}
