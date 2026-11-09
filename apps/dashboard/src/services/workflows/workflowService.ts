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

/** Grant an escalated run a fresh fix budget; resolves to its workflow. */
export const resumeEscalation = (id: string, reason: string, guidance?: string) =>
  api.resumeEscalation(id, reason, guidance);

/** Approve an escalated gate's artifact anyway; resolves to its workflow. */
export const approveEscalation = (id: string, reason: string) => api.approveEscalation(id, reason);

/** Skip a no-tests run's test step (reason required); scope 'run' covers the rest of the run. */
export const skipTests = (id: string, reason: string, scope?: 'item' | 'run') =>
  api.skipTests(id, reason, scope);

/** Replace a no-tests run's test commands (run-scoped) and retest. */
export const replaceTestCommands = (id: string, commands: string[][], reason?: string) =>
  api.replaceTestCommands(id, commands, reason);

/** The run's AI review rounds per gated stage (Phase 12). */
export const getRunReviews = (id: string) => api.getRunReviews(id);

/** Recover an interrupted run (replay the step or fail the run). */
export const recoverWorkflow = (id: string, reason: string, retryInterrupted: boolean) =>
  api.recoverRun(id, reason, retryInterrupted);

/** (Re)start a run's background driver. */
export const driveWorkflow = (id: string) => api.driveRun(id);

/** Fail an escalated or stalled run under operator control. */
export const failWorkflow = (id: string, reason: string) => api.failRun(id, reason);

/** Pause a run at the next step boundary. */
export const pauseWorkflow = (id: string) => api.pauseRun(id);

/** Continue a paused run. */
export const continueWorkflow = (id: string) => api.continueRun(id);

export async function getWorkflowDetail(id: string) {
  const workflow = await api.getWorkflow(id);
  const events = workflow ? await api.listActivity({ taskId: workflow.taskId }) : [];
  return { workflow, events };
}
