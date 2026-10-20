import { useState } from 'react';
import { ActivityFeed } from '../../components/activity/ActivityFeed';
import { Card, PageHeader } from '../../components/common/Layout';
import { useAgents } from '../../features/agent-management';
import { useActivityFeed } from '../../features/activity-feed';

export function ActivityPage() {
  const [live, setLive] = useState(true);
  const [agentId, setAgentId] = useState('');
  const agents = useAgents();
  const { events, loading } = useActivityFeed({ agentId: agentId || undefined }, live);

  return (
    <>
      <PageHeader
        title="Live activity"
        subtitle="Real-time stream of agent, orchestrator and integration events."
        actions={
          <>
            <label className="field inline">
              <span>Agent</span>
              <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                <option value="">All</option>
                {(agents.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </label>
            <button type="button" className="btn" onClick={() => setLive((l) => !l)} aria-pressed={live}>{live ? '❚❚ Pause' : '▶ Resume'}</button>
          </>
        }
      />
      <Card title={live ? '● LIVE (simulated)' : 'Paused'}>
        {loading ? <p className="muted" role="status">Loading…</p> : <ActivityFeed events={events} />}
      </Card>
    </>
  );
}
