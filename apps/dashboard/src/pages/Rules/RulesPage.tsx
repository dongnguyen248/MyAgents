import { useEffect, useState } from 'react';
import { AsyncView } from '../../components/common/AsyncView';
import { PageHeader } from '../../components/common/Layout';
import { RuleFileEditor } from '../../components/rules/RuleFileEditor';
import { useAsync } from '../../hooks/useAsync';
import { api, backendBaseUrl } from '../../services/api';
import type { RuleFile } from '../../types/rule';

function useRuleSelection() {
  const [id, setId] = useState<string>();
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    function warn(event: BeforeUnloadEvent) {
      if (dirty) {
        event.preventDefault();
      }
    }
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  function select(next: string) {
    if (dirty && !window.confirm('Discard unsaved changes?')) {
      return;
    }
    setDirty(false);
    setId(next);
  }
  return { id, select, setDirty };
}

type Selection = ReturnType<typeof useRuleSelection>;
function RuleExplorer({ rules, selection }: { rules: RuleFile[]; selection: Selection }) {
  return (
    <nav className="skill-explorer" aria-label="Rule files">
      <div className="skill-explorer-head">
        <strong>Rules library</strong>
        <span>{rules.length} files</span>
      </div>
      {rules.map((rule) => (
        <button
          key={rule.id}
          type="button"
          className={`skill-tree-file ${selection.id === rule.id ? 'selected' : ''}`}
          onClick={() => selection.select(rule.id)}
        >
          ▤ &nbsp;{rule.id}
        </button>
      ))}
      {!rules.length && <p className="note skill-empty">No Markdown files found in rules/.</p>}
    </nav>
  );
}

function RuleLibrary({ rules, selection }: { rules: RuleFile[]; selection: Selection }) {
  const current = rules.find((rule) => rule.id === selection.id);
  return (
    <div className="skill-workspace">
      <RuleExplorer rules={rules} selection={selection} />
      <main className="skill-content">
        {current ? (
          <RuleFileEditor key={current.id} rule={current} onDirty={selection.setDirty} />
        ) : (
          <div className="skill-overview">
            <span className="skill-eyebrow">PROJECT RULES</span>
            <h2>Rules library</h2>
            <p className="skill-description">
              Select a file to inspect or edit it. In agent setup, choose additional rules for each
              agent.
            </p>
            <section className="skill-detail-card">
              <h3>Existing rules remain active</h3>
              <p className="note">
                Project-configured rules and agent guardrails continue to apply independently of
                these assignments.
              </p>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

export function RulesPage() {
  const rules = useAsync(api.listRules);
  const selection = useRuleSelection();
  return (
    <>
      <PageHeader
        title="Rules"
        subtitle="Browse the project's rule files and assign additional guidance to agents."
        actions={
          <button type="button" className="btn btn-ghost" onClick={rules.reload}>
            ↻ Refresh
          </button>
        }
      />
      {!backendBaseUrl && (
        <p className="alert">Demo data only. Connect the API backend to browse and edit rules/.</p>
      )}
      <AsyncView {...rules}>
        {(data) => <RuleLibrary rules={data} selection={selection} />}
      </AsyncView>
    </>
  );
}
