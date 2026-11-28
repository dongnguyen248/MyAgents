import { useState } from 'react';
import { useAsync } from '../../hooks/useAsync';
import { messageOf } from '../../lib/message';
import { api, backendBaseUrl } from '../../services/api';
import type { Agent } from '../../types/agent';
import type { AgentModelInput, ModelSettings } from '../../types/agentSetup';
import { secretInputAttrs, textInputAttrs } from '../forms/inputAttrs';

type Draft = AgentModelInput;

function initialDraft(agent: Agent, settings: ModelSettings): Draft {
  const connection = settings.agentConnections[agent.type];
  return {
    agent: agent.type,
    provider: connection?.provider ?? '',
    baseUrl: connection?.baseUrl ?? '',
    model: settings.agentModels[agent.type] ?? '',
    apiKey: '',
  };
}

type FieldProps = { draft: Draft; setDraft: (value: Draft) => void; settings: ModelSettings };

function ProviderField({ draft, setDraft, settings }: FieldProps) {
  return (
    <label className="field">
      <span>Provider</span>
      <select
        value={draft.provider}
        onChange={(event) => setDraft({ ...draft, provider: event.target.value })}
      >
        <option value="">Inherit shared ({settings.provider})</option>
        <option value="scripted">Scripted</option>
        <option value="openai">OpenAI</option>
        <option value="gemini">Gemini</option>
        <option value="github-models">GitHub Models</option>
        <option value="meta">Meta</option>
        <option value="custom">OpenAI-compatible</option>
      </select>
    </label>
  );
}

function ModelFields({ draft, setDraft, settings }: FieldProps) {
  return (
    <div className="stack-sm">
      <ProviderField draft={draft} setDraft={setDraft} settings={settings} />
      <label className="field">
        <span>Model override</span>
        <input
          {...textInputAttrs('agent-llm-model')}
          value={draft.model}
          placeholder={settings.model || 'Shared model'}
          onChange={(event) => setDraft({ ...draft, model: event.target.value })}
        />
      </label>
      <label className="field">
        <span>Endpoint override</span>
        <input
          {...textInputAttrs('agent-llm-endpoint')}
          value={draft.baseUrl}
          placeholder={settings.baseUrl || 'Inherit provider default'}
          onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })}
        />
      </label>
    </div>
  );
}

function ClearKey({ draft, setDraft }: { draft: Draft; setDraft: (value: Draft) => void }) {
  return (
    <label className="check">
      <input
        type="checkbox"
        checked={Boolean(draft.clearKey)}
        onChange={(event) => setDraft({ ...draft, clearKey: event.target.checked, apiKey: '' })}
      />{' '}
      Remove agent key
    </label>
  );
}

function KeyField({
  draft,
  setDraft,
  configured,
}: {
  draft: Draft;
  setDraft: (value: Draft) => void;
  configured: boolean;
}) {
  return (
    <div className="stack-sm">
      <label className="field">
        <span>Agent API key</span>
        <input
          type="password"
          {...secretInputAttrs('agent-llm-secret')}
          value={draft.apiKey ?? ''}
          placeholder={
            configured ? 'Stored; leave blank to keep' : 'Inherit shared key when permitted'
          }
          onChange={(event) => setDraft({ ...draft, apiKey: event.target.value, clearKey: false })}
        />
      </label>
      {configured && <ClearKey draft={draft} setDraft={setDraft} />}
    </div>
  );
}

function useModelForm({ agent, settings }: { agent: Agent; settings: ModelSettings }) {
  const [draft, setDraft] = useState(() => initialDraft(agent, settings));
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState(settings);
  async function save() {
    setBusy(true);
    setStatus('');
    try {
      setCurrent(await api.saveAgentModel(draft));
      setDraft({ ...draft, apiKey: '', clearKey: false });
      setStatus('Saved. The next model call uses these settings.');
    } catch (error) {
      setStatus(`Could not save: ${messageOf(error)}`);
    } finally {
      setBusy(false);
    }
  }
  return { draft, setDraft, status, busy, current, save };
}

function ModelNotice() {
  return (
    <p className="note">
      Blank fields inherit shared settings. A different endpoint may require its own key.
      Complex-tier requests may use the shared model.
    </p>
  );
}

function ModelForm({ agent, settings }: { agent: Agent; settings: ModelSettings }) {
  const { draft, setDraft, status, busy, current, save } = useModelForm({ agent, settings });
  return (
    <form
      className="stack-sm"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <ModelFields draft={draft} setDraft={setDraft} settings={settings} />
      <KeyField
        draft={draft}
        setDraft={setDraft}
        configured={Boolean(current.agentConnections[agent.type]?.keyConfigured)}
      />
      <ModelNotice />
      {!backendBaseUrl && <p className="note">Demo mode: changes last only for this session.</p>}
      <button className="btn btn-primary" type="submit" disabled={busy}>
        {busy ? 'Saving…' : 'Save LLM settings'}
      </button>
      {status && (
        <p role="status" className="note">
          {status}
        </p>
      )}
    </form>
  );
}

export function AgentProfilePicker({ agent }: { agent: Agent }) {
  const settings = useAsync(api.getModelSettings);
  if (agent.type === 'test') {
    return <p className="note">The Test agent runs commands and does not call an LLM.</p>;
  }
  if (agent.custom || agent.id !== `agent-${agent.type}`) {
    return <p className="note">Per-agent LLM settings are not supported for this agent.</p>;
  }
  if (settings.error) {
    return (
      <p className="alert" role="alert">
        Cannot load model settings: {settings.error.message}
      </p>
    );
  }
  if (!settings.data) {
    return <p className="note">Loading model settings…</p>;
  }
  return <ModelForm agent={agent} settings={settings.data} />;
}
