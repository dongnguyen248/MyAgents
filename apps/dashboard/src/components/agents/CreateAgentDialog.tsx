import { AGENT_TYPES, agentMeta } from '../../lib/agentCatalog';
import type { AgentType } from '../../types/agent';
import { Icon } from '../common/Icon';
import { Modal } from '../common/Modal';
import { useCreateAgentForm, type CreateForm } from './useCreateAgentForm';

function AgentKeyField({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  return (
    <>
      <label className="field">
        <span>Agent key</span>
        <input
          value={value}
          onChange={(event) => onChange(event.target.value.toLowerCase())}
          placeholder="report-writer"
          aria-describedby="agent-key-hint"
        />
      </label>
      <p className="note" id="agent-key-hint">
        Lowercase letters, digits and dashes, starting with a letter. The key is permanent.
      </p>
    </>
  );
}

function NameAndKeyFields({
  form,
  patch,
}: {
  form: CreateForm;
  patch: (next: Partial<CreateForm>) => void;
}) {
  return (
    <>
      <label className="field">
        <span>Name</span>
        <input
          autoFocus
          value={form.name}
          onChange={(event) => patch({ name: event.target.value })}
          placeholder="Report writer"
        />
      </label>
      <AgentKeyField value={form.id} onChange={(id) => patch({ id })} />
    </>
  );
}

function TypeField({ value, onChange }: { value: AgentType; onChange: (type: AgentType) => void }) {
  return (
    <label className="field">
      <span>Follows</span>
      <select value={value} onChange={(event) => onChange(event.target.value as AgentType)}>
        {AGENT_TYPES.map((type) => (
          <option key={type} value={type}>
            {agentMeta(type).label}
          </option>
        ))}
      </select>
    </label>
  );
}

function CreateFooter({
  busy,
  ready,
  onClose,
}: {
  busy: boolean;
  ready: boolean;
  onClose: () => void;
}) {
  return (
    <>
      <button type="button" className="btn btn-ghost" onClick={onClose}>
        Cancel
      </button>
      <span className="spacer" />
      <button type="submit" className="btn btn-primary" disabled={busy || !ready}>
        <Icon name="plus" className="icon-sm" />
        {busy ? 'Creating…' : 'Create agent'}
      </button>
    </>
  );
}

/** Create a custom agent: slug, display name and the built-in type it follows. */
export function CreateAgentDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { form, patch, busy, error, ready, submit } = useCreateAgentForm(onCreated, onClose);
  return (
    <Modal
      label="Create agent"
      title="Create agent"
      description="A custom agent runs the same prompts and limits as its type."
      onClose={onClose}
      onSubmit={() => void submit()}
      footer={<CreateFooter busy={busy} ready={ready} onClose={onClose} />}
    >
      <NameAndKeyFields form={form} patch={patch} />
      <TypeField value={form.type} onChange={(type) => patch({ type })} />
      {error && <p className="error-text">{error}</p>}
    </Modal>
  );
}
