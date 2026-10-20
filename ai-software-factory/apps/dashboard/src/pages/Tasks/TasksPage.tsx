import { useState } from 'react';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { TaskFilters } from '../../components/tasks/TaskFilters';
import { TaskTable } from '../../components/tasks/TaskTable';
import { useAgents } from '../../features/agent-management';
import { useProjects } from '../../features/project-management';
import { useTasks } from '../../features/task-monitoring';
import type { TaskFilter } from '../../types/task';

export function TasksPage() {
  const [filter, setFilter] = useState<TaskFilter>({});
  const tasks = useTasks(filter);
  const agents = useAgents();
  const projects = useProjects();
  const names = Object.fromEntries((agents.data ?? []).map((a) => [a.id, a.name]));

  return (
    <>
      <PageHeader title="Tasks" subtitle="Every work item across all projects and workflows." />
      <Card>
        <TaskFilters filter={filter} onChange={setFilter} projects={projects.data ?? []} agents={agents.data ?? []} />
      </Card>
      <Card title={tasks.data ? `${tasks.data.length} tasks` : 'Tasks'} flush>
        <AsyncView {...tasks}>{(list) => <TaskTable tasks={list} agentNames={names} />}</AsyncView>
      </Card>
    </>
  );
}
