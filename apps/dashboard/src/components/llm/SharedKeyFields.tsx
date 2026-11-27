import type { LlmDraft } from '../../features/settings/useLlmDraft';
import { sharedKeyStatusText } from '../../lib/agentConnections';
import type { ModelSettings } from '../../types/settings';
import { API_KEY_INPUT_ATTRS } from '../settings/modelFormAttrs';

const PROVIDER_KEY_HINT: Record<string, string> = {
  'github-models':
    ' Use a GitHub personal access token; models are served by GitHub Models, not the Copilot editor API.',
  meta: ' API key from the Meta Model API dashboard at dev.meta.ai.',
};

/** Write-only shared key: a blank field keeps whatever the backend already stores. */
function ApiKeyField({ draft, saved }: { draft: LlmDraft; saved: ModelSettings }) {
  return (
    <label className="field">
      <span className="row-between">
        <span>API key</span>
        <span className="muted small">
          {sharedKeyStatusText(saved.keyConfigured, saved.keyHint)}
        </span>
      </span>
      <input
        {...API_KEY_INPUT_ATTRS}
        type="password"
        value={draft.state.apiKey}
        onChange={(event) => draft.patch({ apiKey: event.target.value })}
        placeholder={
          saved.keyConfigured ? 'Leave blank to keep the stored key' : 'Paste the provider API key'
        }
      />
    </label>
  );
}

function KeyNotes({ draft, saved }: { draft: LlmDraft; saved: ModelSettings }) {
  return (
    <>
      <p className="note">
        {saved.keyConfigured
          ? `A key is stored on the backend (${saved.keyHint || 'hidden'}). It is never shown again.`
          : 'No key stored yet.'}
        {PROVIDER_KEY_HINT[draft.state.provider] ?? ''}
      </p>
      {saved.keyConfigured && (
        <label className="field check">
          <input
            type="checkbox"
            checked={draft.state.clearKey}
            onChange={(event) => draft.patch({ clearKey: event.target.checked })}
          />
          <span>Remove the stored key on save</span>
        </label>
      )}
    </>
  );
}

export function SharedKeyFields({ draft, saved }: { draft: LlmDraft; saved: ModelSettings }) {
  if (draft.state.provider === 'scripted') {
    return (
      <p className="note">The scripted demo provider needs no key: replies come from a fixture.</p>
    );
  }
  return (
    <>
      <ApiKeyField draft={draft} saved={saved} />
      <KeyNotes draft={draft} saved={saved} />
    </>
  );
}
