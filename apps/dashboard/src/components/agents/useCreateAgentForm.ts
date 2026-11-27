import { useState } from 'react';
import { createAgent } from '../../features/agent-management';
import { messageOf } from '../../lib/message';
import type { AgentType } from '../../types/agent';

/** Same shape the backend enforces for an agent slug. */
export const KEY_PATTERN = /^[a-z][a-z0-9-]*$/;

export interface CreateForm {
  id: string;
  name: string;
  type: AgentType;
}

/** Draft + submit state for the create-agent dialog. */
export function useCreateAgentForm(onCreated: () => void, onClose: () => void) {
  const [form, setForm] = useState<CreateForm>({ id: '', name: '', type: 'spec' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const patch = (next: Partial<CreateForm>) => setForm((previous) => ({ ...previous, ...next }));
  const ready = KEY_PATTERN.test(form.id) && form.name.trim() !== '';
  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      await createAgent({ ...form, name: form.name.trim() });
      onCreated();
      onClose();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };
  return { form, patch, busy, error, ready, submit };
}
