import { useState } from 'react';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { SkillDetailDrawer } from '../../components/skills/SkillDetailDrawer';
import { SkillList } from '../../components/skills/SkillList';
import { useProjects } from '../../features/project-management';
import { useSkills } from '../../features/skill-catalogue';
import { skillsForProject } from '../../lib/skillFilter';
import type { Project } from '../../types/project';
import type { Skill } from '../../types/skill';

const ALL = 'all';

function ProjectFilter({
  projects,
  value,
  onChange,
}: {
  projects: Project[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field inline">
      <span>Project</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value={ALL}>All projects</option>
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function SkillCatalogue({
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
    <Card
      title="Skill catalogue"
      subtitle={
        project
          ? `${skillsForProject(skills, project).length} of ${skills.length} enabled by ${project.name}`
          : `${skills.length} total`
      }
    >
      <SkillList
        skills={skillsForProject(skills, project)}
        projects={projects}
        project={project}
        onOpen={onOpen}
      />
    </Card>
  );
}

function useSkillBrowser(skills: Skill[], projects: Project[]) {
  const [projectId, setProjectId] = useState(ALL);
  const [openId, setOpenId] = useState<string | null>(null);
  return {
    projectId,
    setProjectId,
    project: projects.find((entry) => entry.id === projectId),
    open: skills.find((skill) => skill.id === openId),
    setOpenId,
  };
}

export function SkillsPage() {
  const skills = useSkills();
  const projects = useProjects();
  const list = skills.data ?? [];
  const projectList = projects.data ?? [];
  const { projectId, setProjectId, project, open, setOpenId } = useSkillBrowser(list, projectList);

  return (
    <>
      <PageHeader
        title="Skill"
        subtitle="Project skills the platform appends to agent prompts — one folder per skill under skills/."
        actions={<ProjectFilter projects={projectList} value={projectId} onChange={setProjectId} />}
      />
      <AsyncView {...skills}>
        {(data) => (
          <SkillCatalogue
            skills={data}
            projects={projectList}
            project={project}
            onOpen={setOpenId}
          />
        )}
      </AsyncView>
      {open && (
        <SkillDetailDrawer skill={open} projects={projectList} onClose={() => setOpenId(null)} />
      )}
    </>
  );
}
