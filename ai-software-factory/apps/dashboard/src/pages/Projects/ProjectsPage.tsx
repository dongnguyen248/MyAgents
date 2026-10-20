import { AsyncView } from '../../components/common/AsyncView';
import { PageHeader } from '../../components/common/Layout';
import { ProjectCard } from '../../components/projects/ProjectCard';
import { useProjects } from '../../features/project-management';

export function ProjectsPage() {
  const projects = useProjects();
  return (
    <>
      <PageHeader title="Projects" subtitle="Each project is a profile; agents and workflows are shared." />
      <AsyncView {...projects}>
        {(list) => <div className="grid grid-cards">{list.map((p) => <ProjectCard key={p.id} project={p} />)}</div>}
      </AsyncView>
    </>
  );
}
