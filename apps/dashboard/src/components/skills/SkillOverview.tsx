import { Link } from 'react-router-dom';
import { agentMeta } from '../../lib/agentCatalog';
import { projectsEnabling } from '../../lib/skillFilter';
import type { Project } from '../../types/project';
import type { Skill } from '../../types/skill';

function ProjectDetails({ skill, projects }: { skill: Skill; projects?: Project[] }) {
  if (!projects) {
    return <p className="note">Project settings unavailable.</p>;
  }
  const enabled = projectsEnabling(skill, projects);
  if (!enabled.length) {
    return <p className="note">No project enables this skill yet.</p>;
  }
  return (
    <div className="skill-tags">
      {enabled.map((project) => (
        <Link className="chip" to="/projects" key={project.id}>
          {project.name}
        </Link>
      ))}
    </div>
  );
}

function AgentDetails({ skill }: { skill: Skill }) {
  return (
    <section className="skill-detail-card">
      <h3>Agent applicability</h3>
      {skill.appliesTo.length ? (
        <div className="skill-tags">
          {skill.appliesTo.map((agent) => (
            <span className="chip" key={agent}>
              {agentMeta(agent).label}
            </span>
          ))}
        </div>
      ) : (
        <p className="note">
          No agents are mapped to this skill. Enabling it in a project alone will not inject it into
          prompts.
        </p>
      )}
      {skill.stackOnly && (
        <p className="note">This skill also requires a matching project technology stack.</p>
      )}
    </section>
  );
}

function SkillDetails({ skill, projects }: { skill: Skill; projects?: Project[] }) {
  return (
    <div className="skill-overview">
      <span className="skill-eyebrow">SKILL DETAILS</span>
      <h2>{skill.name}</h2>
      <p className="skill-description">{skill.description}</p>
      <div className="skill-detail-grid">
        <AgentDetails skill={skill} />
        <section className="skill-detail-card">
          <h3>Enabled by projects</h3>
          <ProjectDetails skill={skill} projects={projects} />
        </section>
      </div>
      {skill.digest && (
        <section className="skill-detail-card">
          <h3>Digest</h3>
          <p className="note">{skill.digest}</p>
        </section>
      )}
      <section className="skill-detail-card">
        <h3>Definition</h3>
        <p className="note mono">{skill.path}</p>
        <p className="note">Expand the folder on the left to view and edit its files.</p>
      </section>
    </div>
  );
}

function LibraryStats({ skills, projects }: { skills: Skill[]; projects?: Project[] }) {
  const mapped = skills.filter((skill) => skill.appliesTo.length > 0).length;
  const enabled = projects
    ? skills.filter((skill) => projectsEnabling(skill, projects).length > 0).length
    : '—';
  return (
    <div className="skill-stats">
      <div>
        <strong>{skills.length}</strong>
        <span>Total skills</span>
        <small>in the catalogue</small>
      </div>
      <div>
        <strong>{mapped}</strong>
        <span>Mapped skills</span>
        <small>available to agents</small>
      </div>
      <div>
        <strong>{enabled}</strong>
        <span>Enabled skills</span>
        <small>across projects</small>
      </div>
    </div>
  );
}

function GettingStarted() {
  return (
    <section className="skill-detail-card">
      <h3>Getting started</h3>
      <p className="note">
        Select a skill in the library to inspect its configuration. Project settings control which
        mapped skills are included in future runs.
      </p>
    </section>
  );
}

export function SkillOverview({
  skills,
  projects,
  selected,
}: {
  skills: Skill[];
  projects?: Project[];
  selected?: Skill;
}) {
  if (selected) {
    return <SkillDetails skill={selected} projects={projects} />;
  }
  return (
    <div className="skill-overview">
      <span className="skill-eyebrow">YOUR LIBRARY</span>
      <h2>Skill library overview</h2>
      <p className="skill-description">
        Browse the skills available to your agents. Select a folder to see its details or open a
        file to edit it.
      </p>
      <LibraryStats skills={skills} projects={projects} />
      <GettingStarted />
    </div>
  );
}
