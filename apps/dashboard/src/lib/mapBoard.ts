// The live map board: pulses folded into entries, counts and feed rows.
//
// Pure functions over the wire events (types/map.ts), in the spirit of
// lot-map's board/feed (MIT, (c) Aleksei Volodin): a start and its end
// share a span id and become one entry; consecutive finished entries
// at one station for one agent fold into a single feed row. Nothing
// here touches the network or the DOM, so it is unit-testable as-is.
import type { MapCounters, MapEvent, MapStationId, MapStatus } from '../types/map.ts';

const PERCENT_WHOLE = 100;
const MS_PER_SECOND = 1000;
const DEFAULT_FEED_LIMIT = 16;

const SPOKE_BASE_WIDTH = 1.5;
const SPOKE_MAX_BONUS = 4;
const SPOKE_CALLS_PER_STEP = 10;

export function spokeWidth(total: number): number {
  const bonus = Math.min(SPOKE_MAX_BONUS, Math.floor(total / SPOKE_CALLS_PER_STEP));
  return SPOKE_BASE_WIDTH + bonus;
}

export interface MapEntry {
  spanId: string;
  type: MapEvent['type'];
  station: MapStationId;
  agentId: string | null;
  parentId: string | null;
  stepId: string | null;
  label: string;
  status: MapStatus;
  startedAt: string;
  endedAt: string | null;
  durationMs: number | null;
  model: string | null;
  errorCode: string | null;
  promptTokens: number;
  completionTokens: number;
}

export interface BoardState {
  entries: MapEntry[];
}

export interface StationCount {
  total: number;
  running: number;
  faults: number;
}

export interface FeedRow {
  entry: MapEntry;
  times: number;
}

export interface AgentState {
  agentId: string;
  status: 'running' | 'failed' | 'done';
  lastLabel: string;
  totalMs: number;
  calls: number;
}

export const STATION_ORDER: { id: MapStationId; label: string }[] = [
  { id: 'operator', label: 'Operator' },
  { id: 'model', label: 'Model' },
  { id: 'store', label: 'Store' },
  { id: 'files', label: 'Files' },
  { id: 'shell', label: 'Shell' },
  { id: 'network', label: 'Network' },
  { id: 'agents', label: 'Agents' },
  { id: 'skills', label: 'Skills' },
  { id: 'gates', label: 'Gates' },
];

export const AGENT_COLORS: Record<string, string> = {
  'agent-spec': '#2b5fd9',
  'agent-plan': '#8a3fb0',
  'agent-task': '#c96f12',
  'agent-implement': '#17803f',
  'agent-review': '#b3261e',
  'agent-test': '#0e7c86',
  'agent-fix': '#d6336c',
  'agent-artifact-review': '#5f3dc4',
};

export function agentColor(agentId: string | null): string {
  if (agentId === null) {
    return '#6b7280';
  }
  return AGENT_COLORS[agentId] ?? '#6b7280';
}

export function emptyBoard(): BoardState {
  return { entries: [] };
}

function entryFrom(event: MapEvent): MapEntry {
  return {
    spanId: event.spanId,
    type: event.type,
    station: event.station,
    agentId: event.agentId ?? null,
    parentId: event.parentId ?? null,
    stepId: event.stepId ?? null,
    label: event.label,
    status: event.status,
    startedAt: event.ts,
    endedAt: event.phase === 'moment' ? event.ts : null,
    durationMs: event.durationMs ?? null,
    model: event.model ?? null,
    errorCode: event.errorCode ?? null,
    promptTokens: event.promptTokens ?? 0,
    completionTokens: event.completionTokens ?? 0,
  };
}

function closeEntry(entry: MapEntry, event: MapEvent): MapEntry {
  return {
    ...entry,
    status: event.status,
    endedAt: event.ts,
    durationMs: event.durationMs ?? entry.durationMs,
    label: event.label || entry.label,
    model: event.model ?? entry.model,
    errorCode: event.errorCode ?? entry.errorCode,
    promptTokens: event.promptTokens ?? entry.promptTokens,
    completionTokens: event.completionTokens ?? entry.completionTokens,
  };
}

