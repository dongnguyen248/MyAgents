import type { LlmDraft } from '../../features/settings/useLlmDraft';
import { AGENT_MODEL_FIELDS, type AgentModelField } from '../../lib/llmCatalog';
import type { AgentConnectionView, ModelSettings } from '../../types/settings';
import { AgentConnectionFields } from '../settings/AgentConnectionFields';

interface RowProps {
  field: AgentModelField;
  view?: AgentConnectionView;
  draft: LlmDraft;
  busy: boolean;
}

function ConnectionRow({ field, view, draft, busy }: RowProps) {
  return (
    <details className="conn-row">
      <summary>
        <span className="conn-row-name">{field.label}</span>
        {view ? (
          <span className="badge badge-info badge-sm">own connection</span>
        ) : (
          <span className="chip">inherits shared</span>
        )}
      </summary>
      <div className="conn-body">
        <AgentConnectionFields
          agentKey={field.key}
          state={draft.state.connections[field.key]}
          saved={view}
          disabled={busy}
          onChange={(patch) => draft.patchConnection(field.key, patch)}
        />
      </div>
    </details>
  );
}

/**
 * Per-agent connection profiles: an agent with its own endpoint, key, headers or
 * timeout overrides the shared settings above; every blank field inherits.
 */
export function AgentConnectionPanel({
  draft,
  saved,
  busy,
}: {
  draft: LlmDraft;
  saved: ModelSettings;
  busy: boolean;
}) {
  return (
    <div className="stack-sm">
      <p className="note">
        Give one agent its own endpoint, key, headers or timeout — for example a local proxy for one
        agent and a hosted provider for the rest. An agent with nothing here behaves exactly as
        before.
      </p>
      {AGENT_MODEL_FIELDS.map((field) => (
        <ConnectionRow
          key={field.key}
          field={field}
          view={saved.agentConnections?.[field.key]}
          draft={draft}
          busy={busy}
        />
      ))}
    </div>
  );
}
