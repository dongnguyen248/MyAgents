import { Link } from 'react-router-dom';
import { useAsync } from '../../hooks/useAsync';
import { api } from '../../services/api';
import type { RuleFile } from '../../types/rule';

interface Props {
  selected: string[];
  onChange: (rules: string[]) => void;
  legacyFiles?: string[];
  hasInlineRules?: boolean;
}

function RuleChoice({
  rule,
  checked,
  toggle,
}: {
  rule: RuleFile;
  checked: boolean;
  toggle: (id: string) => void;
}) {
  return (
    <label className="agent-skill-option">
      <input type="checkbox" checked={checked} onChange={() => toggle(rule.id)} />
      <span>
        <strong>{rule.name}</strong>
        <small>{rule.path}</small>
      </span>
    </label>
  );
}

function RuleChoices({
  rules,
  selected,
  onChange,
}: {
  rules: RuleFile[];
  selected: string[];
  onChange: Props['onChange'];
}) {
  const missing = selected.filter((id) => !rules.some((rule) => rule.id === id));
  const choices = [
    ...rules,
    ...missing.map((id) => ({ id, name: id, path: 'Missing — restore or uncheck before saving.' })),
  ];
  function toggle(id: string) {
    onChange(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]);
  }
  return (
    <div className="agent-skill-choices">
      {choices.map((rule) => (
        <RuleChoice
          key={rule.id}
          rule={rule}
          checked={selected.includes(rule.id)}
          toggle={toggle}
        />
      ))}
    </div>
  );
}

function LegacyNotice({
  legacyFiles = [],
  hasInlineRules,
}: Pick<Props, 'legacyFiles' | 'hasInlineRules'>) {
  if (!legacyFiles.length && !hasInlineRules) {
    return null;
  }
  return (
    <p className="note">
      Existing legacy project rules remain active and are preserved on save
      {legacyFiles.length ? `: ${legacyFiles.join(', ')}` : ''}
      {hasInlineRules ? ' (including inline rules)' : ''}.
    </p>
  );
}

export function ProjectRulePicker({ selected, onChange, legacyFiles, hasInlineRules }: Props) {
  const catalogue = useAsync(() => api.listRules(), []);
  return (
    <fieldset className="field block">
      <legend>Project rules</legend>
      <p className="note">
        Select shared rules for this project. Language packs apply automatically by technology;
        agent-specific rules and packaged guardrails also apply. Manage files in the{' '}
        <Link to="/rules">rules library</Link>.
      </p>
      {catalogue.error && (
        <p className="alert" role="alert">
          Cannot load rules: {catalogue.error.message}
        </p>
      )}
      {!catalogue.data && !catalogue.error && <p className="note">Loading rules…</p>}
      {catalogue.data?.length === 0 && <p className="note">No rule files available in rules/.</p>}
      {catalogue.data && (
        <RuleChoices rules={catalogue.data} selected={selected} onChange={onChange} />
      )}
      <LegacyNotice legacyFiles={legacyFiles} hasInlineRules={hasInlineRules} />
    </fieldset>
  );
}
