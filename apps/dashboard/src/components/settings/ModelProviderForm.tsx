import { useState } from 'react';
import type { ModelSettings, ModelTestResult } from '../../types/settings';
import { testModelSettings, updateModelSettings } from '../../features/settings';

const PROVIDERS: { value: string; label: string }[] = [
  { value: 'scripted', label: 'Scripted demo replies (no API key)' },
  { value: 'gemini', label: 'Google Gemini' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'github-models', label: 'GitHub Models (GitHub token)' },
  { value: 'meta', label: 'Meta Model API (Muse Spark)' },
  { value: 'custom', label: 'Custom OpenAI-compatible endpoint' },
];

const MODEL_PLACEHOLDERS: Record<string, string> = {
  gemini: 'gemini-2.0-flash',
  openai: 'gpt-4o',
  'github-models': 'openai/gpt-4o',
  meta: 'muse-spark-1.3',
  custom: 'model id at your endpoint',
};

const DEFAULT_BASE_URLS: Record<string, string> = {
  openai: 'https://api.openai.com/v1',
  'github-models': 'https://models.github.ai/inference',
  meta: 'https://api.meta.ai/v1',
};

/** Agents that call a model and may carry their own model override. */
const AGENT_FIELDS: { key: string; label: string }[] = [
  { key: 'spec', label: 'Spec agent' },
  { key: 'plan', label: 'Plan agent' },
  { key: 'task', label: 'Task agent' },
  { key: 'implement', label: 'Implement agent' },
  { key: 'review', label: 'Review agent' },
  { key: 'fix', label: 'Fix agent' },
];

/**
 * Provider / model / API key for the agents, stored by the backend.
 * The key is write-only: after saving, only "configured …last4" shows.
 */
export function ModelProviderForm({ initial }: { initial: ModelSettings }) {
  const [provider, setProvider] = useState(initial.provider);
  const [model, setModel] = useState(initial.model);
  const [baseUrl, setBaseUrl] = useState(initial.baseUrl);
  const [agentModels, setAgentModels] = useState<Record<string, string>>(
    () => ({ ...(initial.agentModels ?? {}) }),
  );
  const [apiKey, setApiKey] = useState('');
  const [clearKey, setClearKey] = useState(false);
  const [saved, setSaved] = useState<ModelSettings>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [test, setTest] = useState<ModelTestResult | null>(null);
  const [testFor, setTestFor] = useState('');

  const needsKey = provider !== 'scripted';
  const showBaseUrl = provider === 'custom' || provider in DEFAULT_BASE_URLS;

  const buildInput = () => ({
    provider,
    model: model.trim(),
    baseUrl: baseUrl.trim(),
    agentModels: Object.fromEntries(
      Object.entries(agentModels)
        .map(([k, v]) => [k, v.trim()] as const)
        .filter(([, v]) => v),
    ),
    ...(apiKey ? { apiKey } : {}),
    ...(clearKey ? { clearKey: true } : {}),
  });

  const save = async (): Promise<boolean> => {
    setBusy(true);
    setError('');
    try {
      const next = await updateModelSettings(buildInput());
      setSaved(next);
      setAgentModels({ ...(next.agentModels ?? {}) });
      setApiKey('');
      setClearKey(false);
      setNotice('Saved. The new provider applies to the next agent calls — no restart needed.');
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const saveAndTest = async () => {
    setTest(null);
    setTestFor('');
    setNotice('');
    if (!(await save())) return;
    setBusy(true);
    try {
      setTest(await testModelSettings());
    } catch (e) {
      setTest({ ok: false, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  const saveAndTestAgent = async (key: string, label: string) => {
    setTest(null);
    setTestFor(label);
    setNotice('');
    if (!(await save())) return;
    setBusy(true);
    try {
      setTest(await testModelSettings(key));
    } catch (e) {
      setTest({ ok: false, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="project-form"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <div className="form-grid">
        <label className="field">
          <span>Provider</span>
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Model (shared default)</span>
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder={MODEL_PLACEHOLDERS[provider] ?? '—'}
            disabled={!needsKey}
          />
        </label>
      </div>
      {showBaseUrl && (
        <label className="field block">
          <span>Base URL{provider === 'custom' ? '' : ' (optional override)'}</span>
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={DEFAULT_BASE_URLS[provider] ?? 'https://your-endpoint/v1'}
          />
        </label>
      )}
      <fieldset>
        <legend>Per-agent models (optional)</legend>
        <p className="muted small">
          Leave an agent blank to use the shared model above. An override uses the same
          provider, endpoint and key — only the model differs. The Test agent never calls
          a model, so it has no setting here.
        </p>
        <div className="form-grid">
          {AGENT_FIELDS.map((a) => (
            <div className="field" key={a.key}>
              <span>{a.label}</span>
              <div className="agent-model-row">
                <input
                  value={agentModels[a.key] ?? ''}
                  onChange={(e) =>
                    setAgentModels((prev) => ({ ...prev, [a.key]: e.target.value }))
                  }
                  placeholder={model.trim() ? `Shared: ${model.trim()}` : 'Shared model'}
                  disabled={!needsKey}
                />
                <button
                  type="button"
                  className="btn"
                  disabled={busy || !needsKey}
                  onClick={() => void saveAndTestAgent(a.key, a.label)}
                >
                  Test
                </button>
              </div>
            </div>
          ))}
        </div>
      </fieldset>
      {needsKey && (
        <>
          <label className="field block">
            <span>API key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={saved.keyConfigured ? 'Leave blank to keep the stored key' : 'Paste the provider API key'}
              autoComplete="off"
            />
          </label>
          <p className="muted small">
            {saved.keyConfigured
              ? `A key is stored on the backend (${saved.keyHint || 'hidden'}). It is never shown again.`
              : 'No key stored yet.'}
            {provider === 'github-models' &&
              ' Use a GitHub personal access token; models are served by GitHub Models, not the Copilot editor API.'}
            {provider === 'meta' &&
              ' API key from the Meta Model API dashboard at dev.meta.ai.'}
          </p>
          {saved.keyConfigured && (
            <label className="field check">
              <input type="checkbox" checked={clearKey} onChange={(e) => setClearKey(e.target.checked)} />
              <span>Remove the stored key on save</span>
            </label>
          )}
        </>
      )}
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="muted small">{notice}</p>}
      {test && (
        <p className={test.ok ? 'muted small' : 'error-text'}>
          {test.ok ? '✓ ' : '✗ '}{testFor ? `${testFor}: ` : ''}{test.message}
        </p>
      )}
      <div className="form-actions">
        <button type="submit" className="btn" disabled={busy}>Save</button>
        <button type="button" className="btn ghost" disabled={busy} onClick={() => void saveAndTest()}>
          Save &amp; test connection
        </button>
      </div>
      <p className="muted small">
        Settings are stored by the backend on this machine (next to its run database) and take effect
        immediately. The shared model is every agent's default; a per-agent model overrides it for
        that agent only.
      </p>
    </form>
  );
}
