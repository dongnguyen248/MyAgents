import { api } from '../api';

export const listWorkflows = () => api.listWorkflows();

export async function getWorkflowDetail(id: string) {
  const workflow = await api.getWorkflow(id);
  const events = workflow ? await api.listActivity({ taskId: workflow.taskId }) : [];
  return { workflow, events };
}
