import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAsync } from '../../hooks/useAsync';
import { messageOf } from '../../lib/message';
import { api, backendBaseUrl } from '../../services/api';
import type { Agent } from '../../types/agent';
import type { Skill } from '../../types/skill';

function useSkillForm(agent: Agent, initial: string[], skills: Skill[]) {
  const [selected, setSelected] = useState(() =>
    initial.filter((id) => skills.some((skill) => skill.id === id)),
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
      setSelected(await api.saveAgentSkills(agent.id, selected));
      setStatus('Saved for new runs.');
    } catch (error) {
      setStatus(`Could not save: ${messageOf(error)}`);
    } finally {
      setBusy(false);
    }
  }
  return { selected, busy, status, toggle, save };
}

type ChoicesProps = {
  agent: Agent;
  skills: Skill[];
  selected: string[];
  toggle: (id: string) => void;
};
function SkillChoices({ agent, skills, selected, toggle }: ChoicesProps) {
  return (
    <div className="agent-skill-choices">
      {skills.map((skill) => (
        <SkillChoice
          key={skill.id}
          agent={agent}
          skill={skill}
          selected={selected.includes(skill.id)}
          onToggle={() => toggle(skill.id)}
        />
      ))}
    </div>
  );
}

function SkillChoice({
  agent,
  skill,
  selected,
  onToggle,
}: {
  agent: Agent;
  skill: Skill;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <label className="agent-skill-option">
      <input type="checkbox" checked={selected} onChange={onToggle} />
      <span>
        <strong>{skill.name}</strong>
        <small>{skill.description}</small>
        {!skill.digest && ['spec', 'plan', 'task'].includes(agent.type) && (
          <small>No digest: omitted from design-agent prompts.</small>
        )}
      </span>
    </label>
  );
}

function SkillHelp() {
  return (
    <p className="note">
      Manage skill files in the <Link to="/skills">skill library</Link> and enable them in project
      settings.
    </p>
  );
}

type SkillFormProps = { agent: Agent; skills: Skill[]; initial: string[] };
function SkillForm({ agent, skills, initial }: SkillFormProps) {
  const { selected, busy, status, toggle, save } = useSkillForm(agent, initial, skills);
  return (
    <div className="stack-sm">
      <p className="note">
        Select skills for this agent. A project must also enable the skill. Stack restrictions and
        design-agent digests still apply.
      </p>
      <SkillChoices agent={agent} skills={skills} selected={selected} toggle={toggle} />
      {initial.some((id) => !skills.some((skill) => skill.id === id)) && (
        <p className="note">
          Some previously selected skills are missing from the catalogue. Saving removes those
          missing selections.
        </p>
      )}
      {!backendBaseUrl && <p className="note">Demo mode: changes last only for this session.</p>}
      <button className="btn btn-primary" disabled={busy} onClick={() => void save()}>
        {busy ? 'Saving…' : 'Save skills'}
      </button>
      {status && (
        <p role="status" className="note">
          {status}
        </p>
      )}
      <SkillHelp />
    </div>
  );
}

export function AgentSkillPicker({ agent }: { agent: Agent }) {
  const data = useAsync(
    () => Promise.all([api.listSkills(), api.getAgentSkills(agent.id)]),
    [agent.id],
  );
  if (agent.type === 'test') {
    return (
      <p className="note">The Test agent does not use model prompts, so skills are not injected.</p>
    );
  }
  if (agent.custom || agent.id !== `agent-${agent.type}`) {
    return <p className="note">Skill assignment is not supported for this agent.</p>;
  }
  if (data.error) {
    return (
      <p className="alert" role="alert">
        Cannot load skills: {data.error.message}
      </p>
    );
  }
  if (!data.data) {
    return <p className="note">Loading skills…</p>;
  }
  return <SkillForm agent={agent} skills={data.data[0]} initial={data.data[1]} />;
}
