import type { AgentMetrics } from './metrics';

export type AgentType = 'spec' | 'plan' | 'task' | 'implement' | 'review' | 'test' | 'fix';

export type AgentStatus = 'ONLINE' | 'BUSY' | 'IDLE' | 'WAITING' | 'ERROR' | 'DISABLED' | 'OFFLINE';

export interface Agent {
  id: string;
  name: string;
  type: AgentType;
  status: AgentStatus;
  statusDetail?: string;
  version: string;
  model: string;
  currentTaskId?: string;
  currentTaskTitle?: string;
  currentProjectId?: string;
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

export interface AgentRun {
  taskId: string;
  projectId: string;
  title: string;
  status: 'Running' | 'Completed' | 'Failed' | 'Cancelled';
  startedAt: string;
  durationSec: number;
}
