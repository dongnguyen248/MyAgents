import type { Project } from '../../types/project';
import { projectsEnabling } from '../../lib/skillFilter';
import type { Skill } from '../../types/skill';

interface RowProps {
  skill: Skill;
  project?: Project;
  enabledCount: number;
  onOpen: () => void;
}

function SkillRow({ skill, project, enabledCount, onOpen }: RowProps) {
  const enabled = project ? project.enabledSkills.includes(skill.id) : undefined;
  return (
    <button type="button" className="skill-row" onClick={onOpen}>
      <span className="skill-row-main">
        <span className="skill-row-name">{skill.name}</span>
        <span className="skill-row-desc">{skill.description}</span>
      </span>
      <span className="skill-row-meta">
        {enabled === true && (
          <span className="badge badge-ok badge-sm">
            <span aria-hidden="true">✓</span> enabled
          </span>
        )}
        {enabled === false && <span className="chip">not enabled</span>}
        <span className="chip">{skill.appliesTo.length} agents</span>
        {skill.stackOnly && <span className="chip">stack</span>}
        <span className="chip">{enabledCount} projects</span>
      </span>
    </button>
  );
}

/** Hairline list of the catalogue; the project filter narrows what is shown. */
export function SkillList({
  skills,
  projects,
  project,
  onOpen,
}: {
  skills: Skill[];
  projects: Project[];
  project?: Project;
  onOpen: (skillId: string) => void;
}) {
  return (
    <div className="skill-list">
      {skills.map((skill) => (
        <SkillRow
          key={skill.id}
          skill={skill}
          project={project}
          enabledCount={projectsEnabling(skill, projects).length}
          onOpen={() => onOpen(skill.id)}
        />
      ))}
      {skills.length === 0 && (
        <p className="empty muted">
          {project ? `${project.name} enables none of the catalogue’s skills.` : 'No skills found.'}
        </p>
      )}
    </div>
  );
}
