import { useAsync } from '../../hooks/useAsync';
import * as svc from '../../services/tasks/taskService';
import type { TaskFilter } from '../../types/task';

export const useTasks = (filter: TaskFilter) => useAsync(() => svc.listTasks(filter), [JSON.stringify(filter)]);
export const useTaskDetail = (id: string) => useAsync(() => svc.getTaskDetail(id), [id]);

export const createTask = svc.createTask;
