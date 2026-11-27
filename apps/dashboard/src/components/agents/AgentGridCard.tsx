import { agentMeta } from '../../lib/agentCatalog';
import type { Agent } from '../../types/agent';
import { Badge } from '../common/Badge';
import { Icon } from '../common/Icon';

function AgentCardHeading({ agent }: { agent: Agent }) {
  return (
    <span className="agent-card-top">
      <Icon name="bot" className="icon-sm" />
      <span className="agent-card-name">{agent.name}</span>
      <span className="agent-card-key">{agent.id}</span>
      {agent.custom ? (
        <Badge tone="info" icon="◇" small>
          Custom
        </Badge>
      ) : (
        <Badge tone="muted" icon="◆" small>
          Built-in
        </Badge>
      )}
      {agent.status === 'DISABLED' && (
        <Badge tone="danger" icon="✕" small>
          Disabled
        </Badge>
      )}
    </span>
  );
}

/**
 * One catalogue tile. Everything actionable lives in the setup drawer, so the
 * whole card is the button; the chips summarise what the agent is bound to.
 */
export function AgentGridCard({
  agent,
  toolCount,
  onOpen,
}: {
  agent: Agent;
  toolCount?: number;
  onOpen: () => void;
}) {
  return (
    <button type="button" className="agent-card" onClick={onOpen}>
      <AgentCardHeading agent={agent} />
      <span className="agent-card-desc">{agentMeta(agent.type).description}</span>
      <span className="agent-card-chips">
        <span className="chip">Skill {agent.skills?.length ?? 0}</span>
        <span className="chip">Tools {toolCount ?? '–'}</span>
        <span className="chip">Runs {agent.metrics.total}</span>
      </span>
    </button>
  );
}
