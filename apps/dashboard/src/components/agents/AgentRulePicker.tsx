import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAsync } from '../../hooks/useAsync';
import { messageOf } from '../../lib/message';
import { api, backendBaseUrl } from '../../services/api';
import type { Agent } from '../../types/agent';
import type { RuleFile } from '../../types/rule';

function useRuleSelection(agent: Agent, initial: string[], rules: RuleFile[]) {
  const [selected, setSelected] = useState(() =>
    initial.filter((id) => rules.some((rule) => rule.id === id)),
  );
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  function toggle(id: string) {
    setSelected((items) =>
      items.includes(id) ? items.filter((item) => item !== id) : [...items, id],
    );
  }
  async function save() {
    setBusy(true);
    setStatus('');
    try {
      setSelected(await api.saveAgentRules(agent.id, selected));
      setStatus('Saved for new runs.');
    } catch (error) {
      setStatus(`Could not save: ${messageOf(error)}`);
    } finally {
      setBusy(false);
    }
  }
  return { selected, busy, status, toggle, save };
}

function RuleChoices({
  rules,
  selected,
  toggle,
}: {
  rules: RuleFile[];
  selected: string[];
  toggle: (id: string) => void;
}) {
  return (
    <div className="agent-skill-choices">
      {rules.map((rule) => (
        <label className="agent-skill-option" key={rule.id}>
          <input
            type="checkbox"
            checked={selected.includes(rule.id)}
            onChange={() => toggle(rule.id)}
          />
          <span>
            <strong>{rule.name}</strong>
            <small>{rule.path}</small>
          </span>
        </label>
      ))}
    </div>
  );
}

function MissingRulesNotice() {
  return (
    <p className="alert">
      Some assigned rule files are missing. Saving removes those assignments; new runs fail until
      they are restored or removed.
    </p>
  );
}

function PackagedGuardrails({ agent }: { agent: Agent }) {
  const packageName = agent.type.replaceAll('-', '_');
  return (
    <p className="note">
      Packaged prompts and guardrails (when present) remain unchanged. Guardrail file:{' '}
      <span className="mono">src/asf/agents/{packageName}/instructions/guardrails.md</span> and are
      not changed by this selection.
    </p>
  );
}

type Props = { agent: Agent; rules: RuleFile[]; initial: string[] };
function RuleSelectionForm({ agent, rules, initial }: Props) {
  const { selected, busy, status, toggle, save } = useRuleSelection(agent, initial, rules);
  const missing = initial.some((id) => !rules.some((rule) => rule.id === id));
  return (
    <div className="stack-sm">
      <p className="note">
        Choose additional rules for this agent. Project rules and agent guardrails still apply.
        Design agents filter by task stack, scope and budget.
      </p>
      <PackagedGuardrails agent={agent} />
      <RuleChoices rules={rules} selected={selected} toggle={toggle} />
      {rules.length === 0 && <p className="note">No rule files available.</p>}
      {missing && <MissingRulesNotice />}
      {!backendBaseUrl && (
        <p className="note">Demo mode: connect the API to load the real rules.</p>
      )}
      <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void save()}>
        {busy ? 'Saving…' : 'Save rules'}
      </button>
      {status && (
        <p role="status" className="note">
          {status}
        </p>
      )}
      <p className="note">
        View and edit shared files in the <Link to="/rules">rules library</Link>.
      </p>
    </div>
  );
}

export function AgentRulePicker({ agent }: { agent: Agent }) {
  const data = useAsync(
    () => Promise.all([api.listRules(), api.getAgentRules(agent.id)]),
    [agent.id],
  );
  if (agent.type === 'test') {
    return (
      <p className="note">The Test agent runs commands and has no model prompt for these rules.</p>
    );
  }
  if (agent.custom || agent.id !== `agent-${agent.type}`) {
    return <p className="note">Rule assignment is not supported for this agent.</p>;
  }
  if (data.error) {
    return (
      <p className="alert" role="alert">
        Cannot load rules: {data.error.message}
      </p>
    );
  }
  if (!data.data) {
    return <p className="note">Loading rules…</p>;
  }
  return <RuleSelectionForm agent={agent} rules={data.data[0]} initial={data.data[1]} />;
}
