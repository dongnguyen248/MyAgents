import { pickCurrentRun } from '../../lib/currentRun';
import { activity, livePool, makeEvent } from '../../mocks/activity';
import { agentConfigs, agents, makeAgentConfig, makeCustomAgent, runsFor } from '../../mocks/agents';
import { approvals as approvalSeed } from '../../mocks/approvals';
import { metricsOverview } from '../../mocks/metrics';
import { projects } from '../../mocks/projects';
import { agentProfileSeed, llmProfiles, MODELS_BY_PROVIDER } from '../../mocks/llmProfiles';
import { skills } from '../../mocks/skills';
import { tasks } from '../../mocks/tasks';
import { workflows } from '../../mocks/workflows';
import type { ActivityEvent } from '../../types/activity';
import type { Agent } from '../../types/agent';
import type { LlmProfile, LlmProfileInput } from '../../types/llm';
import type { Approval, ApprovalStatus } from '../../types/approval';
import type { Project, ProjectProfileInput } from '../../types/project';
import type { Task } from '../../types/task';
import type { RunDiagnostics, StepState, Workflow, WorkflowCurrentActivity, WorkflowStep, WorkflowStepId, WorkflowWaiting } from '../../types/workflow';
import type { FactoryApi } from './contract';

/** Mock parity for the backend's Now-card fields, by active step. */
const NOW_BY_STEP: Record<string, Partial<WorkflowCurrentActivity>> = {
  spec: { agentId: 'agent-spec', agentName: 'Specification Agent', model: 'claude-haiku-4.5', phase: 'PRODUCING' },
  plan: { agentId: 'agent-plan', agentName: 'Planning Agent', model: 'claude-haiku-4.5', phase: 'PRODUCING' },
  task: { agentId: 'agent-task', agentName: 'Task Agent', model: 'claude-haiku-4.5', phase: 'PRODUCING' },
  implementation: { agentId: 'agent-implement', agentName: 'Implementation Agent', model: 'claude-sonnet-5.5', phase: 'PRODUCING' },
  code_review: { agentId: 'agent-review', agentName: 'Review Agent', model: 'gpt-4.1', phase: 'PRODUCING' },
  testing: { agentId: 'agent-test', agentName: 'Test Agent', model: null, phase: 'RUNNING_TESTS' },
  ci: { agentId: null, agentName: null, model: null, phase: 'WAITING_ON_CI' },
  merge: { agentId: null, agentName: null, model: null, phase: 'WAITING_FOR_MERGE' },
};

interface MockNowExample {
  waiting?: Partial<WorkflowWaiting>;
  activity: Omit<WorkflowCurrentActivity, 'since' | 'lastEventAt' | 'recentEvents'>;
  /** Recent events, newest last; agoSec is relative to the workflow's updatedAt. */
  events: { type: string; message: string; agoSec: number }[];
}

/** Full Now-card examples for specific seed workflows. */
const NOW_EXAMPLES: Record<string, MockNowExample> = {
  'wf-vhpc-1024': {
    waiting: {
      kind: 'AI_REVIEW',
      stage: 'SPEC',
      round: 2,
      maxRounds: 4,
      reason: 'AI review of Write specification in progress (round 2 of 4)',
      suggestedActions: ['approve', 'reject', 'cancel'],
    },
    activity: {
      kind: 'AI_REVIEW',
      stepId: 'spec_approval',
      stepLabel: 'Spec Approval',
      stage: 'SPEC_REVIEW',
      reason: 'AI review of Write specification in progress (round 2 of 4)',
      retryAt: null,
      agentId: 'agent-artifact-review',
      agentName: 'Artifact Review Agent',
      model: 'gpt-4.1',
      phase: 'AI_REVIEWING',
      attempt: 2,
      attemptMax: 4,
    },
    events: [
      { type: 'AI_REVIEW_STARTED', message: 'AI review started for SPEC', agoSec: 240 },
      { type: 'AGENT_COMPLETED', message: 'Specification Agent produced SPEC v2', agoSec: 180 },
      { type: 'AI_REVIEW_STARTED', message: 'AI review round 2 started for SPEC', agoSec: 45 },
    ],
  },
  'wf-vnpc-2041': {
    activity: {
      kind: 'APPROVAL',
      stepId: 'plan_approval',
      stepLabel: 'Plan Approval',
      stage: 'PLAN_REVIEW',
      reason: 'Waiting for approval',
      retryAt: null,
      agentId: null,
      agentName: null,
      model: null,
      phase: 'WAITING_FOR_APPROVAL',
      attempt: null,
      attemptMax: null,
    },
    events: [{ type: 'APPROVAL_REQUESTED', message: 'Approval requested for PLAN', agoSec: 600 }],
  },
  'wf-vhpc-1023': {
    activity: {
      kind: 'STEP_RUNNING',
      stepId: 'implementation',
      stepLabel: 'Implementation',
      stage: 'CODE_FIX',
      reason: null,
      retryAt: null,
      agentId: 'agent-fix',
      agentName: 'Fix Agent',
      model: 'claude-sonnet-5.5',
      phase: 'FIXING',
      attempt: 2,
      attemptMax: 3,
    },
    events: [
      { type: 'WORKFLOW_STAGE_CHANGED', message: 'Stage changed to CODE_FIX', agoSec: 900 },
      { type: 'AGENT_STARTED', message: 'Fix Agent started fix attempt 2', agoSec: 870 },
      { type: 'TEST_FAILED', message: 'Tests failed: 2 of 48 assertions', agoSec: 300 },
    ],
  },
};

