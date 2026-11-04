import { useState } from 'react';
import { AsyncView } from '../../components/common/AsyncView';
import { PageHeader } from '../../components/common/Layout';
import { ProjectCard } from '../../components/projects/ProjectCard';
import { ProjectForm } from '../../components/projects/ProjectForm';
import { createProject, useProjects } from '../../features/project-management';
import type { ProjectProfileInput } from '../../types/project';

export function ProjectsPage() {
  const projects = useProjects();
  const [showForm, setShowForm] = useState(false);

  const handleCreate = async (input: ProjectProfileInput) => {
    await createProject(input);
    setShowForm(false);
    projects.reload();
  };

  return (
    <>
      <PageHeader
        title="Projects"
        subtitle="Each project is a profile; agents and workflows are shared."
        actions={
          !showForm ? (
            <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
              New project
            </button>
          ) : undefined
        }
      />
      {showForm && <ProjectForm onCreate={handleCreate} onCancel={() => setShowForm(false)} />}
      <AsyncView {...projects}>
        {(list) => (
          <div className="grid grid-cards">
            {list.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        )}
      </AsyncView>
    </>
  );
}
