import type { WorkflowStatus } from '../../types/workflow';
import { titleCase } from '../../utils/format';
import { Badge, type Tone } from '../common/Badge';

const MAP: Record<WorkflowStatus, [Tone, string]> = {
  RUNNING: ['info', '◐'],
  AI_REVIEWING: ['info', '◐'],
  WAITING_APPROVAL: ['warn', '◔'],
  WAITING_RETRY: ['warn', '◔'],
  ESCALATED: ['danger', '⚠'],
  PAUSED: ['warn', '❚❚'],
  COMPLETED: ['ok', '✓'],
  FAILED: ['danger', '✕'],
  CANCELLED: ['muted', '⊘'],
};

export function WorkflowStatusBadge({ status }: { status: WorkflowStatus }) {
  const [tone, icon] = MAP[status];
  return <Badge tone={tone} icon={icon}>{titleCase(status)}</Badge>;
}
