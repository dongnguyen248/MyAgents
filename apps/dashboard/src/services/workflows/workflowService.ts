import { api } from '../api';

export const listWorkflows = () => api.listWorkflows();

/** Advance a run by one engine step; resolves to the updated workflow. */
export const tickWorkflow = (id: string) => api.tickRun(id);

export async function getWorkflowDetail(id: string) {
  const workflow = await api.getWorkflow(id);
  const events = workflow ? await api.listActivity({ taskId: workflow.taskId }) : [];
  return { workflow, events };
}
