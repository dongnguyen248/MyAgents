import { useState } from 'react';
import { testModelSettings } from '../../services/settings/settingsService';
import { agentLabel } from '../../lib/llmCatalog';
import { messageOf } from '../../lib/llmDraft';
import type { ModelTestResult } from '../../types/settings';

/** One "test connection" probe, for the shared model or a single agent. */
export function useModelTest() {
  const [test, setTest] = useState<ModelTestResult | null>(null);
  const [testFor, setTestFor] = useState('');

  const run = async (agentKey?: string) => {
    setTest(null);
    setTestFor(agentKey ? agentLabel(agentKey) : '');
    try {
      setTest(await testModelSettings(agentKey));
    } catch (error) {
      setTest({ ok: false, message: messageOf(error) });
    }
  };

  return { test, testFor, run };
}
