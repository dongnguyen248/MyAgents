import type { AgentMetrics } from './metrics';

export type AgentType = 'spec' | 'plan' | 'task' | 'implement' | 'review' | 'test' | 'fix' | 'artifact-review';

export type AgentStatus = 'ONLINE' | 'BUSY' | 'IDLE' | 'WAITING' | 'ERROR' | 'DISABLED' | 'OFFLINE';

export interface Agent {
  id: string;
  name: string;
  type: AgentType;
  /** True for agents created by an operator; absent = a built-in platform agent. */
  custom?: boolean;
  status: AgentStatus;
  statusDetail?: string;
  version: string;
  model: string;
  /** Id of the configured LLM profile this agent runs on (see `LlmProfile`). */
  llmProfileId?: string;
  currentTaskId?: string;
  currentTaskTitle?: string;
  currentProjectId?: string;
  /** Catalogue skills that apply to this agent type (injected into its prompt on runs whose project enables them). */
  skills?: string[];
  startedAt?: string; // ISO, start of the current task
  lastActivityAt: string; // ISO
  metrics: AgentMetrics;
}

export interface AgentConfig {
  agentId: string;
  name: string;
  type: AgentType;
  enabled: boolean;
  model: string;
  modelVersion: string;
  systemPrompt: string;
  skills: string[];
  tools: string[];
  allowedProjectIds: string[];
  maxConcurrentTasks: number;
  timeoutSeconds: number;
  retryPolicy: { maxRetries: number; backoff: 'none' | 'linear' | 'exponential'; backoffSeconds: number };
}

/** What a create-agent request sends: the slug, the display name and the type it follows. */
export interface AgentInput {
  id: string;
  name: string;
  type: AgentType;
}

export interface AgentRun {
  taskId: string;
  projectId: string;
  title: string;
  status: 'Running' | 'Completed' | 'Failed' | 'Cancelled';
  startedAt: string;
  durationSec: number;
}
