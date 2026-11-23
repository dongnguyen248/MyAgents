import { agentColor, formatDuration, statusSymbol } from '../../lib/mapBoard';
import type { AgentState, FeedRow, MapEntry } from '../../lib/mapBoard';

function AgentChip({
  agentId,
  active,
  onPick,
}: {
  agentId: string | null;
  active: boolean;
  onPick: () => void;
}) {
  return (
    <button type="button" className={active ? 'lm-chip active' : 'lm-chip'} onClick={onPick}>
      {agentId !== null && <span className="lm-dot" style={{ background: agentColor(agentId) }} />}
      {agentId ?? 'All agents'}
    </button>
  );
}

function AgentChips({
  agents,
  filter,
  onFilter,
}: {
  agents: AgentState[];
  filter: string | null;
  onFilter: (agentId: string | null) => void;
}) {
  return (
    <div className="lm-chips" role="group" aria-label="Filter by agent">
      <AgentChip agentId={null} active={filter === null} onPick={() => onFilter(null)} />
      {agents.map((agent) => (
        <AgentChip
          key={agent.agentId}
          agentId={agent.agentId}
          active={filter === agent.agentId}
          onPick={() => onFilter(filter === agent.agentId ? null : agent.agentId)}
        />
      ))}
    </div>
  );
}

function FeedRowItem({
  row,
  selectedSpanId,
  onSelect,
}: {
  row: FeedRow;
  selectedSpanId: string | null;
  onSelect: (entry: MapEntry) => void;
}) {
  const entry = row.entry;
  return (
    <li>
      <button
        type="button"
        className={entry.spanId === selectedSpanId ? 'lm-row selected' : 'lm-row'}
        onClick={() => onSelect(entry)}
      >
        <span className={`lm-symbol ${entry.status}`}>{statusSymbol(entry.status)}</span>
        <span className="lm-dot" style={{ background: agentColor(entry.agentId) }} />
        <span className="lm-row-label">{entry.label}</span>
        {row.times > 1 && <span className="lm-fold">×{row.times}</span>}
        {entry.agentId && <span className="lm-row-agent">{entry.agentId}</span>}
        <span className="lm-row-time">{formatDuration(entry.durationMs)}</span>
      </button>
    </li>
  );
}

function FeedList({
  rows,
  selectedSpanId,
  onSelect,
}: {
  rows: FeedRow[];
  selectedSpanId: string | null;
  onSelect: (entry: MapEntry) => void;
}) {
  if (rows.length === 0) {
    return <p className="muted">No pulses yet for this run.</p>;
  }
  return (
    <ul className="lm-feed">
      {rows.map((row) => (
        <FeedRowItem
          key={row.entry.spanId}
          row={row}
          selectedSpanId={selectedSpanId}
          onSelect={onSelect}
        />
      ))}
    </ul>
  );
}

export function MapFeed({
  rows,
  agents,
  filter,
  selectedSpanId,
  onFilter,
  onSelect,
}: {
  rows: FeedRow[];
  agents: AgentState[];
  filter: string | null;
  selectedSpanId: string | null;
  onFilter: (agentId: string | null) => void;
  onSelect: (entry: MapEntry) => void;
}) {
  return (
    <div>
      <AgentChips agents={agents} filter={filter} onFilter={onFilter} />
      <FeedList rows={rows} selectedSpanId={selectedSpanId} onSelect={onSelect} />
    </div>
  );
}
