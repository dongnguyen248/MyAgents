import { useState } from 'react';
import { Link } from 'react-router-dom';
import { AgentGridCard } from '../../components/agents/AgentGridCard';
import { AgentSetupDrawer } from '../../components/agents/AgentSetupDrawer';
import { AgentTable } from '../../components/agents/AgentTable';
import { AsyncView } from '../../components/common/AsyncView';
import { Icon } from '../../components/common/Icon';
import { Card, PageHeader } from '../../components/common/Layout';
import { useAgentConfigs, useAgents } from '../../features/agent-management';
import type { Agent, AgentConfig } from '../../types/agent';

type AgentView = 'cards' | 'table';

function toolCountOf(configs: (AgentConfig | undefined)[] | undefined, agentId: string) {
  return configs?.find((config) => config?.agentId === agentId)?.tools.length;
}

/** Cards (the default) or the dense monitoring table, for the same list. */
function AgentList({
  agents,
  view,
  onOpen,
}: {
  agents: Agent[];
  view: AgentView;
  onOpen: (agentId: string) => void;
}) {
  const configs = useAgentConfigs(agents.map((agent) => agent.id));
  if (view === 'table') {
    return <AgentTable agents={agents} />;
  }
  return (
    <div className="agent-grid">
      {agents.map((agent) => (
        <AgentGridCard
          key={agent.id}
          agent={agent}
          toolCount={toolCountOf(configs.data, agent.id)}
          onOpen={() => onOpen(agent.id)}
        />
      ))}
    </div>
  );
}

function ViewToggle({ view, onChange }: { view: AgentView; onChange: (view: AgentView) => void }) {
  return (
    <div className="segmented" role="group" aria-label="Agent list view">
      <button type="button" aria-pressed={view === 'cards'} onClick={() => onChange('cards')}>
        Cards
      </button>
      <button type="button" aria-pressed={view === 'table'} onClick={() => onChange('table')}>
        Table
      </button>
    </div>
  );
}

function AgentCatalogue({
  agents,
  view,
  selectedId,
  onSelect,
}: {
  agents: Agent[];
  view: AgentView;
  selectedId: string | null;
  onSelect: (agentId: string | null) => void;
}) {
  const selected = agents.find((agent) => agent.id === selectedId);
  return (
    <>
      <AgentList agents={agents} view={view} onOpen={onSelect} />
      {selected && <AgentSetupDrawer agent={selected} onClose={() => onSelect(null)} />}
    </>
  );
}

function AgentsHeader() {
  return (
    <PageHeader
      title="Agent"
      subtitle="Prompts and configs for the platform’s built-in agents, plus their runtime status."
      actions={
        <Link className="btn btn-primary" to="/agent-settings">
          <Icon name="plus" className="icon-sm" />
          Create agent
        </Link>
      }
    />
  );
}

export function AgentsPage() {
  const agents = useAgents();
  const [view, setView] = useState<AgentView>('cards');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const total = agents.data ? `${agents.data.length} total` : undefined;

  return (
    <>
      <AgentsHeader />
      <Card
        title="Agent list"
        subtitle={total}
        actions={<ViewToggle view={view} onChange={setView} />}
      >
        <AsyncView {...agents}>
          {(list) => (
            <AgentCatalogue
              agents={list}
              view={view}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </AsyncView>
      </Card>
    </>
  );
}
