import { AsyncView } from '../../components/common/AsyncView';
import { Card, KpiCard, PageHeader } from '../../components/common/Layout';
import { Chart } from '../../components/metrics/Chart';
import { useMetricsOverview } from '../../features/agent-metrics';
import { duration, pct, shortDate } from '../../utils/format';

const C = { a: 'var(--s1)', b: 'var(--s2)', c: 'var(--s3)', d: 'var(--s4)' };

export function MetricsPage() {
  const metrics = useMetricsOverview();
  return (
    <>
      <PageHeader title="Metrics" subtitle="Is the AI Software Factory getting better?" />
      <AsyncView {...metrics}>
        {(m) => {
          const labels = m.daily.map((d) => shortDate(d.date));
          const h = m.human;
          const q = m.quality;
          return (
            <>
              <h2 className="section">Agent performance</h2>
              <div className="grid two-col">
                <Card title="Tasks completed per day"><Chart kind="bar" title="Tasks completed per day" labels={labels} series={[{ name: 'Completed', values: m.daily.map((d) => d.completed), color: C.c }]} /></Card>
                <Card title="Tasks failed per day"><Chart kind="bar" title="Tasks failed per day" labels={labels} series={[{ name: 'Failed', values: m.daily.map((d) => d.failed), color: 'var(--danger)' }]} /></Card>
                <Card title="Success rate"><Chart kind="line" title="Success rate" labels={labels} format={(v) => pct(v, 0)} series={[{ name: 'Success rate', values: m.daily.map((d) => d.successRate), color: C.a }]} /></Card>
                <Card title="Average execution time"><Chart kind="line" title="Average execution time" labels={labels} format={(v) => duration(v)} series={[{ name: 'Avg time', values: m.daily.map((d) => d.avgDurationSec), color: C.b }]} /></Card>
              </div>

              <h2 className="section">Human interaction</h2>
              <div className="grid grid-kpi">
                <KpiCard label="Approval rate" value={pct(h.approvalRate)} />
                <KpiCard label="Rejection rate" value={pct(h.rejectionRate)} />
                <KpiCard label="Avg revisions" value={h.avgRevisions.toFixed(1)} />
                <KpiCard label="Avg approval time" value={`${h.avgApprovalMinutes.toFixed(1)} min`} />
              </div>
              <Card title="Approval vs rejection rate">
                <Chart kind="line" title="Approval versus rejection rate" labels={labels} format={(v) => pct(v, 0)} series={[{ name: 'Approval', values: h.daily.map((d) => d.approvalRate), color: C.c }, { name: 'Rejection', values: h.daily.map((d) => d.rejectionRate), color: 'var(--danger)' }]} />
              </Card>

              <h2 className="section">Engineering quality</h2>
              <div className="grid grid-kpi">
                <KpiCard label="Code review rejection" value={pct(q.codeReviewRejectionRate)} />
                <KpiCard label="Test pass rate" value={pct(q.testPassRate)} />
                <KpiCard label="CI pass rate" value={pct(q.ciPassRate)} />
                <KpiCard label="Bug / rework rate" value={pct(q.reworkRate)} />
              </div>
              <Card title="Test, CI and rework rates">
                <Chart kind="line" title="Test pass, CI pass and rework rates" labels={labels} format={(v) => pct(v, 0)} series={[{ name: 'Test pass', values: q.daily.map((d) => d.testPassRate), color: C.a }, { name: 'CI pass', values: q.daily.map((d) => d.ciPassRate), color: C.c }, { name: 'Rework', values: q.daily.map((d) => d.reworkRate), color: C.b }]} />
              </Card>

              <h2 className="section">Agent comparison</h2>
              <Card flush>
                <div className="table-wrap">
                  <table className="table">
                    <caption className="sr-only">Agent comparison</caption>
                    <thead><tr><th scope="col">Agent</th><th scope="col" className="num">Success</th><th scope="col" className="num">Avg duration</th><th scope="col" className="num">Avg revisions</th><th scope="col" className="num">Human approval</th><th scope="col" className="num">Health</th></tr></thead>
                    <tbody>
                      {m.agents.map((a) => (
                        <tr key={a.agentId}>
                          <th scope="row">{a.name}</th>
                          <td className="num">{pct(a.successRate)}</td>
                          <td className="num">{duration(a.avgDurationSec)}</td>
                          <td className="num">{a.avgRevisions.toFixed(1)}</td>
                          <td className="num">{pct(a.humanApprovalRate)}</td>
                          <td className="num"><strong>{a.healthScore}</strong></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <Card title="Health score by agent">
                <Chart kind="bar" title="Health score by agent" labels={m.agents.map((a) => a.name.replace(' Agent', ''))} series={[{ name: 'Health score', values: m.agents.map((a) => a.healthScore), color: C.d }]} />
              </Card>
            </>
          );
        }}
      </AsyncView>
    </>
  );
}
