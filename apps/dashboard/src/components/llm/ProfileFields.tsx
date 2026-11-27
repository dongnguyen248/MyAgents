import type { ProfileDraft } from '../../lib/llmProfileDraft';
import { keyStatusText } from '../../lib/llmProfileDraft';
import { PROVIDERS, providerOption } from '../../lib/llmCatalog';
import type { LlmProfile } from '../../types/llm';
import {
  API_KEY_INPUT_ATTRS,
  BASE_URL_INPUT_NAME,
  PROFILE_NAME_INPUT_NAME,
  modelTextInputAttrs,
} from '../settings/modelFormAttrs';

export interface DraftProps {
  draft: ProfileDraft;
  patch: (next: Partial<ProfileDraft>) => void;
}

/** The operator-facing name: this is what the agent picker lists. */
export function NameField({ draft, patch }: DraftProps) {
  return (
    <label className="field">
      <span>Name</span>
      <input
        {...modelTextInputAttrs(PROFILE_NAME_INPUT_NAME)}
        autoFocus
        value={draft.name}
        onChange={(event) => patch({ name: event.target.value })}
        placeholder="OpenAI · GPT-4o"
      />
    </label>
  );
}

/** Which provider speaks to the endpoint; switching it drops the loaded models. */
export function ProviderField({
  draft,
  onProvider,
}: {
  draft: ProfileDraft;
  onProvider: (provider: string) => void;
}) {
  return (
    <label className="field">
      <span>Provider</span>
      <select value={draft.provider} onChange={(event) => onProvider(event.target.value)}>
        {PROVIDERS.map((provider) => (
          <option key={provider.value} value={provider.value}>
            {provider.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Endpoint base URL; blank means the provider default. */
export function BaseUrlField({ draft, patch }: DraftProps) {
  return (
    <label className="field">
      <span>Base URL{draft.provider === 'custom' ? '' : ' (optional override)'}</span>
      <input
        {...modelTextInputAttrs(BASE_URL_INPUT_NAME)}
        value={draft.baseUrl}
        onChange={(event) => patch({ baseUrl: event.target.value })}
        placeholder={providerOption(draft.provider)?.baseUrl ?? 'https://your-endpoint/v1'}
      />
    </label>
  );
}

function ClearKeyToggle({ draft, patch }: DraftProps) {
  return (
    <label className="field check">
      <input
        type="checkbox"
        checked={draft.clearKey}
        onChange={(event) => patch({ clearKey: event.target.checked })}
      />
      <span>Remove the stored key on save</span>
    </label>
  );
}

/** Write-only key: a blank field keeps whatever the backend already stores. */
export function KeyField({ draft, patch, profile }: DraftProps & { profile: LlmProfile | null }) {
  return (
    <>
      <label className="field">
        <span className="row-between">
          <span>API key</span>
          <span className="muted small">{keyStatusText(profile ?? undefined)}</span>
        </span>
        <input
          {...API_KEY_INPUT_ATTRS}
          type="password"
          value={draft.apiKey}
          onChange={(event) => patch({ apiKey: event.target.value })}
          placeholder={
            profile?.keyConfigured ? 'Leave blank to keep the stored key' : 'Paste the API key'
          }
        />
      </label>
      {profile?.keyConfigured && <ClearKeyToggle draft={draft} patch={patch} />}
    </>
  );
}

const MODEL_SELECT_ID = 'llm-profile-model';

function ModelOptions({ models, value }: { models: string[]; value: string }) {
  const options = value && !models.includes(value) ? [value, ...models] : models;
  return (
    <>
      <option value="">{models.length ? 'Pick a model' : 'Load the models first'}</option>
      {options.map((model) => (
        <option key={model} value={model}>
          {model}
        </option>
      ))}
    </>
  );
}

interface ModelFieldProps extends DraftProps {
  models: string[];
  loading: boolean;
  onLoad: () => void;
}

/** The model is picked from what the endpoint returned, never typed. */
export function ModelField({ draft, patch, models, loading, onLoad }: ModelFieldProps) {
  return (
    <div className="field">
      <span className="row-between">
        <label htmlFor={MODEL_SELECT_ID}>Model</label>
        <button type="button" className="btn btn-ghost" disabled={loading} onClick={onLoad}>
          {loading ? 'Loading…' : 'Load models'}
        </button>
      </span>
      <select
        id={MODEL_SELECT_ID}
        value={draft.model}
        onChange={(event) => patch({ model: event.target.value })}
      >
        <ModelOptions models={models} value={draft.model} />
      </select>
    </div>
  );
}
