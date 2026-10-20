export type ActivityLevel = 'info' | 'success' | 'warn' | 'error';
export type ActivitySourceKind = 'agent' | 'orchestrator' | 'approval' | 'integration';

export interface ActivityEvent {
  id: string;
  timestamp: string; // ISO
  sourceKind: ActivitySourceKind;
  sourceId: string; // agent id, "orchestrator", "gitlab", ...
  sourceLabel: string;
  projectId?: string;
  taskId?: string;
  level: ActivityLevel;
  message: string;
}

export interface ActivityFilter {
  agentId?: string;
  taskId?: string;
  projectId?: string;
  limit?: number;
}
