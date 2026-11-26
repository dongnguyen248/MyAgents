import { workflowStatusBadge } from '../../lib/workflowStatus';
import type { WorkflowStatus } from '../../types/workflow';
import { Badge } from '../common/Badge';

export function WorkflowStatusBadge({ status }: { status: WorkflowStatus }) {
  const badge = workflowStatusBadge(status);
  return (
    <Badge tone={badge.tone} icon={badge.icon}>
      {badge.label}
    </Badge>
  );
}
