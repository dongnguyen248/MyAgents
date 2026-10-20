import type { ApprovalDecisionInput } from '../../types/approval';
import { api } from '../api';

export const listApprovals = () => api.listApprovals();
export const decide = (id: string, input: ApprovalDecisionInput) => api.decideApproval(id, input);
