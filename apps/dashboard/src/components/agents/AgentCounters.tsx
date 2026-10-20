import type { AgentMetrics } from '../../types/metrics';
import { duration, pct } from '../../utils/format';
import { Stat } from '../common/Layout';

export function AgentCounters({ m }: { m: AgentMetrics }) {
  return (
    <dl className="stats">
      <Stat label="Total tasks" value={m.total} />
      <Stat label="Completed" value={m.completed} />
      <Stat label="Running" value={m.running} />
      <Stat label="Failed" value={m.failed} />
      <Stat label="Cancelled" value={m.cancelled} />
      <Stat label="Success rate" value={pct(m.successRate)} />
      <Stat label="Avg duration" value={duration(m.avgDurationSec)} />
      <Stat label="Avg revisions" value={m.avgRevisions.toFixed(1)} />
      <Stat label="Human approval" value={pct(m.humanApprovalRate)} />
      <Stat label="Test pass" value={pct(m.testPassRate)} />
      <Stat label="CI pass" value={pct(m.ciPassRate)} />
      <Stat label="Health score" value={m.healthScore ?? '–'} />
    </dl>
  );
}
