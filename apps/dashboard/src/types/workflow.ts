import type { WorkflowType } from './task';

export type WorkflowStepId =
  | 'requirement' | 'spec' | 'spec_approval' | 'plan' | 'plan_approval' | 'task' | 'task_approval'
  | 'implementation' | 'code_review' | 'testing' | 'fix' | 'ci' | 'merge';

export type StepState = 'done' | 'active' | 'pending' | 'rejected' | 'failed' | 'cancelled' | 'skipped' | 'escalated';

export interface WorkflowStep {
  id: WorkflowStepId;
  label: string;
  state: StepState;
}

export type WorkflowStatus = 'RUNNING' | 'WAITING_APPROVAL' | 'WAITING_RETRY' | 'ESCALATED' | 'PAUSED' | 'COMPLETED' | 'FAILED' | 'CANCELLED';

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
  kind: 'STEP_RUNNING' | 'RETRY_WAIT' | 'APPROVAL' | 'ESCALATED' | 'STALLED' | 'PAUSED';
  stepId?: string | null;
  stepLabel?: string | null;
  stage?: string | null;
  /** When the current step started (or when the run last changed). */
  since: string;
  /** Human reason for waits (approval target, escalation, stall). */
  reason?: string | null;
  /** For RETRY_WAIT: when the next attempt is due. */
  retryAt?: string | null;
}

/** What a non-terminal run is waiting for, in operator terms. */
export interface WorkflowWaiting {
  kind: 'APPROVAL' | 'ESCALATED' | 'RETRY_WAIT' | 'STEP_RUNNING' | 'STALLED' | 'PAUSED' | 'NONE';
  since: string;
  reason?: string | null;
  retryAt?: string | null;
  budget?: { used: number; max: number } | null;
  suggestedActions: string[];
}

/** The background drive's own state for a run (kept in backend RAM). */
export interface WorkflowDriver {
  alive: boolean;
  lastTickAt?: string | null;
  lastStopReason?: string | null;
}

/** GET /runs/{id}/diagnostics — the operator's one-shot answer. */
export interface RunDiagnostics {
  runId: string;
  taskId: string;
  projectId: string;
  stage: string;
  stageKind: string;
  status: WorkflowStatus;
  waiting: WorkflowWaiting;
  inFlight?: { token: string; ageSeconds: number } | null;
  retryAt?: string | null;
  fixBudget: { used: number; max: number };
  revisions: Record<string, number>;
  lastEvents: { type: string; message: string; at: string; metadata: Record<string, unknown> }[];
  lastError?: {
    code: string;
    message: string;
    category: string;
    retryable: boolean;
    at: string;
    details?: Record<string, unknown> | null;
  } | null;
  driver: WorkflowDriver;
  suggestedActions: string[];
}

export interface Workflow {
  id: string;
  taskId: string;
  title: string;
  projectId: string;
  type: WorkflowType;
  status: WorkflowStatus;
  error?: WorkflowError | null;
  /** Split lineage for auto-split tasks: set on each part's run. */
  parentTaskId?: string | null;
  splitIndex?: number | null;
  splitTotal?: number | null;
  /** Set when auto-split was attempted but decomposition failed (run proceeds whole). */
  splitError?: string | null;
  /** "complex" when the run's oversized requirement auto-upgraded every agent to the shared model. */
  modelTier?: string | null;
  /** Approval steps (spec/plan/task) this task asked to skip at creation. */
  skippedApprovals?: string[];
  currentActivity?: WorkflowCurrentActivity | null;
  waiting?: WorkflowWaiting;
  driver?: WorkflowDriver;
  steps: WorkflowStep[];
  startedAt: string;
  updatedAt: string;
  artifacts?: WorkflowArtifact[];
}
