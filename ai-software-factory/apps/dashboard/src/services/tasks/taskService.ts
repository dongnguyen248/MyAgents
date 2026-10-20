import type { Task, TaskFilter } from '../../types/task';
import { api } from '../api';

export const listTasks = (filter?: TaskFilter): Promise<Task[]> => api.listTasks(filter);

export async function getTaskDetail(taskId: string) {
  const [task, events, workflows] = await Promise.all([api.getTask(taskId), api.listActivity({ taskId }), api.listWorkflows()]);
  return { task, events, workflow: workflows.find((w) => w.taskId === taskId) };
}
