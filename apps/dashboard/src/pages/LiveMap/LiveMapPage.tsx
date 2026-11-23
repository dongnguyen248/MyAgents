import { Card, PageHeader } from '../../components/common/Layout';
import { MapCanvas } from '../../components/livemap/MapCanvas';
import { MapFeed } from '../../components/livemap/MapFeed';
import { AgentList, EntryDetail } from '../../components/livemap/MapSidePanel';
import { agentStates, budgetPercent, feedRows } from '../../lib/mapBoard';
import type { BoardState } from '../../lib/mapBoard';
import type { Workflow } from '../../types/workflow';
import { useLiveMapData, useMapSelection, useWorkflowRuns } from './useLiveMapData';
import type { LiveMapData, MapSelection } from './useLiveMapData';

const TOKENS_PER_K = 1000;
const RUN_ID_PREFIX = 8;

function compactTokens(tokens: number): string {
  if (tokens >= TOKENS_PER_K) {
    return `${(tokens / TOKENS_PER_K).toFixed(1)}k`;
  }
  return `${tokens}`;
}

function RunPicker({
  workflows,
  runId,
  onRunId,
}: {
  workflows: Workflow[];
  runId: string;
  onRunId: (id: string) => void;
}) {
  return (
    <label className="field inline">
      <span>Run</span>
      <select value={runId} onChange={(e) => onRunId(e.target.value)}>
        {workflows.length === 0 && <option value="">No runs</option>}
        {workflows.map((w) => (
          <option key={w.id} value={w.id}>
            {w.title} · {w.status} · {w.id.slice(0, RUN_ID_PREFIX)}
          </option>
        ))}
      </select>
    </label>
  );
}

function SideStack({ board, selection }: { board: BoardState; selection: MapSelection }) {
  return (
    <div className="stack">
      <Card title="Agents">
        <AgentList agents={agentStates(board)} onPick={selection.pickAgent} />
      </Card>
      <Card title="Detail">
        <EntryDetail board={board} entry={selection.selected} onSelect={selection.selectEntry} />
      </Card>
    </div>
  );
}

function FeedCard({ board, selection }: { board: BoardState; selection: MapSelection }) {
  return (
    <Card title="Feed">
      <MapFeed
        rows={feedRows(board, selection.filter)}
        agents={agentStates(board)}
        filter={selection.filter}
        selectedSpanId={selection.selected?.spanId ?? null}
        onFilter={selection.setFilter}
        onSelect={selection.selectEntry}
      />
    </Card>
  );
}

function MapLayout({ live, selection }: { live: LiveMapData; selection: MapSelection }) {
  const percent = budgetPercent(live.usedTokens, live.budget?.limitTokens ?? null);
  const budgetText = percent === null ? compactTokens(live.usedTokens) : `${percent}%`;
  return (
    <div className="grid lm-layout">
      <Card title="Map" flush>
        <MapCanvas
          board={live.board}
          pulses={live.pulses}
          budgetPercent={percent}
          budgetText={budgetText}
          runStatus={live.runStatus}
        />
      </Card>
      <SideStack board={live.board} selection={selection} />
      <FeedCard board={live.board} selection={selection} />
    </div>
  );
}

function MissedCard() {
  return (
    <Card title="Live map">
      <p className="muted">
        No live map for this run. The map needs the real backend started with ASF_LIVE_MAP enabled,
        and it only sees runs from the current backend session.
      </p>
    </Card>
  );
}

export function LiveMapPage() {
  const { workflows, runId, setRunId } = useWorkflowRuns();
  const live = useLiveMapData(runId);
  const selection = useMapSelection(live.board);
  const showMissed = live.missed && live.board.entries.length === 0;
  return (
    <>
      <PageHeader
        title="Live map"
        subtitle="What each agent is doing right now: pulses are metadata only - names, never content."
        actions={<RunPicker workflows={workflows} runId={runId} onRunId={setRunId} />}
      />
      {showMissed ? <MissedCard /> : <MapLayout live={live} selection={selection} />}
    </>
  );
}
