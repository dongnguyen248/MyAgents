import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { AgentStatusBadge } from '../../components/agents/AgentStatusBadge';
import { useAgentConfig, useAgents } from '../../features/agent-management';
import { useProjects } from '../../features/project-management';
import type { AgentConfig } from '../../types/agent';

export function AgentSettingsIndexPage() {
  const agents = useAgents();
  return (
    <>
      <PageHeader title="Agent Settings" subtitle="Configuration, separate from runtime monitoring." />
      <Card flush>
        <AsyncView {...agents}>
          {(list) => (
            <ul className="plain list-links">
              {list.map((a) => (
                <li key={a.id} className="row-between">
                  <Link to={`/agents/${a.id}/settings`}>{a.name}</Link>
                  <AgentStatusBadge status={a.status} />
                </li>
              ))}
            </ul>
          )}
        </AsyncView>
      </Card>
    </>
  );
}

export function AgentSettingsPage() {
  const { agentId = '' } = useParams();
  const config = useAgentConfig(agentId);
  const projects = useProjects();
  const [draft, setDraft] = useState<AgentConfig>();
  const [saved, setSaved] = useState(false);

  useEffect(() => setDraft(config.data), [config.data]);
  const set = <K extends keyof AgentConfig>(k: K, v: AgentConfig[K]) => {
    setSaved(false);
    setDraft((d) => d && { ...d, [k]: v });
  };
  const list = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean);

  return (
    <>
      <PageHeader title="Agent configuration" back={{ to: `/agents/${agentId}`, label: 'Agent runtime view' }} subtitle="Mock configuration. Changes are not persisted to any backend." />
      <AsyncView data={draft} loading={config.loading} error={config.error}>
        {(c) => (
          <form className="form" onSubmit={(e) => { e.preventDefault(); setSaved(true); }}>
            <Card title="General">
              <div className="form-grid">
                <label className="field"><span>Agent name</span><input value={c.name} onChange={(e) => set('name', e.target.value)} /></label>
                <label className="field"><span>Agent type</span><input value={c.type} readOnly /></label>
                <label className="field"><span>Model</span><input value={c.model} onChange={(e) => set('model', e.target.value)} /></label>
                <label className="field"><span>Model version</span><input value={c.modelVersion} onChange={(e) => set('modelVersion', e.target.value)} /></label>
                <label className="check"><input type="checkbox" checked={c.enabled} onChange={(e) => set('enabled', e.target.checked)} /> Enabled</label>
              </div>
              <label className="field block"><span>System prompt</span><textarea rows={4} value={c.systemPrompt} onChange={(e) => set('systemPrompt', e.target.value)} /></label>
            </Card>
            <Card title="Capabilities">
              <label className="field block"><span>Skills (comma separated)</span><input value={c.skills.join(', ')} onChange={(e) => set('skills', list(e.target.value))} /></label>
              <label className="field block"><span>Tools (comma separated)</span><input value={c.tools.join(', ')} onChange={(e) => set('tools', list(e.target.value))} /></label>
              <fieldset className="field block">
                <legend>Allowed projects</legend>
                {(projects.data ?? []).map((p) => (
                  <label className="check" key={p.id}>
                    <input type="checkbox" checked={c.allowedProjectIds.includes(p.id)} onChange={(e) => set('allowedProjectIds', e.target.checked ? [...c.allowedProjectIds, p.id] : c.allowedProjectIds.filter((x) => x !== p.id))} /> {p.name}
                  </label>
                ))}
              </fieldset>
            </Card>
            <Card title="Execution limits">
              <div className="form-grid">
                <label className="field"><span>Max concurrent tasks</span><input type="number" min={1} value={c.maxConcurrentTasks} onChange={(e) => set('maxConcurrentTasks', Number(e.target.value))} /></label>
                <label className="field"><span>Timeout (seconds)</span><input type="number" min={1} value={c.timeoutSeconds} onChange={(e) => set('timeoutSeconds', Number(e.target.value))} /></label>
                <label className="field"><span>Max retries</span><input type="number" min={0} value={c.retryPolicy.maxRetries} onChange={(e) => set('retryPolicy', { ...c.retryPolicy, maxRetries: Number(e.target.value) })} /></label>
                <label className="field">
                  <span>Retry backoff</span>
                  <select value={c.retryPolicy.backoff} onChange={(e) => set('retryPolicy', { ...c.retryPolicy, backoff: e.target.value as AgentConfig['retryPolicy']['backoff'] })}>
                    <option value="none">None</option><option value="linear">Linear</option><option value="exponential">Exponential</option>
                  </select>
                </label>
              </div>
            </Card>
            <div className="toolbar">
              <button type="submit" className="btn btn-primary">Save (mock)</button>
              {saved && <span role="status" className="muted">Saved locally only. Nothing was sent to a backend.</span>}
            </div>
          </form>
        )}
      </AsyncView>
    </>
  );
}
