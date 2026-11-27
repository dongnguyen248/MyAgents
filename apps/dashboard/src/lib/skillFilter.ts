import type { Project } from '../types/project';
import type { Skill } from '../types/skill';

/** Projects whose profile enables this skill. */
export function projectsEnabling(skill: Skill, projects: Project[]): Project[] {
  return projects.filter((project) => project.enabledSkills.includes(skill.id));
}

/** The skills one project enables; the whole catalogue when no project is chosen. */
export function skillsForProject(skills: Skill[], project?: Project): Skill[] {
  if (!project) {
    return skills;
  }
  return skills.filter((skill) => project.enabledSkills.includes(skill.id));
}