/** The generic enriched activity for a running mock workflow. */
const nowActivityFor = (workflow: Workflow, active: WorkflowStep | undefined): WorkflowCurrentActivity => ({
  kind: 'STEP_RUNNING',
  stepId: active?.id ?? null,
  stepLabel: active?.label ?? null,
  stage: null,
  since: workflow.updatedAt,
  retryAt: null,
  agentId: null,
  agentName: null,
  model: null,
  phase: null,
  attempt: null,
  attemptMax: null,
  lastEventAt: workflow.updatedAt,
  recentEvents: [],
  ...(active ? NOW_BY_STEP[active.id] : undefined),
});

/** A seed workflow's full example activity, with times made relative. */
const exampleActivity = (workflow: Workflow, example: MockNowExample): WorkflowCurrentActivity => {
  const base = Date.parse(workflow.updatedAt);
  const events = example.events.map((event) => ({
    type: event.type,
    message: event.message,
    at: new Date(base - event.agoSec * MS_PER_SECOND).toISOString(),
  }));
  return {
    ...example.activity,
    since: workflow.updatedAt,
    lastEventAt: events.length ? events[events.length - 1].at : workflow.updatedAt,
    recentEvents: events,
  };
};

const LATENCY_MS = 150;
const MS_PER_SECOND = 1000;
const delay = <T>(value: T): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(structuredClone(value)), LATENCY_MS));

/** Mock parity for the backend's live currentActivity on running workflows. */
const withLiveActivity = (workflow: Workflow): Workflow => {
  const base: Workflow = {
    ...workflow,
    waiting: workflow.waiting ?? {
      kind:
        workflow.status === 'WAITING_APPROVAL'
          ? 'APPROVAL'
          : workflow.status === 'ESCALATED'
            ? 'ESCALATED'
            : workflow.status === 'WAITING_RETRY'
              ? 'RETRY_WAIT'
              : workflow.status === 'RUNNING'
                ? 'STEP_RUNNING'
                : 'NONE',
      since: workflow.updatedAt,
      reason: workflow.status === 'ESCALATED' ? 'Escalated — fix budget used, needs operator' : null,
      retryAt: null,
      budget: null,
      suggestedActions: workflow.status === 'ESCALATED' ? ['resume', 'cancel'] : [],
    },
    driver: workflow.driver ?? {
      alive: workflow.status === 'RUNNING',
      lastTickAt: workflow.status === 'RUNNING' ? workflow.updatedAt : null,
      lastStopReason: null,
    },
  };
  const example = NOW_EXAMPLES[workflow.id];
  if (example) {
    return {
      ...base,
      waiting: { ...base.waiting!, ...example.waiting },
      currentActivity: exampleActivity(workflow, example),
    };
  }
  if (workflow.status !== 'RUNNING') {
    return base;
  }
  const active = workflow.steps.find((s) => s.state === 'active');
  return { ...base, currentActivity: nowActivityFor(workflow, active) };
};

