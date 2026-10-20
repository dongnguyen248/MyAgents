import { useAsync } from '../../hooks/useAsync';
import * as svc from '../../services/workflows/workflowService';

export const useWorkflows = () => useAsync(svc.listWorkflows);
export const useWorkflowDetail = (id: string) => useAsync(() => svc.getWorkflowDetail(id), [id]);
