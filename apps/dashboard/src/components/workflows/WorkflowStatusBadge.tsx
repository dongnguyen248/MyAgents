import type { WorkflowStatus } from '../../types/workflow';
import { titleCase } from '../../utils/format';
import { Badge, type Tone } from '../common/Badge';

const MAP: Record<WorkflowStatus, [Tone, string]> = {
  RUNNING: ['info', '◐'],
  WAITING_APPROVAL: ['warn', '◔'],
  COMPLETED: ['ok', '✓'],
  FAILED: ['danger', '✕'],
  CANCELLED: ['muted', '⊘'],
};

export function WorkflowStatusBadge({ status }: { status: WorkflowStatus }) {
  const [tone, icon] = MAP[status];
  return <Badge tone={tone} icon={icon}>{titleCase(status)}</Badge>;
}
