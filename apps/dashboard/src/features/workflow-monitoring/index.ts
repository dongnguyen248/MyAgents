import { useAsync } from '../../hooks/useAsync';
import * as svc from '../../services/workflows/workflowService';

export const useWorkflows = () => useAsync(svc.listWorkflows);
export const useWorkflowDetail = (id: string) => useAsync(() => svc.getWorkflowDetail(id), [id]);

export const tickWorkflow = svc.tickWorkflow;
export const retryWorkflow = svc.retryWorkflow;
export const resumeWorkflow = svc.resumeWorkflow;
export const cancelWorkflow = svc.cancelWorkflow;
export const resumeEscalation = svc.resumeEscalation;
export const recoverWorkflow = svc.recoverWorkflow;
export const driveWorkflow = svc.driveWorkflow;
export const failWorkflow = svc.failWorkflow;
export const pauseWorkflow = svc.pauseWorkflow;
export const continueWorkflow = svc.continueWorkflow;
export { useRunLiveRefetch } from './useRunLiveRefetch';
