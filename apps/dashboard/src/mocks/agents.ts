import type { Agent, AgentConfig, AgentRun, AgentStatus, AgentType } from '../types/agent';
import type { AgentMetrics } from '../types/metrics';
import { minutesAgo, secondsAgo } from './time';
import { tasks } from './tasks';

const metrics = (
  completed: number, running: number, failed: number, cancelled: number,
  avgDurationSec: number, avgRevisions: number, humanApprovalRate: number, testPassRate: number, ciPassRate: number,
): AgentMetrics => {
  const total = completed + running + failed + cancelled;
  return { total, completed, running, failed, cancelled, successRate: completed / total, avgDurationSec, avgRevisions, humanApprovalRate, testPassRate, ciPassRate };
};

const base = (
  id: string, name: string, type: AgentType, status: AgentStatus, model: string, version: string,
  lastMin: number, m: AgentMetrics, extra: Partial<Agent> = {},
): Agent => ({ id, name, type, status, model, version, lastActivityAt: minutesAgo(lastMin), metrics: m, ...extra });

export const agents: Agent[] = [
  base('spec-agent', 'Spec Agent', 'spec', 'ONLINE', 'claude-sonnet-4.6', '1.4.2', 1,
    metrics(124, 1, 7, 2, 412, 1.3, 0.88, 0.96, 0.95),
    { currentTaskId: 'VHPC-1024', currentTaskTitle: 'Sales plan approval rules', currentProjectId: 'vhpc', startedAt: minutesAgo(26), statusDetail: 'SPEC drafted; awaiting human approval' }),
  base('plan-agent', 'Plan Agent', 'plan', 'BUSY', 'gpt-5', '1.2.0', 0,
    metrics(98, 2, 8, 1, 655, 1.5, 0.84, 0.94, 0.93),
    { currentTaskId: 'VNPC-2040', currentTaskTitle: 'Add audit log filters', currentProjectId: 'vnpc', startedAt: minutesAgo(7) }),
  base('task-agent', 'Task Agent', 'task', 'WAITING', 'gemini-2.5-pro', '1.1.3', 2,
    metrics(156, 1, 17, 2, 380, 1.6, 0.8, 0.9, 0.9),
    { currentTaskId: 'ERP-3321', currentTaskTitle: 'General ledger account mapping', currentProjectId: 'erp', startedAt: minutesAgo(40), statusDetail: 'Waiting for task approval' }),
  base('implement-agent', 'Implement Agent', 'implement', 'BUSY', 'claude-sonnet-4.6', '2.0.1', 0,
    metrics(298, 3, 41, 0, 1002, 1.4, 0.82, 0.88, 0.86),
    { currentTaskId: 'VHPC-1023', currentTaskTitle: 'Implement Sales Plan API', currentProjectId: 'vhpc', startedAt: secondsAgo(18 * 60 + 32) }),
  base('review-agent', 'Code Review Agent', 'review', 'ONLINE', 'gpt-5', '1.3.0', 3,
    metrics(310, 2, 14, 1, 290, 1.1, 0.93, 0.97, 0.96),
    { currentTaskId: 'VNPC-2038', currentTaskTitle: 'Migrate user profile to new schema', currentProjectId: 'vnpc', startedAt: minutesAgo(25) }),
  base('test-agent', 'Test Agent', 'test', 'ERROR', 'deepseek-v3', '1.0.7', 3,
    metrics(288, 0, 62, 3, 540, 1.8, 0.72, 0.82, 0.8),
    { statusDetail: 'Integration test runner timed out (600s) on ERP-3320' }),
  base('fix-agent', 'Fix Agent', 'fix', 'IDLE', 'qwen-coder (local)', '0.9.4', 55,
    metrics(64, 0, 9, 1, 460, 1.7, 0.78, 0.9, 0.88)),
];

const prompts: Record<AgentType, string> = {
  spec: 'You turn a requirement into a precise SPEC.md. Ask no questions; list open questions in the document.',
  plan: 'You turn an approved SPEC into a PLAN.md with approach, impacted components, risks and milestones.',
  task: 'You break an approved PLAN into small, independently implementable TASK files with a definition of done.',
  implement: 'You implement exactly one approved TASK. Follow enabled skills. Never modify files outside the task scope.',
  review: 'You review code changes against the TASK, SPEC and enabled skills and produce a CODE_REVIEW.md.',
  test: 'You create and run tests for the change and produce a TEST_REPORT.md.',
  fix: 'You resolve review findings, failing tests and CI failures with minimal changes.',
};
const skillSets: Record<AgentType, string[]> = {
  spec: ['general', 'software-development'],
  plan: ['general', 'software-development', 'database'],
  task: ['software-development', 'git'],
  implement: ['java', 'spring', 'react', 'git', 'testing', 'security'],
  review: ['code-review', 'security', 'git'],
  test: ['testing', 'java', 'python'],
  fix: ['java', 'spring', 'git', 'testing'],
};
const toolSets: Record<AgentType, string[]> = {
  spec: ['read_repo', 'read_template'],
  plan: ['read_repo', 'read_template', 'search_docs'],
  task: ['read_repo', 'read_template'],
  implement: ['read_repo', 'write_file', 'run_tests', 'git_diff'],
  review: ['read_repo', 'git_diff', 'comment'],
  test: ['read_repo', 'write_file', 'run_tests'],
  fix: ['read_repo', 'write_file', 'run_tests', 'git_diff'],
};

export const agentConfigs: AgentConfig[] = agents.map((a) => ({
  agentId: a.id,
  name: a.name,
  type: a.type,
  enabled: a.status !== 'DISABLED',
  model: a.model.split(' ')[0],
  modelVersion: a.model.includes('local') ? 'q4_k_m' : 'latest',
  systemPrompt: prompts[a.type],
  skills: skillSets[a.type],
  tools: toolSets[a.type],
  allowedProjectIds: ['vhpc', 'vnpc', 'erp'],
  maxConcurrentTasks: a.type === 'implement' ? 4 : 2,
  timeoutSeconds: a.type === 'test' ? 900 : 1800,
  retryPolicy: { maxRetries: 2, backoff: 'exponential', backoffSeconds: 30 },
}));

/** Mock run history: finished tasks (scaled per agent) plus the current task. */
export function runsFor(agent: Agent): AgentRun[] {
  const idx = agents.findIndex((a) => a.id === agent.id);
  const finished = tasks.filter((t) => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(t.status));
  const runs: AgentRun[] = finished.map((t, i) => ({
    taskId: t.id,
    projectId: t.projectId,
    title: t.title,
    status: t.status === 'COMPLETED' ? 'Completed' : t.status === 'FAILED' && ['implement', 'test'].includes(agent.type) ? 'Failed' : t.status === 'CANCELLED' ? 'Cancelled' : 'Completed',
    startedAt: t.createdAt,
    durationSec: Math.round((t.durationSec ?? 900) * (agent.type === 'implement' ? 1 : 0.4 + ((i + idx) % 5) * 0.15)),
  }));
  if (agent.currentTaskId && agent.startedAt) {
    runs.push({
      taskId: agent.currentTaskId, projectId: agent.currentProjectId ?? '', title: agent.currentTaskTitle ?? '',
      status: 'Running', startedAt: agent.startedAt, durationSec: (Date.now() - new Date(agent.startedAt).getTime()) / 1000,
    });
  }
  return runs.sort((a, b) => a.startedAt.localeCompare(b.startedAt));
}