export function applyMapEvent(board: BoardState, event: MapEvent): BoardState {
  if (event.phase === 'end') {
    const index = board.entries.findIndex((e) => e.spanId === event.spanId);
    if (index === -1) {
      return { entries: [...board.entries, entryFrom(event)] };
    }
    const entries = board.entries.slice();
    entries[index] = closeEntry(entries[index], event);
    return { entries };
  }
  if (event.phase === 'start') {
    const exists = board.entries.some((e) => e.spanId === event.spanId);
    if (exists) {
      return board;
    }
  }
  return { entries: [...board.entries, entryFrom(event)] };
}

export function applyMapEvents(board: BoardState, events: MapEvent[]): BoardState {
  let next = board;
  for (const event of events) {
    next = applyMapEvent(next, event);
  }
  return next;
}

type CountMap = Partial<Record<MapStationId, StationCount>>;

function mergeCounters(counts: CountMap, counters: MapCounters): void {
  for (const station of STATION_ORDER) {
    const total = counters.stations[station.id];
    if (total === undefined) {
      continue;
    }
    const current = counts[station.id] ?? { total: 0, running: 0, faults: 0 };
    current.total = Math.max(current.total, total);
    current.faults = Math.max(current.faults, counters.errors[station.id] ?? 0);
    counts[station.id] = current;
  }
}

export interface ModelChange {
  key: string;
  at: string;
  fromModel: string;
  toModel: string;
  agentId: string | null;
}

/** Model switches inside this board's run: consecutive model spans
 * whose model differs. Compared within the run only - a board never
 * holds another run's entries. */
export function modelChanges(board: BoardState): ModelChange[] {
  const spans = board.entries
    .filter((entry) => entry.type === 'model' && entry.model)
    .sort((a, b) => a.startedAt.localeCompare(b.startedAt));
  const changes: ModelChange[] = [];
  let previous: string | null = null;
  for (const entry of spans) {
    if (previous !== null && entry.model !== previous) {
      changes.push({
        key: `change:${entry.spanId}`,
        at: entry.startedAt,
        fromModel: previous,
        toModel: entry.model as string,
        agentId: entry.agentId,
      });
    }
    previous = entry.model;
  }
  return changes;
}

export const MODEL_FLASH_WINDOW_MS = 4000;

function latestBoardTs(board: BoardState): number {
  let latest = 0;
  for (const entry of board.entries) {
    latest = Math.max(latest, Date.parse(entry.endedAt ?? entry.startedAt));
  }
  return latest;
}

/** True while the newest model change is still fresh relative to the
 * board's own timeline (not the wall clock, so a loaded snapshot of
 * a finished run does not flash forever). */
export function isModelFlashing(board: BoardState): boolean {
  const changes = modelChanges(board);
  if (changes.length === 0) {
    return false;
  }
  const changeAt = Date.parse(changes[changes.length - 1].at);
  return latestBoardTs(board) - changeAt <= MODEL_FLASH_WINDOW_MS;
}

export interface RunningAgent {
  spanId: string;
  agentId: string | null;
  color: string;
}

/** One entry per agent execution in flight - the orbit dots around
 * the Agents station. An execution that ended leaves the list, so
 * its dot disappears with its span. */
export function runningAgents(board: BoardState): RunningAgent[] {
  return board.entries
    .filter((entry) => entry.type === 'agent' && entry.status === 'running')
    .map((entry) => ({
      spanId: entry.spanId,
      agentId: entry.agentId,
      color: agentColor(entry.agentId),
    }));
}

export type FeedItem = { kind: 'row'; row: FeedRow } | { kind: 'change'; change: ModelChange };

