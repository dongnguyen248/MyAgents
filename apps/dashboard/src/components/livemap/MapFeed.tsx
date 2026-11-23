import { agentColor, formatDuration, statusSymbol } from '../../lib/mapBoard';
import type { AgentState, FeedItem, FeedRow, MapEntry, ModelChange } from '../../lib/mapBoard';

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
        {row.times > 1 && <span className="lm-fold">+{row.times - 1}</span>}
        {entry.agentId && <span className="lm-row-agent">{entry.agentId}</span>}
        <span className="lm-row-time">{formatDuration(entry.durationMs)}</span>
      </button>
    </li>
  );
}

function ChangeRowItem({ change }: { change: ModelChange }) {
  return (
    <li>
      <div className="lm-row lm-change">
        <span className="lm-symbol change">◆</span>
        <span className="lm-dot" style={{ background: agentColor(change.agentId) }} />
        <span className="lm-row-label">
          {change.fromModel} → {change.toModel}
        </span>
        <span className="lm-row-agent">model</span>
      </div>
    </li>
  );
}

function FeedList({
  items,
  selectedSpanId,
  onSelect,
}: {
  items: FeedItem[];
  selectedSpanId: string | null;
  onSelect: (entry: MapEntry) => void;
}) {
  if (items.length === 0) {
    return <p className="muted">No pulses yet for this run.</p>;
  }
  return (
    <ul className="lm-feed">
      {items.map((item) =>
        item.kind === 'change' ? (
          <ChangeRowItem key={item.change.key} change={item.change} />
        ) : (
          <FeedRowItem
            key={item.row.entry.spanId}
            row={item.row}
            selectedSpanId={selectedSpanId}
            onSelect={onSelect}
          />
        ),
      )}
    </ul>
  );
}

export function MapFeed({
  items,
  agents,
  filter,
  selectedSpanId,
  onFilter,
  onSelect,
}: {
  items: FeedItem[];
  agents: AgentState[];
  filter: string | null;
  selectedSpanId: string | null;
  onFilter: (agentId: string | null) => void;
  onSelect: (entry: MapEntry) => void;
}) {
  return (
    <div>
      <AgentChips agents={agents} filter={filter} onFilter={onFilter} />
      <FeedList items={items} selectedSpanId={selectedSpanId} onSelect={onSelect} />
    </div>
  );
}
