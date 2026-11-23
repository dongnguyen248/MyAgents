import { useCallback, useEffect, useMemo, useState } from 'react';
import { agentColor, replayBoard, replayDurationMs } from '../../lib/mapBoard';
import type { BoardState } from '../../lib/mapBoard';
import type { MapPulse } from '../../components/livemap/MapCanvas';
import { api } from '../../services/api';
import type { MapEvent, MapReplay, MapReplaySummary } from '../../types/map';

const TICK_MS = 100;
const PULSE_TTL_MS = 800;
const MAX_PULSES = 24;
const FAILED_COLOR = '#e0524d';

export interface ReplayPlayer {
  summaries: MapReplaySummary[];
  runId: string;
  setRunId: (id: string) => void;
  replay: MapReplay | null;
  board: BoardState;
  cursorMs: number;
  durationMs: number;
  playing: boolean;
  speed: number;
  setSpeed: (speed: number) => void;
  toggle: () => void;
  seek: (ms: number) => void;
  pulses: MapPulse[];
}

interface PlayerState {
  key: string;
  cursorMs: number;
  playing: boolean;
  speed: number;
  pulses: MapPulse[];
}

const IDLE_STATE: PlayerState = { key: '', cursorMs: 0, playing: false, speed: 1, pulses: [] };

function useReplayList() {
  const [summaries, setSummaries] = useState<MapReplaySummary[]>([]);
  const [runId, setRunId] = useState('');
  useEffect(() => {
    let cancelled = false;
    api.getMapReplays().then((items) => {
      if (!cancelled) {
        setSummaries(items);
        setRunId((current) => current || (items[0]?.runId ?? ''));
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return { summaries, runId, setRunId };
}

function useReplayData(runId: string): MapReplay | null {
  const [loaded, setLoaded] = useState<{ forRun: string; replay: MapReplay | null }>({
    forRun: '',
    replay: null,
  });
  useEffect(() => {
    if (!runId) {
      return undefined;
    }
    let cancelled = false;
    api.getMapReplay(runId).then((payload) => {
      if (!cancelled) {
        setLoaded({ forRun: runId, replay: payload ?? null });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [runId]);
  return loaded.forRun === runId ? loaded.replay : null;
}

function pulseFor(event: MapEvent): MapPulse | null {
  if (event.station === 'core') {
    return null;
  }
  const failed = event.status === 'error' || event.status === 'blocked';
  return {
    key: `${event.id}:${event.phase}`,
    station: event.station,
    color: failed ? FAILED_COLOR : agentColor(event.agentId ?? null),
    inbound: event.phase === 'end',
  };
}

function crossedPulses(events: MapEvent[], fromMs: number, toMs: number): MapPulse[] {
  if (events.length === 0) {
    return [];
  }
  const start = Date.parse(events[0].ts);
  const pulses: MapPulse[] = [];
  for (const event of events) {
    const offset = Date.parse(event.ts) - start;
    const pulse = offset > fromMs && offset <= toMs ? pulseFor(event) : null;
    if (pulse !== null) {
      pulses.push(pulse);
    }
  }
  return pulses;
}

type Patch = (part: Partial<PlayerState>) => void;

interface TickArgs {
  state: PlayerState;
  events: MapEvent[];
  durationMs: number;
  patch: Patch;
  expirePulse: (key: string) => void;
}

function usePlayerTick({ state, events, durationMs, patch, expirePulse }: TickArgs) {
  useEffect(() => {
    if (!state.playing) {
      return undefined;
    }
    const timer = setInterval(() => {
      const next = Math.min(durationMs, state.cursorMs + TICK_MS * state.speed);
      const fresh = crossedPulses(events, state.cursorMs, next);
      patch({ cursorMs: next, playing: next < durationMs, pulses: [...state.pulses, ...fresh] });
      for (const pulse of fresh) {
        setTimeout(() => expirePulse(pulse.key), PULSE_TTL_MS);
      }
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [state, durationMs, events, patch, expirePulse]);
}

function usePlayerControls(state: PlayerState, durationMs: number, patch: Patch) {
  const toggle = useCallback(() => {
    if (!state.playing && state.cursorMs >= durationMs) {
      patch({ cursorMs: 0, playing: true, pulses: [] });
    } else {
      patch({ playing: !state.playing });
    }
  }, [state, durationMs, patch]);
  const seek = useCallback(
    (ms: number) => {
      patch({ cursorMs: ms, pulses: [] });
    },
    [patch],
  );
  return { toggle, seek };
}

function usePlayerState(runId: string) {
  const [raw, setRaw] = useState<PlayerState>(IDLE_STATE);
  const state = raw.key === runId ? raw : IDLE_STATE;
  const patch = useCallback<Patch>(
    (part) => {
      setRaw((current) => {
        const base = current.key === runId ? current : IDLE_STATE;
        return { ...base, ...part, key: runId };
      });
    },
    [runId],
  );
  const expirePulse = useCallback((key: string) => {
    setRaw((current) => ({ ...current, pulses: current.pulses.filter((p) => p.key !== key) }));
  }, []);
  return { state, patch, expirePulse };
}

export function useReplayPlayer(): ReplayPlayer {
  const { summaries, runId, setRunId } = useReplayList();
  const replay = useReplayData(runId);
  const { state, patch, expirePulse } = usePlayerState(runId);
  const events = useMemo(() => replay?.events ?? [], [replay]);
  const durationMs = useMemo(() => replayDurationMs(events), [events]);
  usePlayerTick({ state, events, durationMs, patch, expirePulse });
  const { toggle, seek } = usePlayerControls(state, durationMs, patch);

  const board = useMemo(() => replayBoard(events, state.cursorMs), [events, state.cursorMs]);
  return {
    summaries,
    runId,
    setRunId,
    replay,
    board,
    cursorMs: state.cursorMs,
    durationMs,
    playing: state.playing,
    speed: state.speed,
    setSpeed: (speed: number) => patch({ speed }),
    toggle,
    seek,
    pulses: state.pulses.slice(-MAX_PULSES),
  };
}
