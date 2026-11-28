import { useState } from 'react';
import { AgentGridCard } from '../../components/agents/AgentGridCard';
import { CreateAgentDialog } from '../../components/agents/CreateAgentDialog';
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

/** What the catalogue needs besides the agents themselves. */
interface Catalogue {
  view: AgentView;
  selectedId: string | null;
  onSelect: (agentId: string | null) => void;
}

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
    return <AgentTable agents={agents} onOpen={onOpen} />;
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

function AgentCatalogue({ agents, catalogue }: { agents: Agent[]; catalogue: Catalogue }) {
  const { view, selectedId, onSelect } = catalogue;
  const selected = agents.find((agent) => agent.id === selectedId);
  return (
    <>
      <AgentList agents={agents} view={view} onOpen={onSelect} />
      {selected && <AgentSetupDrawer agent={selected} onClose={() => onSelect(null)} />}
    </>
  );
}

function AgentsHeader({ onCreate }: { onCreate: () => void }) {
  return (
    <PageHeader
      title="Agent"
      subtitle="Prompts and configs for the platform’s built-in agents, plus creating and managing custom agents."
      actions={
        <button type="button" className="btn btn-primary" onClick={onCreate}>
          <Icon name="plus" className="icon-sm" />
          Create agent
        </button>
      }
    />
  );
}

function AgentListCard({
  agents,
  catalogue,
  setView,
}: {
  agents: ReturnType<typeof useAgents>;
  catalogue: Catalogue;
  setView: (view: AgentView) => void;
}) {
  return (
    <Card
      title="Agent list"
      subtitle={agents.data ? `${agents.data.length} total` : undefined}
      actions={<ViewToggle view={catalogue.view} onChange={setView} />}
    >
      <AsyncView {...agents}>
        {(list) => <AgentCatalogue agents={list} catalogue={catalogue} />}
      </AsyncView>
    </Card>
  );
}

function CreateDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  return <CreateAgentDialog onClose={onClose} onCreated={onCreated} />;
}

function useSelectedAgent(reload: () => void) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  function selectAgent(id: string | null) {
    setSelectedId(id);
    if (!id) {
      reload();
    }
  }
  return { selectedId, selectAgent };
}

export function AgentsPage() {
  const agents = useAgents();
  const [view, setView] = useState<AgentView>('cards');
  const { selectedId, selectAgent } = useSelectedAgent(agents.reload);
  const [creating, setCreating] = useState(false);

  return (
    <>
      <AgentsHeader onCreate={() => setCreating(true)} />
      <AgentListCard
        agents={agents}
        setView={setView}
        catalogue={{ view, selectedId, onSelect: selectAgent }}
      />
      {creating && (
        <CreateDialog
          onClose={() => setCreating(false)}
          onCreated={() => {
            agents.reload();
            setView('cards');
          }}
        />
      )}
    </>
  );
}
