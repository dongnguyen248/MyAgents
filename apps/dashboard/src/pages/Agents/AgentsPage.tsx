import { AgentTable } from '../../components/agents/AgentTable';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { useAgents } from '../../features/agent-management';

export function AgentsPage() {
  const agents = useAgents();
  return (
    <>
      <PageHeader title="Agents" subtitle="Runtime status and performance of every agent." />
      <Card flush>
        <AsyncView {...agents}>{(list) => <AgentTable agents={list} />}</AsyncView>
      </Card>
    </>
  );
}
