/** Live map wire types: mirror src/asf/contracts/map_events.py (camelCase). */

export type MapStationId =
  | 'core'
  | 'operator'
  | 'model'
  | 'files'
  | 'shell'
  | 'network'
  | 'agents'
  | 'skills'
  | 'store'
  | 'gates';

export type MapEventType = 'agent' | 'model' | 'step' | 'gate' | 'run' | 'tool';
export type MapPhase = 'start' | 'end' | 'moment';
export type MapStatus = 'running' | 'ok' | 'error' | 'blocked';

export interface MapEvent {
  id: string;
  ts: string;
  runId: string;
  spanId: string;
  type: MapEventType;
  station: MapStationId;
  phase: MapPhase;
  status: MapStatus;
  label: string;
  taskId?: string | null;
  projectId?: string | null;
  agentId?: string | null;
  parentId?: string | null;
  stepId?: string | null;
  model?: string | null;
  durationMs?: number | null;
  promptTokens?: number | null;
  completionTokens?: number | null;
  errorCode?: string | null;
}

export interface MapBudget {
  usedTokens: number;
  limitTokens: number | null;
  usedCalls: number;
  limitCalls: number | null;
}

export interface MapCounters {
  stations: Record<string, number>;
  agents: Record<string, number>;
  errors: Record<string, number>;
}

export interface MapHosting {
  url: string;
  number: string;
}

export interface MapReplaySummary {
  runId: string;
  startedAt: string | null;
  sizeBytes: number;
  events: number;
  complete: boolean;
  truncated: boolean;
}

export interface MapReplay {
  runId: string;
  events: MapEvent[];
  counters: MapCounters | null;
  budget: MapBudget | null;
  complete: boolean;
  truncated: boolean;
}

export interface MapSnapshot {
  runId: string;
  status: string;
  budget: MapBudget;
  counters: MapCounters;
  hosting: MapHosting | null;
  events: MapEvent[];
}