/** Feed rows and model-change markers merged newest-first. */
export function feedItems(
  board: BoardState,
  agentFilter: string | null,
  limit: number = DEFAULT_FEED_LIMIT,
): FeedItem[] {
  const items: { at: string; rank: number; item: FeedItem }[] = feedRows(
    board,
    agentFilter,
    limit * 2,
  ).map((row) => ({ at: row.entry.startedAt, rank: 1, item: { kind: 'row', row } as FeedItem }));
  for (const change of modelChanges(board)) {
    if (!agentFilter || change.agentId === agentFilter) {
      items.push({ at: change.at, rank: 0, item: { kind: 'change', change } });
    }
  }
  return items
    .sort((a, b) => b.at.localeCompare(a.at) || a.rank - b.rank)
    .slice(0, limit)
    .map((entry) => entry.item);
}

export function stationCounts(board: BoardState, counters?: MapCounters | null): CountMap {
  const counts: CountMap = {};
  for (const entry of board.entries) {
    const current = counts[entry.station] ?? { total: 0, running: 0, faults: 0 };
    current.total += 1;
    if (entry.status === 'running') {
      current.running += 1;
    }
    if (entry.status === 'error' || entry.status === 'blocked') {
      current.faults += 1;
    }
    counts[entry.station] = current;
  }
  if (counters) {
    mergeCounters(counts, counters);
  }
  return counts;
}

function foldKey(entry: MapEntry): string {
  if (entry.type === 'tool') {
    return `${entry.station}|${entry.agentId ?? ''}|${entry.type}`;
  }
  return `${entry.station}|${entry.agentId ?? ''}|${entry.type}|${entry.label}`;
}

export function feedRows(
  board: BoardState,
  agentFilter: string | null,
  limit = DEFAULT_FEED_LIMIT,
): FeedRow[] {
  const sorted = board.entries
    .filter((e) => agentFilter === null || e.agentId === agentFilter)
    .slice()
    .sort((a, b) => Date.parse(b.startedAt) - Date.parse(a.startedAt));
  const rows: FeedRow[] = [];
  for (const entry of sorted) {
    const last = rows[rows.length - 1];
    if (
      last !== undefined &&
      entry.status !== 'running' &&
      last.entry.status !== 'running' &&
      foldKey(last.entry) === foldKey(entry)
    ) {
      rows[rows.length - 1] = { entry: last.entry, times: last.times + 1 };
    } else {
      rows.push({ entry, times: 1 });
    }
    if (rows.length >= limit) {
      break;
    }
  }
  return rows;
}

export function agentStates(board: BoardState): AgentState[] {
  const byAgent = new Map<string, AgentState>();
  for (const entry of board.entries) {
    if (entry.agentId === null || entry.type !== 'agent') {
      continue;
    }
    const current = byAgent.get(entry.agentId) ?? {
      agentId: entry.agentId,
      status: 'done' as const,
      lastLabel: entry.label,
      totalMs: 0,
      calls: 0,
    };
    current.calls += 1;
    current.totalMs += entry.durationMs ?? 0;
    current.lastLabel = entry.label;
    if (entry.status === 'running') {
      current.status = 'running';
    } else if (entry.status === 'error' || entry.status === 'blocked') {
      current.status = 'failed';
    }
    byAgent.set(entry.agentId, current);
  }
  return [...byAgent.values()];
}

export function childrenOf(board: BoardState, spanId: string): MapEntry[] {
  return board.entries.filter((e) => e.parentId === spanId);
}

export function budgetPercent(usedTokens: number, limitTokens: number | null): number | null {
  if (limitTokens === null || limitTokens <= 0) {
    return null;
  }
  return Math.min(PERCENT_WHOLE, Math.round((usedTokens / limitTokens) * PERCENT_WHOLE));
}

export function formatDuration(durationMs: number | null): string {
  if (durationMs === null) {
    return '';
  }
  if (durationMs < MS_PER_SECOND) {
    return `${durationMs}ms`;
  }
  return `${(durationMs / MS_PER_SECOND).toFixed(1)}s`;
}

export function statusSymbol(status: MapStatus): string {
  if (status === 'running') {
    return '●';
  }
  if (status === 'ok') {
    return '·';
  }
  return '✕';
}
