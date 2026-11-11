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

export type WorkflowStatus = 'RUNNING' | 'WAITING_APPROVAL' | 'AI_REVIEWING' | 'WAITING_RETRY' | 'ESCALATED' | 'PAUSED' | 'COMPLETED' | 'FAILED' | 'CANCELLED';

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
  kind: 'APPROVAL' | 'AI_REVIEW' | 'ESCALATED' | 'RETRY_WAIT' | 'STEP_RUNNING' | 'STALLED' | 'PAUSED' | 'NONE';
  since: string;
  reason?: string | null;
  retryAt?: string | null;
  budget?: { used: number; max: number } | null;
  suggestedActions: string[];
  /** For a no-tests stop: the run's baked test commands (redacted argv lists). */
  testCommands?: string[][];
  /** For AI_REVIEW: the gated stage under review (e.g. 'SPEC'). */
  stage?: string;
  /** For AI_REVIEW: the current review round (1-based). */
  round?: number;
  /** For AI_REVIEW: the effective revision cap the loop escalates at. */
  maxRounds?: number;
  /** For ESCALATED: MAX_REVISIONS | NO_PROGRESS | REVIEWER_FAILED | BUDGET | NO_TESTS, when known. */
  escalationReason?: string | null;
  /** For ESCALATED: open BLOCKER findings in the latest AI review of the stage. */
  openBlockers?: number;
  /** For ESCALATED with REVIEWER_FAILED: the reviewer error's code. */
  errorCode?: string | null;
  /** For ESCALATED with REVIEWER_FAILED: the reviewer error's redacted, capped message. */
  errorMessage?: string | null;
}

/** One finding of an AI artifact review (GET /runs/{id}/reviews). */
export interface ReviewFinding {
  id: string;
  severity: 'BLOCKER' | 'MAJOR' | 'MINOR' | 'NIT';
  category: string;
  location: string;
  problem: string;
  requiredChange: string;
  status: 'NEW' | 'STILL_OPEN' | 'RESOLVED' | 'WAIVED';
  source: 'ai' | 'mechanical';
  waiverReason?: string | null;
}

/** One AI review round of a gated stage. */
export interface ReviewRound {
  round: number;
  verdict: 'APPROVE' | 'REQUEST_CHANGES';
  reviewArtifactId: string;
  reviewedArtifactId?: string | null;
  reviewedArtifactVersion?: string | null;
  counts: { BLOCKER: number; MAJOR: number; MINOR: number; NIT: number };
  summary?: string | null;
  findings: ReviewFinding[];
}

/** One gated stage's AI review rounds. */
export interface ReviewStage {
  stage: string;
  stepId: string;
  rounds: ReviewRound[];
}

/** GET /runs/{id}/reviews — the AI review history of a run, per stage. */
export interface RunReviews {
  runId: string;
  stages: ReviewStage[];
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

/** Local workspace of a run: how the project's folder was used. */
export interface WorkflowWorkspace {
  /** Effective mode for this run: 'direct' or 'worktree'. */
  mode: string;
  /** Mode configured on the project: 'direct' | 'worktree' | 'auto'. */
  configuredMode: string;
  /** The folder the run worked in (the project folder, or its worktree). */
  folderPath: string;
  /** Repository-relative paths the run wrote (direct mode: the journal's files). */
  filesWritten: string[];
  /** Undo-journal state: active | reverted | kept | conflict; null outside direct mode. */
  journalState: string | null;
  /** Direct-mode files a revert skipped because the user edited them. */
  conflicts?: string[];
  keepChangesOnFailure: boolean;
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
  /** Local workspace block; null when the project has no local folder. */
  workspace?: WorkflowWorkspace | null;
  steps: WorkflowStep[];
  startedAt: string;
  updatedAt: string;
  artifacts?: WorkflowArtifact[];
}
