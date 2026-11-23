import { useCallback, useEffect, useRef, useState } from 'react';
import { agentColor, applyMapEvent, emptyBoard } from '../../lib/mapBoard';
import type { BoardState, MapEntry } from '../../lib/mapBoard';
import type { MapPulse } from '../../components/livemap/MapCanvas';
import { api } from '../../services/api';
import type { MapBudget, MapEvent, MapSnapshot } from '../../types/map';
import type { Workflow } from '../../types/workflow';

const PULSE_FRESH_MS = 4000;
const PULSE_TTL_MS = 800;
const MAX_PULSES = 24;
const SNAPSHOT_REFRESH_MS = 5000;
const FAILED_COLOR = '#e0524d';

interface MapViewState {
  forRun: string;
  board: BoardState;
  budget: MapBudget | null;
  status: string;
  missed: boolean;
}

export interface LiveMapData {
  board: BoardState;
  budget: MapBudget | null;
  runStatus: string;
  missed: boolean;
  pulses: MapPulse[];
  usedTokens: number;
}

function emptyView(runId: string): MapViewState {
  return { forRun: runId, board: emptyBoard(), budget: null, status: '', missed: false };
}

function usedTokensOf(board: BoardState): number {
  let total = 0;
  for (const entry of board.entries) {
    if (entry.type === 'model' && entry.endedAt !== null) {
      total += entry.promptTokens + entry.completionTokens;
    }
  }
  return total;
}

function useMapPulses(): { pulses: MapPulse[]; spawnPulse: (event: MapEvent) => void } {
  const [pulses, setPulses] = useState<MapPulse[]>([]);
  const spawnPulse = useCallback((event: MapEvent) => {
    if (event.station === 'core') {
      return;
    }
    if (Date.now() - Date.parse(event.ts) >= PULSE_FRESH_MS) {
      return;
    }
    const failed = event.status === 'error' || event.status === 'blocked';
    const pulse: MapPulse = {
      key: `${event.id}:${event.phase}`,
      station: event.station,
      color: failed ? FAILED_COLOR : agentColor(event.agentId ?? null),
      inbound: event.phase === 'end',
    };
    setPulses((current) => [...current.slice(-MAX_PULSES), pulse]);
    setTimeout(() => {
      setPulses((current) => current.filter((p) => p.key !== pulse.key));
    }, PULSE_TTL_MS);
  }, []);
  return { pulses, spawnPulse };
}

function deliverSnapshot(
  snapshot: MapSnapshot | undefined,
  applySnapshot: (snapshot: MapSnapshot | undefined) => void,
  onEvent: (event: MapEvent) => void,
): void {
  applySnapshot(snapshot);
  if (snapshot !== undefined) {
    for (const event of snapshot.events) {
      onEvent(event);
    }
  }
}

function useSnapshotLoader(
  runId: string,
  onEvent: (event: MapEvent) => void,
  applySnapshot: (snapshot: MapSnapshot | undefined) => void,
): void {
  useEffect(() => {
    if (!runId) {
      return undefined;
    }
    let cancelled = false;
    const loadSnapshot = () => {
      api.getMapSnapshot(runId).then((snapshot) => {
        if (!cancelled) {
          deliverSnapshot(snapshot, applySnapshot, onEvent);
        }
      });
    };
    loadSnapshot();
    const timer = setInterval(loadSnapshot, SNAPSHOT_REFRESH_MS);
    const unsubscribe = api.subscribeMapEvents(runId, onEvent);
    return () => {
      cancelled = true;
      clearInterval(timer);
      unsubscribe();
    };
  }, [runId, onEvent, applySnapshot]);
}

type SetView = (update: (current: MapViewState) => MapViewState) => void;
type AppliedRef = { current: { runId: string; ids: Set<string> } };

function makeEventHandler(
  appliedRef: AppliedRef,
  setView: SetView,
  spawnPulse: (event: MapEvent) => void,
): (event: MapEvent) => void {
  return (event: MapEvent) => {
    if (appliedRef.current.runId !== event.runId) {
      appliedRef.current = { runId: event.runId, ids: new Set() };
    }
    if (appliedRef.current.ids.has(event.id)) {
      return;
    }
    appliedRef.current.ids.add(event.id);
    setView((current) => {
      const base = current.forRun === event.runId ? current : emptyView(event.runId);
      return { ...base, board: applyMapEvent(base.board, event) };
    });
    spawnPulse(event);
  };
}

function makeSnapshotApplier(
  setView: SetView,
  runId: string,
): (snapshot: MapSnapshot | undefined) => void {
  return (snapshot: MapSnapshot | undefined) => {
    setView((current) => {
      const base = current.forRun === runId ? current : emptyView(runId);
      if (snapshot === undefined) {
        return { ...base, missed: true };
      }
      return { ...base, budget: snapshot.budget, status: snapshot.status };
    });
  };
}

export function useLiveMapData(runId: string): LiveMapData {
  const [view, setView] = useState<MapViewState>(() => emptyView(''));
  const { pulses, spawnPulse } = useMapPulses();
  const appliedRef = useRef<{ runId: string; ids: Set<string> }>({ runId: '', ids: new Set() });
  const handleEvent = useCallback(
    (event: MapEvent) => {
      makeEventHandler(appliedRef, setView, spawnPulse)(event);
    },
    [spawnPulse],
  );
  const applySnapshot = useCallback(
    (snapshot: MapSnapshot | undefined) => {
      makeSnapshotApplier(setView, runId)(snapshot);
    },
    [runId],
  );
  useSnapshotLoader(runId, handleEvent, applySnapshot);

  const current = view.forRun === runId ? view : emptyView(runId);
  return {
    board: current.board,
    budget: current.budget,
    runStatus: current.status,
    missed: current.missed,
    pulses,
    usedTokens: usedTokensOf(current.board),
  };
}

export function useWorkflowRuns(): {
  workflows: Workflow[];
  runId: string;
  setRunId: (id: string) => void;
} {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [runId, setRunId] = useState('');
  useEffect(() => {
    let cancelled = false;
    api.listWorkflows().then((list) => {
      if (cancelled) {
        return;
      }
      setWorkflows(list);
      setRunId((current) => {
        if (current) {
          return current;
        }
        const running = list.find((w) => w.status === 'RUNNING');
        return (running ?? list[0])?.id ?? '';
      });
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return { workflows, runId, setRunId };
}

export interface MapSelection {
  filter: string | null;
  setFilter: (agentId: string | null) => void;
  selected: MapEntry | null;
  selectEntry: (entry: MapEntry) => void;
  pickAgent: (agentId: string) => void;
}

export function useMapSelection(board: BoardState): MapSelection {
  const [filter, setFilter] = useState<string | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const selected = board.entries.find((e) => e.spanId === selectedSpanId) ?? null;
  const selectEntry = useCallback((entry: MapEntry) => {
    setSelectedSpanId(entry.spanId);
  }, []);
  const pickAgent = useCallback(
    (agentId: string) => {
      setFilter(agentId);
      const own = board.entries.filter((e) => e.agentId === agentId);
      const latest = own[own.length - 1];
      if (latest) {
        setSelectedSpanId(latest.spanId);
      }
    },
    [board],
  );
  return { filter, setFilter, selected, selectEntry, pickAgent };
}
