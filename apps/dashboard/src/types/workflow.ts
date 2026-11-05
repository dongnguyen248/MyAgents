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
  /** Structured specifics, e.g. which paths violated a changeset scope. */
  details?: Record<string, unknown> | null;
  /** The workflow stage the run died in (e.g. CODE_FIX for the fix loop). */
  stage?: string | null;
}

export interface WorkflowArtifact {
  id: string;
  type: string;
  name: string;
  version: string;
  createdBy: string;
  content?: string | null;
}

/** What a live run is doing right now (absent for terminal/waiting runs). */
export interface WorkflowCurrentActivity {
  kind: 'STEP_RUNNING' | 'RETRY_WAIT';
  stepId?: string | null;
  stepLabel?: string | null;
  stage?: string | null;
  /** When the current step started (or when the run last changed). */
  since: string;
  /** For RETRY_WAIT: when the next attempt is due. */
  retryAt?: string | null;
}

export interface Workflow {
  id: string;
  taskId: string;
  title: string;
  projectId: string;
  type: WorkflowType;
  status: WorkflowStatus;
  error?: WorkflowError | null;
  currentActivity?: WorkflowCurrentActivity | null;
  steps: WorkflowStep[];
  startedAt: string;
  updatedAt: string;
  artifacts?: WorkflowArtifact[];
}
