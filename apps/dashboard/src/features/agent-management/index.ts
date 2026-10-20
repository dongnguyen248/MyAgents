import { useAsync } from '../../hooks/useAsync';
import * as svc from '../../services/agents/agentService';

export const useAgents = () => useAsync(svc.listAgents);
export const useAgentDetail = (id: string) => useAsync(() => svc.getAgentDetail(id), [id]);
export const useAgentConfig = (id: string) => useAsync(() => svc.getAgentConfig(id), [id]);
export { attentionReason } from '../../services/agents/agentService';
