import { useState } from 'react';
import { useLlmSettingsForm } from '../../features/settings';
import type { LlmDraft } from '../../features/settings';
import type { ModelSettings } from '../../types/settings';
import { AgentConnectionPanel } from './AgentConnectionPanel';
import { AgentModelPanel } from './AgentModelPanel';
import { LlmActionBar } from './LlmActionBar';
import { BaseUrlField, ProviderSelect, SharedModelField } from './ProviderFields';
import { SharedKeyFields } from './SharedKeyFields';

type LlmTab = 'provider' | 'models' | 'connections';

const TABS: { id: LlmTab; label: string }[] = [
  { id: 'provider', label: 'Provider & key' },
  { id: 'models', label: 'Per-agent models' },
  { id: 'connections', label: 'Per-agent connections' },
];

function LlmTabs({ tab, onSelect }: { tab: LlmTab; onSelect: (tab: LlmTab) => void }) {
  return (
    <div className="tabs" role="tablist" aria-label="LLM settings">
      {TABS.map((entry) => (
        <button
          key={entry.id}
          type="button"
          role="tab"
          className="tab"
          aria-selected={tab === entry.id}
          onClick={() => onSelect(entry.id)}
        >
          {entry.label}
        </button>
      ))}
    </div>
  );
}

interface SaveStatus {
  busy: boolean;
  error?: string;
  notice?: string;
}

interface TabBodyProps {
  tab: LlmTab;
  draft: LlmDraft;
  saved: ModelSettings;
  status: SaveStatus;
  onTest: (agentKey: string) => void;
}

function TabBody({ tab, draft, saved, status, onTest }: TabBodyProps) {
  if (tab === 'provider') {
    return (
      <div className="stack-sm">
        <div className="form-grid">
          <ProviderSelect draft={draft} />
          <SharedModelField draft={draft} />
        </div>
        <BaseUrlField draft={draft} />
        <SharedKeyFields draft={draft} saved={saved} />
      </div>
    );
  }
  if (tab === 'models') {
    return (
      <AgentModelPanel draft={draft} sharedModel={saved.model} busy={status.busy} onTest={onTest} />
    );
  }
  return <AgentConnectionPanel draft={draft} saved={saved} busy={status.busy} />;
}

interface FormProps {
  initial: ModelSettings;
}

export function LlmSettingsForm({ initial }: FormProps) {
  const { draft, saved, status, save, modelTest, saveThenTest } = useLlmSettingsForm(initial);
  const [tab, setTab] = useState<LlmTab>('provider');

  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <LlmTabs tab={tab} onSelect={setTab} />
      <TabBody
        tab={tab}
        draft={draft}
        saved={saved}
        status={status}
        onTest={(agentKey) => void saveThenTest(agentKey)}
      />
      <LlmActionBar
        status={status}
        test={modelTest.test}
        testFor={modelTest.testFor}
        onTest={() => void saveThenTest()}
      />
    </form>
  );
}
