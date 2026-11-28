import { useParams } from 'react-router-dom';
import { AgentProfilePicker } from '../../components/agents/AgentProfilePicker';
import { AgentSkillPicker } from '../../components/agents/AgentSkillPicker';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { useAsync } from '../../hooks/useAsync';
import { api } from '../../services/api';
import type { Agent } from '../../types/agent';

function SettingsCards({ agent }: { agent: Agent }) {
  return <div className="grid two-col"><Card title="LLM settings"><AgentProfilePicker agent={agent} /></Card><Card title="Skills"><AgentSkillPicker agent={agent} /></Card></div>;
}

export function AgentSettingsPage() {
  const { agentId = '' } = useParams();
  const agent = useAsync(() => api.getAgent(agentId), [agentId]);
  return <><PageHeader title="Agent configuration" back={{ to: `/agents/${agentId}`, label: 'Agent runtime view' }} subtitle="Configure the model connection and skills used by this agent." />
    <AsyncView {...agent}>{(value) => <SettingsCards agent={value} />}</AsyncView>
  </>;
}
