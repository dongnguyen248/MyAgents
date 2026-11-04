import { activity, livePool, makeEvent } from '../../mocks/activity';
import { agentConfigs, agents, runsFor } from '../../mocks/agents';
import { approvals as approvalSeed } from '../../mocks/approvals';
import { metricsOverview } from '../../mocks/metrics';
import { projects } from '../../mocks/projects';
import { tasks } from '../../mocks/tasks';
import { workflows } from '../../mocks/workflows';
import type { ActivityEvent } from '../../types/activity';
import type { Approval, ApprovalStatus } from '../../types/approval';
import type { Project } from '../../types/project';
import type { Task } from '../../types/task';
import type { StepState, Workflow, WorkflowStep, WorkflowStepId } from '../../types/workflow';
import type { FactoryApi } from './contract';

const LATENCY_MS = 150;
const delay = <T>(value: T): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(structuredClone(value)), LATENCY_MS));

// Mutable in-memory state so mock approval actions are visible until reload.
const approvals: Approval[] = structuredClone(approvalSeed);
const projectStore = structuredClone(projects);
let modelSettings = { provider: 'scripted', model: '', baseUrl: '', apiKey: '' };
const modelSettingsView = () => ({
  provider: modelSettings.provider,
  model: modelSettings.model,
  baseUrl: modelSettings.baseUrl,
  keyConfigured: Boolean(modelSettings.apiKey),
  keyHint: modelSettings.apiKey.length >= 4 ? `…${modelSettings.apiKey.slice(-4)}` : '',
});
const taskStore: Task[] = structuredClone(tasks);
const workflowStore: Workflow[] = structuredClone(workflows);

const STEP_DEFS: [WorkflowStepId, string][] = [
  ['requirement', 'Requirement'], ['spec', 'Spec'], ['spec_approval', 'Spec Approval'],
  ['plan', 'Plan'], ['plan_approval', 'Plan Approval'], ['task', 'Task'], ['task_approval', 'Task Approval'],
  ['implementation', 'Implementation'], ['code_review', 'Code Review'], ['testing', 'Testing'],
  ['ci', 'CI'], ['merge', 'Merge'],
];

