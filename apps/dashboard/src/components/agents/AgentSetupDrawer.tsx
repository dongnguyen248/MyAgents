import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAgentConfig } from '../../features/agent-management';
import { useEscape } from '../../hooks/useEscape';
import { agentMeta } from '../../lib/agentCatalog';
import type { Agent, AgentConfig } from '../../types/agent';
import { AsyncView } from '../common/AsyncView';
import { Badge } from '../common/Badge';
import { Icon } from '../common/Icon';
import { AgentCapabilityList } from './AgentCapabilityList';
import { AgentSetupConfig } from './AgentSetupConfig';
import { AgentSkillPicker } from './AgentSkillPicker';
import { AgentRulePicker } from './AgentRulePicker';

type TabId = 'config' | 'skills' | 'rules' | 'tools';

const TABS: { id: TabId; label: string }[] = [
  { id: 'config', label: 'Config & prompt' },
  { id: 'skills', label: 'Skills' },
  { id: 'rules', label: 'Rules' },
  { id: 'tools', label: 'Tools' },
];

function DrawerBackdrop({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      className="drawer-backdrop"
      aria-label="Close agent setup"
      onClick={onClose}
    />
  );
}

function DrawerHead({ agent }: { agent: Agent }) {
  return (
    <div className="drawer-head">
      <h2 className="drawer-title">
        {agent.name}
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
      </h2>
      <p className="drawer-desc">{agentMeta(agent.type).description}</p>
    </div>
  );
}

function DrawerTabs({ tab, onSelect }: { tab: TabId; onSelect: (tab: TabId) => void }) {
  return (
    <div className="tabs" role="tablist" aria-label="Agent setup sections">
      {TABS.map((entry) => (
        <button
          key={entry.id}
          type="button"
          role="tab"
          className="tab"
          aria-selected={tab === entry.id}
          onClick={() => onSelect(entry.id)}
        >
          {entry.label}
        </button>
      ))}
    </div>
  );
}

function DrawerBody({ agent, tab, config }: { agent: Agent; tab: TabId; config: AgentConfig }) {
  if (tab === 'config') {
    return <AgentSetupConfig agent={agent} config={config} />;
  }
  if (tab === 'skills') {
    return <AgentSkillPicker agent={agent} />;
  }
  if (tab === 'rules') {
    return <AgentRulePicker agent={agent} />;
  }
  return <AgentCapabilityList kind="tools" items={config.tools} />;
}

function DrawerFoot({ agentId, onClose }: { agentId: string; onClose: () => void }) {
  return (
    <div className="drawer-foot">
      <Link className="btn" to={`/agents/${agentId}`} onClick={onClose}>
        <Icon name="external" className="icon-sm" />
        Runtime view
      </Link>
      <Link className="btn" to={`/agents/${agentId}/settings`} onClick={onClose}>
        <Icon name="sliders" className="icon-sm" />
        Full settings
      </Link>
      <span className="spacer" />
      <button type="button" className="btn btn-ghost" onClick={onClose}>
        Close
      </button>
    </div>
  );
}

/**
 * Agent setup, as a right-hand drawer over the catalogue: config & prompt,
 * then the skills and tools the backend reports for the agent.
 */
export function AgentSetupDrawer({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const [tab, setTab] = useState<TabId>('config');
  const config = useAgentConfig(agent.id);

  useEscape(onClose);

  return (
    <>
      <DrawerBackdrop onClose={onClose} />
      <div className="drawer" role="dialog" aria-modal="true" aria-label={`${agent.name} setup`}>
        <DrawerHead agent={agent} />
        <DrawerTabs tab={tab} onSelect={setTab} />
        <div className="drawer-body">
          <AsyncView {...config}>
            {(value) => <DrawerBody agent={agent} tab={tab} config={value} />}
          </AsyncView>
        </div>
        <DrawerFoot agentId={agent.id} onClose={onClose} />
      </div>
    </>
  );
}
