import { activity, livePool, makeEvent } from '../../mocks/activity';
import { agentConfigs, agents, runsFor } from '../../mocks/agents';
import { approvals as approvalSeed } from '../../mocks/approvals';
import { metricsOverview } from '../../mocks/metrics';
import { projects } from '../../mocks/projects';
import { tasks } from '../../mocks/tasks';
import { workflows } from '../../mocks/workflows';
import type { ActivityEvent } from '../../types/activity';
import type { Approval, ApprovalStatus } from '../../types/approval';
import type { FactoryApi } from './contract';

const LATENCY_MS = 150;
const delay = <T>(value: T): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(structuredClone(value)), LATENCY_MS));

// Mutable in-memory state so mock approval actions are visible until reload.
const approvals: Approval[] = structuredClone(approvalSeed);
const statusFor = { APPROVE: 'APPROVED', REJECT: 'REJECTED', REQUEST_CHANGES: 'CHANGES_REQUESTED' } as const;

export const mockApi: FactoryApi = {
  listAgents: () => delay(agents),
  getAgent: (id) => delay(agents.find((a) => a.id === id)),
  getAgentConfig: (id) => delay(agentConfigs.find((c) => c.agentId === id)),
  getAgentRuns: (id) => {
    const agent = agents.find((a) => a.id === id);
    return delay(agent ? runsFor(agent) : []);
  },

  listTasks: (f = {}) => {
    const cutoff = f.sinceHours ? Date.now() - f.sinceHours * 3600_000 : 0;
    return delay(
      tasks
        .filter((t) => !f.projectId || t.projectId === f.projectId)
        .filter((t) => !f.agentId || t.assignedAgentId === f.agentId)
        .filter((t) => !f.status || t.status === f.status)
        .filter((t) => !f.workflowType || t.workflowType === f.workflowType)
        .filter((t) => !f.priority || t.priority === f.priority)
        .filter((t) => new Date(t.createdAt).getTime() >= cutoff)
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    );
  },
  getTask: (id) => delay(tasks.find((t) => t.id === id)),

  listWorkflows: () => delay(workflows),
  getWorkflow: (id) => delay(workflows.find((w) => w.id === id)),

  listProjects: () => delay(projects),

  listApprovals: () => delay(approvals),
  decideApproval: (id, input) => {
    const a = approvals.find((x) => x.id === id);
    if (!a) return Promise.reject(new Error(`Approval ${id} not found`));
    if (input.comment) a.comments.push({ author: 'You (mock)', at: new Date().toISOString(), text: input.comment });
    if (input.decision !== 'COMMENT') a.status = statusFor[input.decision] as ApprovalStatus;
    return delay(a);
  },

  listActivity: (f = {}) =>
    delay(
      activity
        .filter((e) => !f.agentId || e.sourceId === f.agentId)
        .filter((e) => !f.taskId || e.taskId === f.taskId)
        .filter((e) => !f.projectId || e.projectId === f.projectId)
        .slice(0, f.limit ?? 500),
    ),

  subscribeActivity: (onEvent) => {
    let i = 0;
    const timer = setInterval(() => {
      const [source, taskId, level, message] = livePool[i++ % livePool.length];
      const e: ActivityEvent = makeEvent(0, source, taskId, level, message);
      onEvent(e);
    }, 4000);
    return () => clearInterval(timer);
  },

  getMetricsOverview: () => delay(metricsOverview),
};
