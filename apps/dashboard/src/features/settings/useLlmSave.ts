import { useState } from 'react';
import { useModelTest } from './useModelTest';
import { updateModelSettings } from '../../services/settings/settingsService';
import { messageOf } from '../../lib/llmDraft';
import type { ModelSettings } from '../../types/settings';
import { useLlmDraft, type LlmDraft } from './useLlmDraft';

interface SaveStatus {
  busy: boolean;
  error?: string;
  notice?: string;
}

/** Owns the stored snapshot plus the busy/error/notice state of one save. */
export function useLlmSave(initial: ModelSettings, draft: LlmDraft) {
  const [saved, setSaved] = useState(initial);
  const [status, setStatus] = useState<SaveStatus>({ busy: false });

  const save = async (): Promise<boolean> => {
    setStatus({ busy: true });
    try {
      const next = await updateModelSettings(draft.payload(saved));
      setSaved(next);
      draft.reset(next);
      setStatus({ busy: false, notice: 'Saved — the next agent call uses it.' });
      return true;
    } catch (error) {
      setStatus({ busy: false, error: messageOf(error) });
      return false;
    }
  };

  return { saved, status, save };
}

/** Everything the LLM page needs: the draft, the save flow and one shared test probe. */
export function useLlmSettingsForm(initial: ModelSettings) {
  const draft = useLlmDraft(initial);
  const { saved, status, save } = useLlmSave(initial, draft);
  const modelTest = useModelTest();
  const saveThenTest = async (agentKey?: string) => {
    if (await save()) {
      await modelTest.run(agentKey);
    }
  };
  return { draft, saved, status, save, modelTest, saveThenTest };
}
