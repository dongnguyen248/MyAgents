import { useState } from 'react';
import { AsyncView } from '../../components/common/AsyncView';
import { PageHeader } from '../../components/common/Layout';
import { ProjectCard } from '../../components/projects/ProjectCard';
import { ProjectForm } from '../../components/projects/ProjectForm';
import { createProject, deleteProject, updateProject, useProjects } from '../../features/project-management';
import type { Project, ProjectProfileInput } from '../../types/project';

const toInput = (p: Project): ProjectProfileInput => ({
  id: p.id,
  name: p.name,
  description: p.description,
  repository: { provider: p.repositoryProvider.toLowerCase(), path: p.repositoryPath, url: p.repositoryUrl },
  technology: {
    backend: p.technologyGroups.backend ?? [],
    frontend: p.technologyGroups.frontend ?? [],
  },
  workflow: p.workflow || 'software-development',
  enabledSkills: p.enabledSkills,
  configuration: {
    ...(p.approvalChannel ? { approval: { channel: p.approvalChannel } } : {}),
    ...(p.testCommands.length ? { testCommands: p.testCommands } : {}),
  },
  hostingTokenConfigured: p.hostingTokenConfigured,
  hostingTokenHint: p.hostingTokenHint,
});

export function ProjectsPage() {
  const projects = useProjects();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);

  const handleCreate = async (input: ProjectProfileInput) => {
    await createProject(input);
    setShowForm(false);
    projects.reload();
  };

  const handleUpdate = async (input: ProjectProfileInput) => {
    if (!editing) {return;}
    await updateProject(editing.id, input);
    setEditing(null);
    projects.reload();
  };

  const handleDelete = async (project: Project) => {
    await deleteProject(project.id);
    projects.reload();
  };

  const formOpen = showForm || editing !== null;

  return (
    <>
      <PageHeader
        title="Projects"
        subtitle="Each project is a profile; agents and workflows are shared."
        actions={
          !formOpen ? (
            <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
              New project
            </button>
          ) : undefined
        }
      />
      {showForm && <ProjectForm onCreate={handleCreate} onCancel={() => setShowForm(false)} />}
      {editing && (
        <ProjectForm
          key={editing.id}
          title={`Edit project · ${editing.id}`}
          submitLabel="Save changes"
          initial={toInput(editing)}
          onCreate={handleUpdate}
          onCancel={() => setEditing(null)}
        />
      )}
      <AsyncView {...projects}>
        {(list) => (
          <div className="grid grid-cards">
            {list.map((p) => (
              <ProjectCard key={p.id} project={p} onEdit={setEditing} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </AsyncView>
    </>
  );
}
