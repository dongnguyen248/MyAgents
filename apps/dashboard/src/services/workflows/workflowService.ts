import { api } from '../api';

export const listWorkflows = () => api.listWorkflows();

/** Advance a run by one engine step; resolves to the updated workflow. */
export const tickWorkflow = (id: string) => api.tickRun(id);

/** Start a fresh run of a finished run's task; resolves to the new workflow. */
export const retryWorkflow = (id: string) => api.retryRun(id);

/** Continue a failed run from its failed step; resolves to the new workflow. */
export const resumeWorkflow = (id: string) => api.resumeRun(id);

/** Cancel an active run; resolves to its (possibly still stopping) workflow. */
export const cancelWorkflow = (id: string) => api.cancelRun(id);

export async function getWorkflowDetail(id: string) {
  const workflow = await api.getWorkflow(id);
  const events = workflow ? await api.listActivity({ taskId: workflow.taskId }) : [];
  return { workflow, events };
}