// Mutable in-memory state so mock approval actions are visible until reload.
const approvals: Approval[] = structuredClone(approvalSeed);
const projectStore = structuredClone(projects);
/** Mock hosting tokens: stored apart from the project views, like the backend. */
const hostingTokenStore: Record<string, string> = {};
const tokenHint = (token: string): string => (token.length >= 4 ? `…${token.slice(-4)}` : '…');

const rememberHostingToken = (id: string, token?: string): void => {
  if (token) {
    hostingTokenStore[id] = token;
  }
};

const applyHostingTokenInput = (id: string, input: ProjectProfileInput): void => {
  if (input.clearHostingToken) {
    delete hostingTokenStore[id];
  }
  if (input.hostingToken) {
    hostingTokenStore[id] = input.hostingToken;
  }
};
const keyHintFor = (key: string): string =>
  key.length >= 4 ? `\u2026${key.slice(-4)}` : '';
const taskStore: Task[] = structuredClone(tasks);
const workflowStore: Workflow[] = structuredClone(workflows);

/** Mock parity for the backend's current-run selection on task views. */
function currentRunIdFor(taskId: string): string | undefined {
  const pool = workflowStore.filter((w) => w.taskId === taskId || w.parentTaskId === taskId);
  return pickCurrentRun(pool)?.id;
}

function withCurrentRun(task: Task): Task {
  const currentRunId = currentRunIdFor(task.id);
  if (currentRunId === undefined) {
    return task;
  }
  return { ...task, currentRunId };
}

/** Mock parity for the backend's by-task workflow lookup fallback. */
function workflowByTask(taskId: string): Workflow | undefined {
  return pickCurrentRun(workflowStore.filter((w) => w.taskId === taskId));
}

const STEP_DEFS: [WorkflowStepId, string][] = [
  ['requirement', 'Requirement'], ['spec', 'Spec'], ['spec_approval', 'Spec Approval'],
  ['plan', 'Plan'], ['plan_approval', 'Plan Approval'], ['task', 'Task'], ['task_approval', 'Task Approval'],
  ['implementation', 'Implementation'], ['code_review', 'Code Review'], ['testing', 'Testing'],
  ['ci', 'CI'], ['merge', 'Merge'],
];

const freshSteps = (): WorkflowStep[] =>
  STEP_DEFS.map(([id, label], i) => ({ id, label, state: i === 0 ? 'active' : 'pending' }));
const statusFor = { APPROVE: 'APPROVED', REJECT: 'REJECTED', REQUEST_CHANGES: 'CHANGES_REQUESTED' } as const;

const profileStore: LlmProfile[] = llmProfiles.map((profile) => ({ ...profile }));
/** agent id -> profile id; the seed keeps the demo agents on sensible profiles. */
const agentProfile: Record<string, string> = { ...agentProfileSeed };
const withProfile = (agent: Agent): Agent =>
  agentProfile[agent.id] ? { ...agent, llmProfileId: agentProfile[agent.id] } : agent;
const findAgent = (id: string): Agent | undefined => {
  const agent = agents.find((entry) => entry.id === id);
  return agent ? withProfile(agent) : undefined;
};

function validateProfile(input: LlmProfileInput): void {
  if (!input.name.trim()) {
    throw new Error('A profile needs a name');
  }
  if (input.provider !== 'scripted' && !input.model.trim()) {
    throw new Error('Pick a model — load the list from the endpoint first');
  }
  if (input.provider === 'custom' && !/^https?:\/\//.test(input.baseUrl.trim())) {
    throw new Error('The custom provider needs a base URL (http/https)');
  }
}

function keyFields(input: LlmProfileInput, existing?: LlmProfile): Pick<LlmProfile, 'keyConfigured' | 'keyHint'> {
  const key = input.apiKey?.trim() ?? '';
  if (input.clearKey) {
    return { keyConfigured: false, keyHint: '' };
  }
  return {
    keyConfigured: key !== '' || Boolean(existing?.keyConfigured),
    keyHint: keyHintFor(key) || existing?.keyHint || '',
  };
}

