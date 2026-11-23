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

export type MapEventType = 'agent' | 'model' | 'step' | 'gate' | 'run';
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

export interface MapSnapshot {
  runId: string;
  status: string;
  budget: MapBudget;
  events: MapEvent[];
}
