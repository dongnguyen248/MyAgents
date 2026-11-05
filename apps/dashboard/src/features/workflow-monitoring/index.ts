import { useAsync } from '../../hooks/useAsync';
import * as svc from '../../services/workflows/workflowService';

export const useWorkflows = () => useAsync(svc.listWorkflows);
export const useWorkflowDetail = (id: string) => useAsync(() => svc.getWorkflowDetail(id), [id]);

export const tickWorkflow = svc.tickWorkflow;
export const retryWorkflow = svc.retryWorkflow;
export const resumeWorkflow = svc.resumeWorkflow;
export const cancelWorkflow = svc.cancelWorkflow;
