import type { StartRunInput, Task, TaskFilter } from '../../types/task';
import type { Workflow } from '../../types/workflow';
import { api } from '../api';

export const listTasks = (filter?: TaskFilter): Promise<Task[]> => api.listTasks(filter);

/** Create a task by starting its workflow run; resolves to the workflow. */
export const createTask = (input: StartRunInput): Promise<Workflow> => api.startRun(input);

export async function getTaskDetail(taskId: string) {
  const [task, events, workflows] = await Promise.all([api.getTask(taskId), api.listActivity({ taskId }), api.listWorkflows()]);
  return { task, events, workflow: workflows.find((w) => w.taskId === taskId) };
}
