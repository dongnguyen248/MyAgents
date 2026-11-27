import type { LlmDraft } from '../../features/settings/useLlmDraft';
import { PROVIDERS, providerOption } from '../../lib/llmCatalog';
import {
  BASE_URL_INPUT_NAME,
  SHARED_MODEL_INPUT_NAME,
  modelTextInputAttrs,
} from '../settings/modelFormAttrs';

/** Provider picker. */
export function ProviderSelect({ draft }: { draft: LlmDraft }) {
  const { state, patch } = draft;
  return (
    <label className="field">
      <span>Provider</span>
      <select value={state.provider} onChange={(event) => patch({ provider: event.target.value })}>
        {PROVIDERS.map((provider) => (
          <option key={provider.value} value={provider.value}>
            {provider.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** The shared model every agent falls back to. */
export function SharedModelField({ draft }: { draft: LlmDraft }) {
  const { state, patch } = draft;
  return (
    <label className="field">
      <span>Shared model</span>
      <input
        {...modelTextInputAttrs(SHARED_MODEL_INPUT_NAME)}
        value={state.model}
        placeholder={providerOption(state.provider)?.model ?? '—'}
        onChange={(event) => patch({ model: event.target.value })}
        disabled={state.provider === 'scripted'}
      />
    </label>
  );
}

/** Endpoint override; blank means the provider default. */
export function BaseUrlField({ draft }: { draft: LlmDraft }) {
  const { state, patch } = draft;
  return (
    <label className="field">
      <span>Base URL{state.provider === 'custom' ? '' : ' (optional override)'}</span>
      <input
        {...modelTextInputAttrs(BASE_URL_INPUT_NAME)}
        value={state.baseUrl}
        placeholder={providerOption(state.provider)?.baseUrl ?? 'https://your-endpoint/v1'}
        onChange={(event) => patch({ baseUrl: event.target.value })}
      />
    </label>
  );
}
