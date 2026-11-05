import type { StartRunInput, Task, TaskFilter } from '../../types/task';
import type { Workflow } from '../../types/workflow';
import { api } from '../api';

export const listTasks = (filter?: TaskFilter): Promise<Task[]> => api.listTasks(filter);

/** Create a task by starting its workflow run; resolves to the workflow. */
export const createTask = (input: StartRunInput): Promise<Workflow> => api.startRun(input);

export async function getTaskDetail(taskId: string) {
  const [task, events, workflows] = await Promise.all([api.getTask(taskId), api.listActivity({ taskId }), api.listWorkflows()]);
  // Every run of this task, newest first; the page's workflow is the latest
  // run, and the rest form the run history (a task is one row everywhere
  // else, always reflecting its latest run). For an auto-split parent
  // task, its parts are separate runs pointing back via parentTaskId —
  // they belong on the parent's page as its parts.
  const runs = workflows
    .filter((w) => w.taskId === taskId || w.parentTaskId === taskId)
    .sort((a, b) => b.startedAt.localeCompare(a.startedAt));
  return { task, events, workflow: runs[0], runs };
}
