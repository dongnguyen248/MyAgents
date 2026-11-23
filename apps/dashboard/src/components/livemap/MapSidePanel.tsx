import { agentColor, childrenOf, formatDuration } from '../../lib/mapBoard';
import type { AgentState, BoardState, MapEntry } from '../../lib/mapBoard';
import type { MapHosting } from '../../types/map';

function agentStatusText(status: AgentState['status']): string {
  if (status === 'running') {
    return 'running';
  }
  if (status === 'failed') {
    return 'failed';
  }
  return 'done';
}

export function AgentList({
  agents,
  onPick,
}: {
  agents: AgentState[];
  onPick: (agentId: string) => void;
}) {
  if (agents.length === 0) {
    return <p className="muted">No agent has run yet.</p>;
  }
  return (
    <ul className="lm-agents">
      {agents.map((agent) => (
        <li key={agent.agentId}>
          <button type="button" className="lm-agent-row" onClick={() => onPick(agent.agentId)}>
            <span className="lm-dot" style={{ background: agentColor(agent.agentId) }} />
            <span className="lm-agent-name">{agent.agentId}</span>
            <span className={`lm-agent-status ${agent.status}`}>
              {agentStatusText(agent.status)}
            </span>
            <span className="lm-row-time">{formatDuration(agent.totalMs)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function DetailRow({ name, value }: { name: string; value: string }) {
  return (
    <div className="lm-detail-row">
      <dt>{name}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function ChildrenList({
  children,
  onSelect,
}: {
  children: MapEntry[];
  onSelect: (entry: MapEntry) => void;
}) {
  if (children.length === 0) {
    return null;
  }
  return (
    <div>
      <h3 className="lm-detail-sub">Calls under this span</h3>
      <ul className="lm-feed">
        {children.map((child) => (
          <li key={child.spanId}>
            <button type="button" className="lm-row" onClick={() => onSelect(child)}>
              <span className="lm-dot" style={{ background: agentColor(child.agentId) }} />
              <span className="lm-row-label">{child.label}</span>
              <span className="lm-row-time">{formatDuration(child.durationMs)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DetailRows({ entry }: { entry: MapEntry }) {
  const tokens = entry.promptTokens + entry.completionTokens;
  return (
    <dl className="lm-detail">
      <DetailRow name="Label" value={entry.label} />
      <DetailRow name="Type" value={entry.type} />
      <DetailRow name="Station" value={entry.station} />
      {entry.agentId && <DetailRow name="Agent" value={entry.agentId} />}
      {entry.stepId && <DetailRow name="Step" value={entry.stepId} />}
      <DetailRow name="Status" value={entry.status} />
      <DetailRow name="Started" value={entry.startedAt} />
      {entry.endedAt && <DetailRow name="Ended" value={entry.endedAt} />}
      {entry.durationMs !== null && (
        <DetailRow name="Duration" value={formatDuration(entry.durationMs)} />
      )}
      {entry.model && <DetailRow name="Model" value={entry.model} />}
      {tokens > 0 && (
        <DetailRow
          name="Tokens"
          value={`${tokens} (${entry.promptTokens} in / ${entry.completionTokens} out)`}
        />
      )}
      {entry.errorCode && <DetailRow name="Error" value={entry.errorCode} />}
    </dl>
  );
}

function HostingLink({ hosting }: { hosting: MapHosting | null }) {
  if (hosting === null) {
    return null;
  }
  return (
    <dl className="lm-detail">
      <div className="lm-detail-row">
        <dt>PR / MR</dt>
        <dd>
          <a href={hosting.url} target="_blank" rel="noreferrer">
            #{hosting.number}
          </a>
        </dd>
      </div>
    </dl>
  );
}

export function EntryDetail({
  board,
  entry,
  hosting,
  onSelect,
}: {
  board: BoardState;
  entry: MapEntry | null;
  hosting: MapHosting | null;
  onSelect: (entry: MapEntry) => void;
}) {
  if (entry === null) {
    return (
      <div>
        <HostingLink hosting={hosting} />
        <p className="muted">Select a feed row or an agent to see what it did.</p>
      </div>
    );
  }
  return (
    <div>
      <HostingLink hosting={hosting} />
      <DetailRows entry={entry} />
      <ChildrenList children={childrenOf(board, entry.spanId)} onSelect={onSelect} />
    </div>
  );
}
