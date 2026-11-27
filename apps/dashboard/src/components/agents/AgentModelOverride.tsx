import { useState } from 'react';
import { useModelSettings, updateModelSettings } from '../../features/settings';
import type { Agent, AgentType } from '../../types/agent';
import type { ModelSettings } from '../../types/settings';

/** Agents that call a model and may carry their own override (mirrors MODEL_AGENTS). */
const MODEL_AGENTS: AgentType[] = [
  'spec',
  'plan',
  'task',
  'implement',
  'review',
  'fix',
  'artifact-review',
];

interface Status {
  saving: boolean;
  message?: string;
  failed?: boolean;
}

async function persistOverride(
  shared: ModelSettings,
  type: AgentType,
  model: string,
  onSaved: () => void,
): Promise<string> {
  const agentModels = { ...shared.agentModels };
  if (model) {
    agentModels[type] = model;
  } else {
    delete agentModels[type];
  }
  await updateModelSettings({
    provider: shared.provider,
    model: shared.model,
    baseUrl: shared.baseUrl,
    agentModels,
  });
  onSaved();
  return 'Saved — the next agent call uses it.';
}

/** Save state for one agent's override, kept out of the form component. */
function useOverrideSave(agent: Agent, shared: ModelSettings, onSaved: () => void) {
  const [status, setStatus] = useState<Status>({ saving: false });
  const save = async (model: string) => {
    setStatus({ saving: true });
    try {
      setStatus({
        saving: false,
        message: await persistOverride(shared, agent.type, model, onSaved),
      });
    } catch (error) {
      setStatus({ saving: false, message: (error as Error).message, failed: true });
    }
  };
  return { status, save };
}

function ModelField({
  value,
  fallback,
  onChange,
}: {
  value: string;
  fallback: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>Model override</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={fallback || 'Shared model'}
      />
    </label>
  );
}

function SaveRow({ shared, saving }: { shared: ModelSettings; saving: boolean }) {
  return (
    <div className="hint-row">
      <p className="note">
        Empty means {shared.model || 'the shared model'}, on {shared.provider}.
      </p>
      <button type="submit" className="btn" disabled={saving}>
        {saving ? 'Saving…' : 'Save'}
      </button>
    </div>
  );
}

function StatusLine({ status }: { status: Status }) {
  if (!status.message) {
    return null;
  }
  return (
    <p className={status.failed ? 'alert' : 'note'} role="status">
      {status.message}
    </p>
  );
}

function OverrideFields({
  value,
  shared,
  status,
  onChange,
  onSave,
}: {
  value: string;
  shared: ModelSettings;
  status: Status;
  onChange: (value: string) => void;
  onSave: () => void;
}) {
  return (
    <form
      className="stack-sm"
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      <ModelField value={value} fallback={shared.model} onChange={onChange} />
      <SaveRow shared={shared} saving={status.saving} />
      <StatusLine status={status} />
    </form>
  );
}

function ModelOverrideForm({
  agent,
  shared,
  onSaved,
}: {
  agent: Agent;
  shared: ModelSettings;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<string>();
  const { status, save } = useOverrideSave(agent, shared, onSaved);
  const value = draft ?? shared.agentModels[agent.type] ?? '';
  return (
    <OverrideFields
      value={value}
      shared={shared}
      status={status}
      onChange={setDraft}
      onSave={() => void save(value.trim())}
    />
  );
}

/** Per-agent model override: the one agent setting the API can actually persist. */
export function AgentModelOverride({ agent }: { agent: Agent }) {
  const settings = useModelSettings();
  if (!MODEL_AGENTS.includes(agent.type)) {
    return (
      <p className="note">
        The Test agent never calls a model: it runs the project’s configured test commands in the
        sandbox and reports their exit codes.
      </p>
    );
  }
  if (!settings.data) {
    return <p className="note">Model settings are unavailable for this backend.</p>;
  }
  return <ModelOverrideForm agent={agent} shared={settings.data} onSaved={settings.reload} />;
}
