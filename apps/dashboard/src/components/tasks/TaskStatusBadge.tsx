import type { TaskStatus } from '../../types/task';
import { titleCase } from '../../utils/format';
import { Badge, type Tone } from '../common/Badge';

function describe(s: TaskStatus): [Tone, string] {
  if (s === 'COMPLETED') return ['ok', '✓'];
  if (s === 'FAILED' || s.endsWith('_REJECTED')) return ['danger', '✕'];
  if (s === 'CANCELLED') return ['muted', '⊘'];
  if (s.endsWith('_REVIEW') || s === 'READY_TO_MERGE') return ['warn', '◔'];
  if (s === 'NEW') return ['neutral', '○'];
  return ['info', '◐'];
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const [tone, icon] = describe(status);
  return (
    <Badge tone={tone} icon={icon}>
      {titleCase(status)}
    </Badge>
  );
}
