import type { ConnFormState } from '../../lib/agentConnections';
import { ownKeyPlaceholder, ownKeyStatusText } from '../../lib/agentConnections';
import type { AgentConnectionView } from '../../types/settings';
import {
  agentConnectionInputName,
  agentKeyInputAttrs,
  modelTextInputAttrs,
} from './modelFormAttrs';

const CONN_PROVIDERS: { value: string; label: string }[] = [
  { value: '', label: 'Shared provider' },
  { value: 'scripted', label: 'Scripted demo replies' },
  { value: 'gemini', label: 'Google Gemini' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'github-models', label: 'GitHub Models (GitHub token)' },
  { value: 'meta', label: 'Meta Model API (Muse Spark)' },
  { value: 'custom', label: 'Custom OpenAI-compatible endpoint' },
];

interface FieldsProps {
  agentKey: string;
  state: ConnFormState;
  saved?: AgentConnectionView;
  disabled: boolean;
  onChange: (patch: Partial<ConnFormState>) => void;
}

function ConnectionProviderRow({ agentKey, state, disabled, onChange }: FieldsProps) {
  return (
    <div className="form-grid">
      <label className="field">
        <span>Provider</span>
        <select
          value={state.provider}
          onChange={(e) => onChange({ provider: e.target.value })}
          disabled={disabled}
        >
          {CONN_PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Timeout (seconds)</span>
        <input
          {...modelTextInputAttrs(agentConnectionInputName(agentKey, 'timeout'))}
          value={state.timeoutText}
          onChange={(e) => onChange({ timeoutText: e.target.value })}
          placeholder="System default"
          disabled={disabled}
        />
      </label>
    </div>
  );
}

function ConnectionUrlField({ agentKey, state, disabled, onChange }: FieldsProps) {
  const httpWarning = state.baseUrl.trim().startsWith('http://');
  return (
    <>
      <label className="field block">
        <span>API URL (base URL)</span>
        <input
          {...modelTextInputAttrs(agentConnectionInputName(agentKey, 'url'))}
          value={state.baseUrl}
          onChange={(e) => onChange({ baseUrl: e.target.value })}
          placeholder="Shared base URL"
          disabled={disabled}
        />
      </label>
      {httpWarning && (
        <p className="muted small">
          ⚠ http:// is not encrypted — fine for a local proxy, risky beyond this machine.
        </p>
      )}
    </>
  );
}

function ConnectionKeyField({ agentKey, state, saved, disabled, onChange }: FieldsProps) {
  const status = ownKeyStatusText(saved);
  const placeholder = ownKeyPlaceholder(saved);
  return (
    <>
      <label className="field block">
        <span style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <span>API key (own)</span>
          <span className="muted small" style={{ fontWeight: 'normal' }}>
            {status}
          </span>
        </span>
        <input
          {...agentKeyInputAttrs(agentKey)}
          type="password"
          value={state.apiKey}
          onChange={(e) => onChange({ apiKey: e.target.value })}
          placeholder={placeholder}
          disabled={disabled}
        />
      </label>
      <p className="muted small">
        {saved?.keyConfigured
          ? `An own key is stored for this agent (${saved.keyHint || 'hidden'}). It is never shown again.`
          : 'This agent currently inherits the shared API key above.'}
      </p>
      {saved?.keyConfigured && (
        <label className="field check">
          <input
            type="checkbox"
            checked={state.clearKey}
            onChange={(e) => onChange({ clearKey: e.target.checked })}
            disabled={disabled}
          />
          <span>Remove this agent’s stored key on save</span>
        </label>
      )}
    </>
  );
}

function ConnectionHeadersField({ agentKey, state, disabled, onChange }: FieldsProps) {
  return (
    <label className="field block">
      <span>Custom headers (one “Name: value” per line)</span>
      <textarea
        {...modelTextInputAttrs(agentConnectionInputName(agentKey, 'headers'))}
        value={state.headersText}
        onChange={(e) => onChange({ headersText: e.target.value, headersDirty: true })}
        placeholder="Shared: no extra headers"
        rows={2}
        disabled={disabled}
      />
    </label>
  );
}

function ConnectionNote({ state, saved, disabled, onChange }: FieldsProps) {
  return (
    <>
      <p className="muted small">
        {saved
          ? 'This agent has its own connection; stored header values stay hidden (****) and are replaced only if you edit the box.'
          : 'No own connection yet — this agent uses the shared settings.'}
      </p>
      {saved && (
        <label className="field check">
          <input
            type="checkbox"
            checked={state.remove}
            onChange={(e) => onChange({ remove: e.target.checked })}
            disabled={disabled}
          />
          <span>Remove this agent’s own connection on save</span>
        </label>
      )}
    </>
  );
}

/**
 * One agent's own API connection: provider, endpoint, key, headers
 * and timeout. Every field left blank inherits the shared settings.
 */
export function AgentConnectionFields(props: FieldsProps) {
  return (
    <div className="agent-conn">
      <ConnectionProviderRow {...props} />
      <ConnectionUrlField {...props} />
      <ConnectionKeyField {...props} />
      <ConnectionHeadersField {...props} />
      <ConnectionNote {...props} />
    </div>
  );
}
