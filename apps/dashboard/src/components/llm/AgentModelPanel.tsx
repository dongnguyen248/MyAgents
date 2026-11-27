import type { LlmDraft } from '../../features/settings/useLlmDraft';
import { AGENT_MODEL_FIELDS, type AgentModelField } from '../../lib/llmCatalog';
import { agentModelInputName, modelTextInputAttrs } from '../settings/modelFormAttrs';

interface RowProps {
  field: AgentModelField;
  value: string;
  sharedModel: string;
  disabled: boolean;
  busy: boolean;
  onChange: (value: string) => void;
  onTest: () => void;
}

function AgentModelRow({ field, value, sharedModel, disabled, busy, onChange, onTest }: RowProps) {
  return (
    <div className="llm-row">
      <span className="llm-row-label">{field.label}</span>
      <input
        {...modelTextInputAttrs(agentModelInputName(field.key))}
        value={value}
        placeholder={sharedModel ? `Shared: ${sharedModel}` : 'Shared model'}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
      <span className="chip">{value.trim() !== '' ? 'override' : 'inherits'}</span>
      <button type="button" className="btn" disabled={busy || disabled} onClick={onTest}>
        Test
      </button>
    </div>
  );
}

interface PanelProps {
  draft: LlmDraft;
  sharedModel: string;
  busy: boolean;
  onTest: (agentKey: string) => void;
}

/** One row per agent that calls a model; a blank row inherits the shared model. */
export function AgentModelPanel({ draft, sharedModel, busy, onTest }: PanelProps) {
  return (
    <div className="llm-list">
      <p className="note">
        Leave a row blank to use the shared model. An override keeps the same provider, endpoint and
        key — only the model id differs. The Test agent never calls a model, so it has no row here.
      </p>
      {AGENT_MODEL_FIELDS.map((field) => (
        <AgentModelRow
          key={field.key}
          field={field}
          value={draft.state.agentModels[field.key] ?? ''}
          sharedModel={sharedModel}
          disabled={draft.state.provider === 'scripted'}
          busy={busy}
          onChange={(value) => draft.setAgentModel(field.key, value)}
          onTest={() => onTest(field.key)}
        />
      ))}
    </div>
  );
}
