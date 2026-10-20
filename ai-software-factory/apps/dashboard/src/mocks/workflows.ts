import type { Task, TaskStatus } from '../types/task';
import type { StepState, Workflow, WorkflowStatus, WorkflowStep, WorkflowStepId } from '../types/workflow';
import { tasks } from './tasks';

const STEPS: [WorkflowStepId, string][] = [
  ['requirement', 'Requirement'], ['spec', 'Spec'], ['spec_approval', 'Spec Approval'],
  ['plan', 'Plan'], ['plan_approval', 'Plan Approval'], ['task', 'Task'], ['task_approval', 'Task Approval'],
  ['implementation', 'Implementation'], ['code_review', 'Code Review'], ['testing', 'Testing'],
  ['ci', 'CI'], ['merge', 'Merge'],
];

/** Index of the step each status sits on (12 = everything done). */
const POSITION: Record<TaskStatus, number> = {
  NEW: 0, SPEC_DRAFT: 1, SPEC_REVIEW: 2, SPEC_REJECTED: 2, SPEC_APPROVED: 3,
  PLAN_DRAFT: 3, PLAN_REVIEW: 4, PLAN_REJECTED: 4, PLAN_APPROVED: 5,
  TASK_DRAFT: 5, TASK_REVIEW: 6, TASK_REJECTED: 6, TASK_APPROVED: 7,
  IMPLEMENTING: 7, CODE_REVIEW: 8, TESTING: 9, CI: 10, READY_TO_MERGE: 11,
  COMPLETED: 12, FAILED: -1, CANCELLED: -1,
};
/** Mock-only: where terminal failures/cancellations happened. A backend sends steps directly. */
const TERMINAL_AT: Record<string, number> = { 'VHPC-1022': 7, 'ERP-3324': 9, 'ERP-3323': 1 };

function stepsFor(t: Task): WorkflowStep[] {
  const pos = t.status === 'FAILED' || t.status === 'CANCELLED' ? TERMINAL_AT[t.id] ?? 7 : POSITION[t.status];
  return STEPS.map(([id, label], i): WorkflowStep => {
    let state: StepState = i < pos ? 'done' : i === pos ? 'active' : 'pending';
    if (i === pos) {
      if (t.status.endsWith('_REJECTED')) state = 'rejected';
      else if (t.status === 'FAILED') state = 'failed';
      else if (t.status === 'CANCELLED') state = 'cancelled';
    }
    if (t.status === 'CANCELLED' && i > pos) state = 'cancelled';
    return { id, label, state };
  });
}

function statusFor(t: Task): WorkflowStatus {
  if (t.status === 'COMPLETED') return 'COMPLETED';
  if (t.status === 'FAILED') return 'FAILED';
  if (t.status === 'CANCELLED') return 'CANCELLED';
  return t.status.endsWith('_REVIEW') || t.status === 'READY_TO_MERGE' ? 'WAITING_APPROVAL' : 'RUNNING';
}

export const workflows: Workflow[] = tasks.map((t) => ({
  id: `wf-${t.id.toLowerCase()}`,
  taskId: t.id,
  title: t.title,
  projectId: t.projectId,
  type: t.workflowType,
  status: statusFor(t),
  steps: stepsFor(t),
  startedAt: t.createdAt,
  updatedAt: t.updatedAt,
}));
