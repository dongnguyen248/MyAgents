import type { CiStatus, Task, TaskPriority, TaskStatus, WorkflowType } from '../types/task';
import { minutesAgo } from './time';

type Extra = { type?: WorkflowType; dur?: number; rev?: number; ci?: CiStatus; mr?: string };

const mk = (
  id: string, title: string, status: TaskStatus, priority: TaskPriority,
  agentId: string | undefined, ageMin: number, x: Extra = {},
): Task => ({
  id, title, status, priority,
  projectId: id.split('-')[0].toLowerCase(),
  workflowType: x.type ?? 'feature-development',
  assignedAgentId: agentId,
  createdAt: minutesAgo(ageMin),
  updatedAt: minutesAgo(Math.floor(ageMin / 4) + 1),
  durationSec: x.dur ? x.dur * 60 : undefined,
  revisions: x.rev ?? 0,
  ci: x.ci,
  mergeRequest: x.mr,
});

export const tasks: Task[] = [
  mk('VHPC-1018', 'Add customer export endpoint', 'COMPLETED', 'MEDIUM', 'implement-agent', 3100, { dur: 14, rev: 1, ci: 'PASS', mr: '!201' }),
  mk('VHPC-1019', 'Fix rounding error in invoice totals', 'COMPLETED', 'HIGH', 'implement-agent', 2900, { type: 'bug-fix', dur: 11, rev: 0, ci: 'PASS', mr: '!204' }),
  mk('VHPC-1020', 'Refactor PricingService', 'COMPLETED', 'MEDIUM', 'implement-agent', 2500, { type: 'refactoring', dur: 12, rev: 1, ci: 'PASS', mr: '!207' }),
  mk('VHPC-1021', 'Add pagination to product list', 'COMPLETED', 'MEDIUM', 'implement-agent', 1700, { dur: 18, rev: 2, ci: 'PASS', mr: '!210' }),
  mk('VHPC-1022', 'Integrate inventory sync', 'FAILED', 'HIGH', 'implement-agent', 1500, { dur: 27, rev: 3 }),
  mk('VHPC-1023', 'Implement Sales Plan API', 'IMPLEMENTING', 'HIGH', 'implement-agent', 240, { rev: 1 }),
  mk('VHPC-1024', 'Sales plan approval rules', 'SPEC_REVIEW', 'MEDIUM', 'spec-agent', 60),
  mk('VHPC-1025', 'Monthly sales dashboard widgets', 'TESTING', 'MEDIUM', 'test-agent', 380, { rev: 1 }),
  mk('VNPC-2038', 'Migrate user profile to new schema', 'CODE_REVIEW', 'HIGH', 'review-agent', 420, { rev: 1 }),
  mk('VNPC-2039', 'Fix timezone bug in scheduler', 'CI', 'CRITICAL', undefined, 300, { type: 'bug-fix', rev: 0, ci: 'RUNNING', mr: '!214' }),
  mk('VNPC-2040', 'Add audit log filters', 'PLAN_DRAFT', 'LOW', 'plan-agent', 90),
  mk('VNPC-2041', 'Bulk import of vendors', 'PLAN_REVIEW', 'MEDIUM', 'plan-agent', 150),
  mk('VNPC-2042', 'Notification preferences page', 'TASK_DRAFT', 'MEDIUM', 'task-agent', 200),
  mk('VNPC-2043', 'Refactor auth middleware', 'READY_TO_MERGE', 'MEDIUM', undefined, 700, { type: 'refactoring', rev: 1, ci: 'PASS', mr: '!211' }),
  mk('ERP-3318', 'Purchase order PDF export', 'COMPLETED', 'MEDIUM', 'implement-agent', 2000, { dur: 22, rev: 1, ci: 'PASS', mr: '!88' }),
  mk('ERP-3319', 'Stock reconciliation job', 'TASK_REJECTED', 'HIGH', 'task-agent', 330, { rev: 2 }),
  mk('ERP-3320', 'Ledger balance report', 'TESTING', 'HIGH', 'test-agent', 260, { rev: 1 }),
  mk('ERP-3321', 'General ledger account mapping', 'TASK_REVIEW', 'HIGH', 'task-agent', 100),
  mk('ERP-3322', 'Supplier onboarding form', 'NEW', 'LOW', undefined, 15),
  mk('ERP-3323', 'Legacy currency converter cleanup', 'CANCELLED', 'LOW', undefined, 4000, { type: 'refactoring', dur: 3, rev: 0 }),
  mk('ERP-3324', 'Fix payroll rounding', 'FAILED', 'HIGH', 'test-agent', 1900, { type: 'bug-fix', dur: 35, rev: 3 }),
];