const freshSteps = (): WorkflowStep[] =>
  STEP_DEFS.map(([id, label], i) => ({ id, label, state: i === 0 ? 'active' : 'pending' }));
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
      taskStore
        .filter((t) => !f.projectId || t.projectId === f.projectId)
        .filter((t) => !f.agentId || t.assignedAgentId === f.agentId)
        .filter((t) => !f.status || t.status === f.status)
        .filter((t) => !f.workflowType || t.workflowType === f.workflowType)
        .filter((t) => !f.priority || t.priority === f.priority)
        .filter((t) => new Date(t.createdAt).getTime() >= cutoff)
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    );
  },
  getTask: (id) => delay(taskStore.find((t) => t.id === id)),

  startRun: (input) => {
    if (!projectStore.some((p) => p.id === input.projectId)) {
      return Promise.reject(new Error(`Project '${input.projectId}' not found`));
    }
    const now = new Date().toISOString();
    const task: Task = {
      id: input.taskId,
      title: input.title || input.taskId,
      projectId: input.projectId,
      workflowType: input.workflowType ?? 'feature-development',
      status: 'NEW',
      priority: input.priority ?? 'MEDIUM',
      createdAt: now,
      updatedAt: now,
      revisions: 0,
    };
    taskStore.unshift(task);
    const workflow: Workflow = {
      id: `wf-${input.taskId.toLowerCase()}`,
      taskId: input.taskId,
      title: task.title,
      projectId: input.projectId,
      type: task.workflowType,
      status: 'RUNNING',
      steps: freshSteps(),
      startedAt: now,
      updatedAt: now,
    };
    workflowStore.unshift(workflow);
    return delay(workflow);
  },

  listWorkflows: () => delay(workflowStore),
  getWorkflow: (id) => delay(workflowStore.find((w) => w.id === id)),

  tickRun: (runId) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) return Promise.reject(new Error(`Run '${runId}' not found`));
    // Mock advance: complete the active step, activate the next one.
    const active = workflow.steps.findIndex((s) => s.state === 'active');
    if (active >= 0) {
      workflow.steps[active].state = 'done';
      const next = workflow.steps[active + 1];
      if (next) next.state = 'active';
      else workflow.status = 'COMPLETED';
      workflow.updatedAt = new Date().toISOString();
      const task = taskStore.find((t) => t.id === workflow.taskId);
      if (task) {
        task.status = workflow.status === 'COMPLETED' ? 'COMPLETED' : 'IMPLEMENTING';
        task.updatedAt = workflow.updatedAt;
      }
    }
    return delay(workflow);
  },

  retryRun: (runId) => {
    const previous = workflowStore.find((w) => w.id === runId);
    if (!previous) return Promise.reject(new Error(`Run '${runId}' not found`));
    if (!['FAILED', 'CANCELLED', 'COMPLETED'].includes(previous.status)) {
      return Promise.reject(new Error('Only a finished run can be run again'));
    }
    const now = new Date().toISOString();
    const workflow: Workflow = {
      ...structuredClone(previous),
      id: `wf-${previous.taskId.toLowerCase()}-${Date.now()}`,
      status: 'RUNNING',
      steps: freshSteps(),
      startedAt: now,
      updatedAt: now,
      artifacts: undefined,
    };
    workflowStore.unshift(workflow);
    const task = taskStore.find((t) => t.id === previous.taskId);
    if (task) {
      task.status = 'NEW';
      task.updatedAt = now;
    }
    return delay(workflow);
  },

  resumeRun: (runId) => {
    const previous = workflowStore.find((w) => w.id === runId);
    if (!previous) return Promise.reject(new Error(`Run '${runId}' not found`));
    if (previous.status !== 'FAILED') {
      return Promise.reject(new Error('Only a failed run can be resumed'));
    }
    const now = new Date().toISOString();
    // Mock resume: steps before the failed one stay done; the failed step
    // becomes active again; later steps go back to pending. Artifacts are
    // kept, unlike retryRun which starts from a clean slate.
    const failedAt = previous.steps.findIndex((s) => s.state !== 'done');
    const steps = previous.steps.map((step, index) => ({
      ...step,
      state: (index < failedAt ? 'done' : index === failedAt ? 'active' : 'pending') as StepState,
    }));
    const workflow: Workflow = {
      ...structuredClone(previous),
      id: `wf-${previous.taskId.toLowerCase()}-${Date.now()}`,
      status: 'RUNNING',
      steps,
      startedAt: now,
      updatedAt: now,
    };
    workflowStore.unshift(workflow);
    const task = taskStore.find((t) => t.id === previous.taskId);
    if (task) {
      task.status = failedAt > 0 ? 'IMPLEMENTING' : 'NEW';
      task.updatedAt = now;
    }
    return delay(workflow);
  },

  listProjects: () => delay(projectStore),
  createProject: (input) => {
    if (projectStore.some((p) => p.id === input.id)) {
      return Promise.reject(new Error(`Project '${input.id}' already exists`));
    }
    const project: Project = {
      id: input.id,
      name: input.name,
      repositoryProvider: input.repository.provider,
      repositoryUrl: input.repository.url ?? '',
      repositoryPath: input.repository.path ?? '',
      testCommands: input.configuration.testCommands ?? [],
      technologies: [...input.technology.backend, ...input.technology.frontend],
      description: input.description ?? '',
      workflow: input.workflow,
      enabledSkills: input.enabledSkills,
      technologyGroups: { ...input.technology },
      approvalChannel: input.configuration.approval?.channel ?? '',
      agentIds: agents.map((a) => a.id),
      ci: 'UNKNOWN',
      ciFailures24h: 0,
      metrics: { activeAgents: 0, running: 0, completed: 0, failed: 0, successRate: 0, pendingApprovals: 0 },
    };
    projectStore.push(project);
    return delay(project);
  },
  updateProject: (id, input) => {
    const index = projectStore.findIndex((p) => p.id === id);
    if (index < 0) return Promise.reject(new Error(`Project '${id}' not found`));
    const updated: Project = {
      ...projectStore[index],
      name: input.name,
      description: input.description ?? projectStore[index].description,
      repositoryProvider: input.repository.provider,
      repositoryUrl: input.repository.url ?? '',
      repositoryPath: input.repository.path ?? '',
      testCommands: input.configuration.testCommands ?? [],
      technologies: [...input.technology.backend, ...input.technology.frontend],
      workflow: input.workflow,
      enabledSkills: input.enabledSkills,
      technologyGroups: { ...input.technology },
      approvalChannel: input.configuration.approval?.channel ?? '',
    };
    projectStore[index] = updated;
    return delay(updated);
  },
  deleteProject: (id) => {
    const index = projectStore.findIndex((p) => p.id === id);
    if (index < 0) return Promise.reject(new Error(`Project '${id}' not found`));
    projectStore.splice(index, 1);
    return delay(undefined);
  },

  listApprovals: () => delay(approvals),
  decideApproval: (id, input) => {
    const a = approvals.find((x) => x.id === id);
    if (!a) return Promise.reject(new Error(`Approval ${id} not found`));
    if (input.comment) a.comments.push({ author: 'You (mock)', at: new Date().toISOString(), text: input.comment });
    if (input.decision !== 'COMMENT') a.status = statusFor[input.decision] as ApprovalStatus;
    if (input.decision === 'APPROVE') {
      // Mock auto-advance: an approved run continues on its own — steps
      // complete until the next approval step becomes active (or the
      // workflow completes), mirroring the real backend's behaviour.
      const workflow = workflowStore.find(
        (w) => w.taskId === a.taskId && w.status === 'WAITING_APPROVAL',
      );
      if (workflow) {
        workflow.status = 'RUNNING';
        let idx = workflow.steps.findIndex((s) => s.state === 'active');
        while (idx >= 0) {
          workflow.steps[idx].state = 'done';
          const next = workflow.steps[idx + 1];
          if (!next) {
            workflow.status = 'COMPLETED';
            break;
          }
          next.state = 'active';
          if (next.id.endsWith('_approval')) {
            workflow.status = 'WAITING_APPROVAL';
            break;
          }
          idx += 1;
        }
        if (workflow.status === 'COMPLETED') {
          const task = taskStore.find((t) => t.id === workflow.taskId);
          if (task) task.status = 'COMPLETED';
        }
        workflow.updatedAt = new Date().toISOString();
      }
    }
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

  getModelSettings: () => delay(modelSettingsView()),

  updateModelSettings: (input) => {
    if (input.provider !== 'scripted' && !input.model.trim()) {
      return Promise.reject(new Error(`A model name is required for provider '${input.provider}'`));
    }
    if (input.provider === 'custom' && !/^https?:\/\//.test(input.baseUrl.trim())) {
      return Promise.reject(new Error('The custom provider needs a base URL (http/https)'));
    }
    modelSettings = {
      provider: input.provider,
      model: input.model.trim(),
      baseUrl: input.baseUrl.trim(),
      apiKey: input.clearKey ? '' : input.apiKey || modelSettings.apiKey,
    };
    return delay(modelSettingsView());
  },

  testModelSettings: () => {
    if (modelSettings.provider === 'scripted') {
      return delay({ ok: true, message: 'Scripted demo provider: no network call to test (mock).' });
    }
    if (!modelSettings.apiKey) {
      return delay({ ok: false, message: `No API key stored for provider '${modelSettings.provider}' (mock).` });
    }
    return delay({ ok: true, message: `Mock check passed for '${modelSettings.model}' (no real network call in mock mode).` });
  },
};
