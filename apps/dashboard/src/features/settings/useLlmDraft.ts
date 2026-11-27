import { useCallback, useState } from 'react';
import type { ConnFormState } from '../../lib/agentConnections';
import { draftFromSettings, payloadOf, type LlmDraftState } from '../../lib/llmDraft';
import type { ModelSettings, ModelSettingsInput } from '../../types/settings';

export interface LlmDraft {
  state: LlmDraftState;
  patch: (next: Partial<LlmDraftState>) => void;
  setAgentModel: (key: string, value: string) => void;
  patchConnection: (key: string, patch: Partial<ConnFormState>) => void;
  reset: (settings: ModelSettings) => void;
  payload: (saved: ModelSettings) => ModelSettingsInput;
}

/** Editable copy of the model settings, shared by the three LLM tabs. */
export function useLlmDraft(initial: ModelSettings): LlmDraft {
  const [state, setState] = useState<LlmDraftState>(() => draftFromSettings(initial));
  const patch = useCallback((next: Partial<LlmDraftState>) => {
    setState((previous) => ({ ...previous, ...next }));
  }, []);
  const setAgentModel = useCallback((key: string, value: string) => {
    setState((previous) => ({
      ...previous,
      agentModels: { ...previous.agentModels, [key]: value },
    }));
  }, []);
  const patchConnection = useCallback((key: string, next: Partial<ConnFormState>) => {
    setState((previous) => ({
      ...previous,
      connections: { ...previous.connections, [key]: { ...previous.connections[key], ...next } },
    }));
  }, []);
  const reset = useCallback((settings: ModelSettings) => {
    setState(draftFromSettings(settings));
  }, []);
  const payload = useCallback((saved: ModelSettings) => payloadOf(state, saved), [state]);
  return { state, patch, setAgentModel, patchConnection, reset, payload };
}
