import { Link } from 'react-router-dom';
import { useEscape } from '../../hooks/useEscape';
import { agentMeta } from '../../lib/agentCatalog';
import { projectsEnabling } from '../../lib/skillFilter';
import type { AgentType } from '../../types/agent';
import type { Project } from '../../types/project';
import type { Skill } from '../../types/skill';
import { Badge } from '../common/Badge';
import { Icon } from '../common/Icon';

function AppliesToSection({ appliesTo }: { appliesTo: AgentType[] }) {
  return (
    <section>
      <h3 className="section-title">Injected into</h3>
      <ul className="pill-list">
        {appliesTo.map((type) => (
          <li key={type} className="chip">
            <Icon name="bot" className="icon-sm" />
            {agentMeta(type).label}
          </li>
        ))}
      </ul>
      <p className="note">
        Appended to the system prompt of these agents on runs whose project enables the skill.
      </p>
    </section>
  );
}

function EnabledBySection({ skill, projects }: { skill: Skill; projects: Project[] }) {
  const enabledBy = projectsEnabling(skill, projects);
  return (
    <section>
      <h3 className="section-title">Enabled by</h3>
      {enabledBy.length === 0 ? (
        <p className="note">No project enables this skill yet.</p>
      ) : (
        <ul className="list-rows">
          {enabledBy.map((project) => (
            <li key={project.id} className="list-row">
              <Icon name="folder" className="icon-sm" />
              <Link to="/projects">{project.name}</Link>
            </li>
          ))}
        </ul>
      )}
      {skill.stackOnly && (
        <p className="note">
          Stack skill: it only reaches an enabled project whose technology matches this stack.
        </p>
      )}
    </section>
  );
}

function DrawerSections({ skill, projects }: { skill: Skill; projects: Project[] }) {
  return (
    <>
      {skill.digest && (
        <section>
          <h3 className="section-title">Digest</h3>
          <p className="note">{skill.digest}</p>
        </section>
      )}
      <AppliesToSection appliesTo={skill.appliesTo} />
      <EnabledBySection skill={skill} projects={projects} />
      <section>
        <h3 className="section-title">Definition</h3>
        <p className="note">
          <span className="mono">{skill.path}</span> — editing it changes agent behaviour on the
          next run.
        </p>
      </section>
    </>
  );
}

function Backdrop({ onClose }: { onClose: () => void }) {
  return (
    <button type="button" className="drawer-backdrop" aria-label="Close skill" onClick={onClose} />
  );
}

function Head({ skill }: { skill: Skill }) {
  return (
    <div className="drawer-head">
      <h2 className="drawer-title">
        <span className="mono">{skill.name}</span>
        {skill.stackOnly && (
          <Badge tone="info" icon="◈" small>
            stack
          </Badge>
        )}
      </h2>
      <p className="drawer-desc">{skill.description}</p>
    </div>
  );
}

/** Skill detail: where it is injected, who enables it, and where it is defined. */
export function SkillDetailDrawer({
  skill,
  projects,
  onClose,
}: {
  skill: Skill;
  projects: Project[];
  onClose: () => void;
}) {
  useEscape(onClose);
  return (
    <>
      <Backdrop onClose={onClose} />
      <div className="drawer" role="dialog" aria-modal="true" aria-label={`${skill.name} skill`}>
        <Head skill={skill} />
        <div className="drawer-body">
          <DrawerSections skill={skill} projects={projects} />
        </div>
        <div className="drawer-foot">
          <span className="spacer" />
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </>
  );
}
