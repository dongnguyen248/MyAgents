import { useState } from 'react';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { TaskFilters } from '../../components/tasks/TaskFilters';
import { TaskForm } from '../../components/tasks/TaskForm';
import { TaskTable } from '../../components/tasks/TaskTable';
import { useAgents } from '../../features/agent-management';
import { useProjects } from '../../features/project-management';
import { createTask, useTasks } from '../../features/task-monitoring';
import type { StartRunInput, TaskFilter } from '../../types/task';

export function TasksPage() {
  const [filter, setFilter] = useState<TaskFilter>({});
  const [showForm, setShowForm] = useState(false);
  const tasks = useTasks(filter);
  const agents = useAgents();
  const projects = useProjects();
  const names = Object.fromEntries((agents.data ?? []).map((a) => [a.id, a.name]));

  const handleCreate = async (input: StartRunInput) => {
    await createTask(input);
    setShowForm(false);
    tasks.reload();
  };

  return (
    <>
      <PageHeader
        title="Tasks"
        subtitle="Every work item across all projects and workflows."
        actions={
          !showForm ? (
            <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
              New task
            </button>
          ) : undefined
        }
      />
      {showForm && (
        <TaskForm projects={projects.data ?? []} onCreate={handleCreate} onCancel={() => setShowForm(false)} />
      )}
      <Card>
        <TaskFilters filter={filter} onChange={setFilter} projects={projects.data ?? []} agents={agents.data ?? []} />
      </Card>
      <Card title={tasks.data ? `${tasks.data.length} tasks` : 'Tasks'} flush>
        <AsyncView {...tasks}>{(list) => <TaskTable tasks={list} agentNames={names} />}</AsyncView>
      </Card>
    </>
  );
}