function mergeProfile(input: LlmProfileInput, existing?: LlmProfile): LlmProfile {
  return {
    id: input.id,
    name: input.name.trim(),
    provider: input.provider,
    baseUrl: input.baseUrl.trim(),
    model: input.model.trim(),
    models: input.models ?? existing?.models,
    ...keyFields(input, existing),
  };
}

const mockSkillOverrides: Record<string, string[]> = {};
const mockRuleOverrides: Record<string, string[]> = {};
let mockModelSettings = { provider: 'scripted', model: '', baseUrl: '', keyConfigured: false,
  agentModels: {} as Record<string, string>, agentConnections: {} as Record<string, import('../../types/agentSetup').AgentConnection> };

export const mockApi: FactoryApi = {
  listAgents: () => delay(agents.map(withProfile)),
  getAgent: (id) => delay(findAgent(id)),
  getAgentConfig: (id) => delay(agentConfigs.find((c) => c.agentId === id)),
  getAgentRuns: (id) => {
    const agent = agents.find((a) => a.id === id);
    return delay(agent ? runsFor(agent) : []);
  },
  listSkills: () => delay(skills),
  listRules: () => delay([]),
  getAgentRules: (id) => delay(mockRuleOverrides[id] ?? []),
  saveAgentRules: (id, rules) => {
    mockRuleOverrides[id] = [...rules];
    return delay([...rules]);
  },
  readRuleFile: async () => { throw new Error('Rule files require the API backend.'); },
  saveRuleFile: async () => { throw new Error('Rule files require the API backend.'); },
  getAgentSkills: (id) => delay(mockSkillOverrides[id] ?? agentConfigs.find((config) => config.agentId === id)?.skills ?? []),
  saveAgentSkills: (id, selected) => {
    mockSkillOverrides[id] = [...selected];
    return delay([...selected]);
  },
  getModelSettings: () => delay(mockModelSettings),
  saveAgentModel: (input) => {
    const previous = mockModelSettings.agentConnections[input.agent];
    mockModelSettings = { ...mockModelSettings,
      agentModels: { ...mockModelSettings.agentModels, [input.agent]: input.model },
      agentConnections: { ...mockModelSettings.agentConnections, [input.agent]: { provider: input.provider,
        baseUrl: input.baseUrl, keyConfigured: input.clearKey ? false : Boolean(input.apiKey || previous?.keyConfigured) } } };
    return delay(mockModelSettings);
  },
  readSkillFile: async () => { throw new Error('File access requires the API backend.'); },
  saveSkillFile: async () => { throw new Error('File access requires the API backend.'); },

  listLlmProfiles: () => delay(profileStore.map((profile) => ({ ...profile }))),

  saveLlmProfile: (input) => {
    validateProfile(input);
    const at = profileStore.findIndex((profile) => profile.id === input.id);
    const next = mergeProfile(input, at >= 0 ? profileStore[at] : undefined);
    if (at >= 0) {
      profileStore[at] = next;
    } else {
      profileStore.push(next);
    }
    return delay(next);
  },

  deleteLlmProfile: (id) => {
    const at = profileStore.findIndex((profile) => profile.id === id);
    if (at >= 0) {
      profileStore.splice(at, 1);
    }
    for (const [agentId, profileId] of Object.entries(agentProfile)) {
      if (profileId === id) {
        delete agentProfile[agentId];
      }
    }
    return delay(undefined);
  },

  loadLlmModels: (request) => {
    if (request.provider !== 'scripted') {
      const stored = profileStore.find((profile) => profile.id === request.profileId);
      const hasKey = Boolean(request.apiKey?.trim()) || Boolean(stored?.keyConfigured);
      if (!hasKey) {
        return Promise.reject(new Error('Enter the API key first — the endpoint needs it to list models'));
      }
    }
    if (request.provider === 'custom' && !/^https?:\/\//.test(request.baseUrl.trim())) {
      return Promise.reject(new Error('The custom provider needs a base URL (http/https)'));
    }
    return delay(MODELS_BY_PROVIDER[request.provider] ?? []);
  },

  testLlmProfile: (id) => {
    const profile = profileStore.find((entry) => entry.id === id);
    if (!profile) {
      return Promise.reject(new Error(`Unknown profile '${id}'`));
    }
    if (profile.provider === 'scripted') {
      return delay({ ok: true, message: 'Scripted provider answers from a fixture — nothing to reach.' });
    }
    if (!profile.model.trim()) {
      return delay({ ok: false, message: 'No model selected for this profile.' });
    }
    return delay({ ok: true, message: `${profile.model} answered from ${profile.baseUrl || profile.provider}.` });
  },

  assignAgentProfile: (agentId, profileId) => {
    const agent = agents.find((entry) => entry.id === agentId);
    if (!agent) {
      return Promise.reject(new Error(`Unknown agent '${agentId}'`));
    }
    if (profileId) {
      agentProfile[agentId] = profileId;
    } else {
      delete agentProfile[agentId];
    }
    return delay(withProfile(agent));
  },
  createAgent: (input) => {
    const created = makeCustomAgent(input);
    agents.push(created);
    agentConfigs.push(makeAgentConfig(input));
    return delay(created);
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
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
        .map(withCurrentRun),
    );
  },
  getTask: (id) => {
    const task = taskStore.find((t) => t.id === id);
    return delay(task && withCurrentRun(task));
  },

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
      skippedApprovals: input.skipApprovals ?? [],
      steps: freshSteps(),
      startedAt: now,
      updatedAt: now,
    };
    workflowStore.unshift(workflow);
    return delay(workflow);
  },

  listWorkflows: () => delay(workflowStore.map(withLiveActivity)),
  getWorkflow: (id) => {
    const workflow = workflowStore.find((w) => w.id === id) ?? workflowByTask(id);
    return delay(workflow && withLiveActivity(workflow));
  },

  getRunDiagnostics: (runId) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return delay(undefined);
    }
    const view = withLiveActivity(workflow);
    const diagnostics: RunDiagnostics = {
      runId: workflow.id,
      taskId: workflow.taskId,
      projectId: workflow.projectId,
      stage: view.currentActivity?.stage ?? workflow.status,
      stageKind: 'STEP',
      status: workflow.status,
      waiting: view.waiting!,
      inFlight:
        workflow.status === 'RUNNING'
          ? { token: 'mock-in-flight', ageSeconds: 5 }
          : null,
      retryAt: view.waiting?.retryAt ?? null,
      fixBudget: view.waiting?.budget ?? { used: 0, max: 3 },
      revisions: {},
      lastEvents: activity
        .filter((e) => e.taskId === workflow.taskId)
        .slice(-20)
        .map((e) => ({
          type: e.sourceKind.toUpperCase(),
          message: e.message,
          at: e.timestamp,
          metadata: e.metadata ?? {},
        })),
      lastError: workflow.error
        ? {
            code: workflow.error.code,
            message: workflow.error.message,
            category: workflow.error.category,
            retryable: false,
            at: workflow.error.at ?? workflow.updatedAt,
            details: workflow.error.details ?? null,
          }
        : null,
      driver: view.driver!,
      suggestedActions: view.waiting?.suggestedActions ?? [],
    };
    return delay(diagnostics);
  },

  getRunReviews: (runId) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return delay(undefined);
    }
    // Mock mode has no AI review loop; report an empty history.
    return delay({ runId: workflow.id, stages: [] });
  },

  tickRun: (runId) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    // Mock advance: complete the active step, activate the next one.
    const active = workflow.steps.findIndex((s) => s.state === 'active');
    if (active >= 0) {
      workflow.steps[active].state = 'done';
      let next = workflow.steps[active + 1];
      // Approval gates this task chose to skip are passed over.
      if (
        next && next.id.endsWith('_approval')
        && workflow.skippedApprovals?.includes(next.id.replace('_approval', ''))
      ) {
        next.state = 'skipped';
        next = workflow.steps[active + 2];
      }
      if (next) {
        next.state = 'active';
      }
      else {workflow.status = 'COMPLETED';}
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
    if (!previous) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
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
    if (!previous) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
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

  cancelRun: (runId) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    if (['FAILED', 'CANCELLED', 'COMPLETED'].includes(workflow.status)) {
      return Promise.reject(new Error('Only an active run can be cancelled'));
    }
    workflow.status = 'CANCELLED';
    workflow.updatedAt = new Date().toISOString();
    const task = taskStore.find((t) => t.id === workflow.taskId);
    if (task) {
      task.status = 'CANCELLED';
      task.updatedAt = workflow.updatedAt;
    }
    return delay(workflow);
  },

  resumeEscalation: (runId, reason) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    if (!reason.trim()) {
      return Promise.reject(new Error('reason is required'));
    }
    if (workflow.status !== 'ESCALATED') {
      return Promise.reject(new Error('Only an escalated run can be resumed with a new fix budget'));
    }
    workflow.status = 'RUNNING';
    workflow.waiting = { kind: 'STEP_RUNNING', since: new Date().toISOString(), reason: null, retryAt: null, budget: null, suggestedActions: [] };
    const fix = workflow.steps.find((s) => s.id === 'fix');
    if (fix) {
      fix.state = 'active';
      fix.label = 'Fix code · fix 1/3';
    }
    workflow.updatedAt = new Date().toISOString();
    return delay(workflow);
  },


  recoverRun: (runId, reason, retryInterrupted) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    if (!reason.trim()) {
      return Promise.reject(new Error('reason is required'));
    }
    workflow.status = retryInterrupted ? 'RUNNING' : 'FAILED';
    if (!retryInterrupted) {
      workflow.error = { code: 'AGENT_EXECUTION_FAILED', message: 'Interrupted dispatch not replayed', category: 'AGENT' };
    }
    workflow.updatedAt = new Date().toISOString();
    return delay(workflow);
  },

  driveRun: (runId) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    workflow.driver = { alive: true, lastTickAt: new Date().toISOString(), lastStopReason: null };
    return delay(workflow);
  },

  failRun: (runId, reason) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    if (!reason.trim()) {
      return Promise.reject(new Error('reason is required'));
    }
    workflow.status = 'FAILED';
    workflow.error = { code: 'OPERATOR_FAILED', message: `Failed by operator: ${reason}`, category: 'WORKFLOW' };
    workflow.updatedAt = new Date().toISOString();
    return delay(workflow);
  },

  pauseRun: (runId) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    workflow.status = 'PAUSED';
    workflow.waiting = { kind: 'PAUSED', since: new Date().toISOString(), reason: 'Paused by operator — no step will start until continued', retryAt: null, budget: null, suggestedActions: ['continue', 'cancel'] };
    workflow.updatedAt = new Date().toISOString();
    return delay(workflow);
  },

  continueRun: (runId) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    workflow.status = 'RUNNING';
    workflow.waiting = { kind: 'STEP_RUNNING', since: new Date().toISOString(), reason: null, retryAt: null, budget: null, suggestedActions: [] };
    workflow.updatedAt = new Date().toISOString();
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
      workspaceMode: input.repository.workspaceMode ?? 'direct',
      keepChangesOnFailure: input.repository.keepChangesOnFailure ?? false,
      testCommands: input.configuration.testCommands ?? [],
      technologies: [...input.technology.backend, ...input.technology.frontend],
      description: input.description ?? '',
      workflow: input.workflow,
      enabledSkills: input.enabledSkills, enabledRules: input.enabledRules ?? [],
      technologyGroups: { ...input.technology },
      ...approvalFieldsOf(input),
      hostingTokenConfigured: Boolean(input.hostingToken),
      hostingTokenHint: input.hostingToken ? tokenHint(input.hostingToken) : null,
      agentIds: agents.map((a) => a.id),
      ci: 'UNKNOWN',
      ciFailures24h: 0,
      metrics: { activeAgents: 0, running: 0, completed: 0, failed: 0, successRate: 0, pendingApprovals: 0 },
    };
    rememberHostingToken(input.id, input.hostingToken);
    projectStore.push(project);
    return delay(project);
  },
  updateProject: (id, input) => {
    const index = projectStore.findIndex((p) => p.id === id);
    if (index < 0) {
      return Promise.reject(new Error(`Project '${id}' not found`));
    }
    applyHostingTokenInput(id, input);
    const stored = hostingTokenStore[id];
    const updated: Project = {
      ...projectStore[index],
      name: input.name,
      description: input.description ?? projectStore[index].description,
      repositoryProvider: input.repository.provider,
      repositoryUrl: input.repository.url ?? '',
      repositoryPath: input.repository.path ?? '',
      workspaceMode: input.repository.workspaceMode ?? projectStore[index].workspaceMode,
      keepChangesOnFailure:
        input.repository.keepChangesOnFailure ?? projectStore[index].keepChangesOnFailure,
      hostingTokenConfigured: Boolean(stored),
      hostingTokenHint: stored ? tokenHint(stored) : null,
      testCommands: input.configuration.testCommands ?? [],
      technologies: [...input.technology.backend, ...input.technology.frontend],
      workflow: input.workflow,
      enabledSkills: input.enabledSkills, enabledRules: input.enabledRules ?? [],
      technologyGroups: { ...input.technology },
      ...approvalFieldsOf(input),
    };
    projectStore[index] = updated;
    return delay(updated);
  },
  deleteProject: (id) => {
    const index = projectStore.findIndex((p) => p.id === id);
    if (index < 0) {
      return Promise.reject(new Error(`Project '${id}' not found`));
    }
    projectStore.splice(index, 1);
    delete hostingTokenStore[id];
    return delay(undefined);
  },

  listApprovals: () => delay(approvals),
  decideApproval: (id, input) => {
    const a = approvals.find((x) => x.id === id);
    if (!a) {
      return Promise.reject(new Error(`Approval ${id} not found`));
    }
    if (input.comment) {
      a.comments.push({ author: 'You (mock)', at: new Date().toISOString(), text: input.comment });
    }
    if (input.decision !== 'COMMENT') {
      a.status = statusFor[input.decision] as ApprovalStatus;
    }
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
          if (task) {
            task.status = 'COMPLETED';
          }
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

  // The live map exists only on the real backend; mock mode has no pulses.
  getMapSnapshot: () => delay(undefined),

  subscribeMapEvents: () => () => undefined,

  getMetricsOverview: () => delay(metricsOverview),

  approveEscalation: (runId, reason) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    if (!reason.trim()) {
      return Promise.reject(new Error('reason is required'));
    }
    if (workflow.status !== 'ESCALATED') {
      return Promise.reject(new Error('Only an escalated approval gate can be approved anyway'));
    }
    workflow.status = 'RUNNING';
    workflow.waiting = {
      kind: 'STEP_RUNNING',
      since: new Date().toISOString(),
      reason: null,
      retryAt: null,
      budget: null,
      suggestedActions: [],
    };
    workflow.updatedAt = new Date().toISOString();
    return delay(workflow);
  },

  skipTests: (runId, reason) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    if (!reason.trim()) {
      return Promise.reject(new Error('reason is required'));
    }
    if (workflow.status !== 'ESCALATED') {
      return Promise.reject(
        new Error('Only a run stopped for a no-tests decision can skip its tests'),
      );
    }
    workflow.status = 'RUNNING';
    workflow.waiting = {
      kind: 'STEP_RUNNING',
      since: new Date().toISOString(),
      reason: null,
      retryAt: null,
      budget: null,
      suggestedActions: [],
    };
    workflow.updatedAt = new Date().toISOString();
    return delay(workflow);
  },

  replaceTestCommands: (runId, commands) => {
    const workflow = workflowStore.find((w) => w.id === runId);
    if (!workflow) {
      return Promise.reject(new Error(`Run '${runId}' not found`));
    }
    if (commands.length === 0) {
      return Promise.reject(new Error('Provide at least one test command'));
    }
    if (workflow.status !== 'ESCALATED') {
      return Promise.reject(
        new Error('Only a run stopped for a no-tests decision can replace its test commands'),
      );
    }
    workflow.status = 'RUNNING';
    workflow.waiting = {
      kind: 'STEP_RUNNING',
      since: new Date().toISOString(),
      reason: null,
      retryAt: null,
      budget: null,
      suggestedActions: [],
    };
    workflow.updatedAt = new Date().toISOString();
    return delay(workflow);
  },
};

function approvalFieldsOf(input: ProjectProfileInput) {
  return {
    approvalChannel: input.configuration.approval?.channel ?? '',
    approvalMode: input.configuration.approval?.mode ?? '',
    approvalMaxRevisions: input.configuration.approval?.maxRevisions ?? null,
    approvalOnExhausted: input.configuration.approval?.onExhausted ?? '',
  };
}
