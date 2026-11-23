import { Card } from '../../components/common/Layout';
import { MapCanvas } from '../../components/livemap/MapCanvas';
import { MapFeed } from '../../components/livemap/MapFeed';
import { AgentList, EntryDetail } from '../../components/livemap/MapSidePanel';
import { agentStates, budgetPercent, feedItems, formatDuration } from '../../lib/mapBoard';
import type { MapReplaySummary } from '../../types/map';
import { useMapSelection } from './useLiveMapData';
import type { MapSelection } from './useLiveMapData';
import { useReplayPlayer } from './useReplay';
import type { ReplayPlayer } from './useReplay';

const SPEED_NORMAL = 1;
const SPEED_DOUBLE = 2;
const SPEED_QUAD = 4;
const SPEEDS = [SPEED_NORMAL, SPEED_DOUBLE, SPEED_QUAD];
const RUN_ID_PREFIX = 8;

function ReplayBadges({ player }: { player: ReplayPlayer }) {
  const replay = player.replay;
  if (replay === null) {
    return null;
  }
  return (
    <>
      {!replay.complete && <span className="lm-badge warn">Chưa hoàn tất</span>}
      {replay.truncated && <span className="lm-badge warn">Replay bị cắt</span>}
    </>
  );
}

function RunSelect({ player }: { player: ReplayPlayer }) {
  return (
    <label className="field inline">
      <span>Run</span>
      <select value={player.runId} onChange={(e) => player.setRunId(e.target.value)}>
        {player.summaries.length === 0 && <option value="">No replays</option>}
        {player.summaries.map((item: MapReplaySummary) => (
          <option key={item.runId} value={item.runId}>
            {item.runId.slice(0, RUN_ID_PREFIX)} · {item.events} pulses
            {item.complete ? '' : ' · incomplete'}
          </option>
        ))}
      </select>
    </label>
  );
}

function SpeedSelect({ player }: { player: ReplayPlayer }) {
  return (
    <label className="field inline">
      <span>Speed</span>
      <select value={player.speed} onChange={(e) => player.setSpeed(Number(e.target.value))}>
        {SPEEDS.map((speed) => (
          <option key={speed} value={speed}>
            {speed}x
          </option>
        ))}
      </select>
    </label>
  );
}

function PositionSlider({ player }: { player: ReplayPlayer }) {
  return (
    <>
      <input
        type="range"
        min={0}
        max={player.durationMs}
        step={100}
        value={player.cursorMs}
        onChange={(e) => player.seek(Number(e.target.value))}
        aria-label="Replay position"
      />
      <span className="lm-row-time">
        {formatDuration(player.cursorMs)} / {formatDuration(player.durationMs)}
      </span>
    </>
  );
}

function Transport({ player }: { player: ReplayPlayer }) {
  return (
    <div className="lm-transport">
      <button type="button" onClick={player.toggle}>
        {player.playing ? 'Pause' : 'Play'}
      </button>
      <SpeedSelect player={player} />
      <PositionSlider player={player} />
      <ReplayBadges player={player} />
    </div>
  );
}

function ReplaySideStack({ player, selection }: { player: ReplayPlayer; selection: MapSelection }) {
  return (
    <div className="stack">
      <Card title="Agents">
        <AgentList agents={agentStates(player.board)} onPick={selection.pickAgent} />
      </Card>
      <Card title="Detail">
        <EntryDetail
          board={player.board}
          entry={selection.selected}
          hosting={null}
          onSelect={selection.selectEntry}
        />
      </Card>
    </div>
  );
}

function ReplayFeed({ player, selection }: { player: ReplayPlayer; selection: MapSelection }) {
  return (
    <Card title="Feed">
      <MapFeed
        items={feedItems(player.board, selection.filter)}
        agents={agentStates(player.board)}
        filter={selection.filter}
        selectedSpanId={selection.selected?.spanId ?? null}
        onFilter={selection.setFilter}
        onSelect={selection.selectEntry}
      />
    </Card>
  );
}

function ReplayLayout({ player }: { player: ReplayPlayer }) {
  const selection = useMapSelection(player.board);
  const budget = player.replay?.budget ?? null;
  const used = budget?.usedTokens ?? 0;
  const percent = budgetPercent(used, budget?.limitTokens ?? null);
  return (
    <div className="grid lm-layout">
      <Card title="Map" flush>
        <MapCanvas
          board={player.board}
          counters={player.replay?.counters ?? null}
          pulses={player.pulses}
          budgetPercent={percent}
          budgetText={percent === null ? `${used}` : `${percent}%`}
          runStatus="REPLAY"
        />
      </Card>
      <ReplaySideStack player={player} selection={selection} />
      <ReplayFeed player={player} selection={selection} />
    </div>
  );
}

export function ReplaySection() {
  const player = useReplayPlayer();
  if (player.summaries.length === 0) {
    return (
      <Card title="Replay">
        <p className="muted">
          No stored replays yet. Finished runs are recorded next to the run database when the live
          map is enabled.
        </p>
      </Card>
    );
  }
  return (
    <>
      <Card title="Replay">
        <div className="lm-replay-bar">
          <RunSelect player={player} />
          <Transport player={player} />
        </div>
      </Card>
      <ReplayLayout player={player} />
    </>
  );
}
