import type { Approval } from '../types/approval';
import { minutesAgo } from './time';

export const approvals: Approval[] = [
  { id: 'apr-501', projectId: 'vhpc', taskId: 'VHPC-1024', type: 'SPEC', status: 'PENDING', requestedAt: minutesAgo(5), requestedByAgentId: 'spec-agent', artifact: 'SPEC.md', summary: 'Specification for configurable sales plan approval rules (3 functional areas, 11 acceptance criteria).', comments: [] },
  { id: 'apr-502', projectId: 'vnpc', taskId: 'VNPC-2041', type: 'PLAN', status: 'PENDING', requestedAt: minutesAgo(12), requestedByAgentId: 'plan-agent', artifact: 'PLAN.md', summary: 'Plan for bulk vendor import: CSV validation, staging table, idempotent upsert. 2 identified risks.', comments: [] },
  { id: 'apr-503', projectId: 'erp', taskId: 'ERP-3321', type: 'TASK', status: 'PENDING', requestedAt: minutesAgo(2), requestedByAgentId: 'task-agent', artifact: 'TASK-001..006.md', summary: 'Breakdown into 6 tasks for general ledger account mapping.', comments: [] },
  { id: 'apr-504', projectId: 'vnpc', taskId: 'VNPC-2038', type: 'CODE_REVIEW', status: 'PENDING', requestedAt: minutesAgo(25), requestedByAgentId: 'review-agent', artifact: 'CODE_REVIEW.md', summary: 'Review of profile schema migration: 3 comments, 1 medium-severity (missing rollback script).', comments: [{ author: 'Review Agent', at: minutesAgo(25), text: 'Recommend adding a rollback migration before merge.' }] },
  { id: 'apr-505', projectId: 'vnpc', taskId: 'VNPC-2043', type: 'DEPLOYMENT', status: 'PENDING', requestedAt: minutesAgo(40), requestedByAgentId: 'review-agent', artifact: 'MR !211', summary: 'Quality gate passed; auth middleware refactor ready to merge to main.', comments: [] },
];
