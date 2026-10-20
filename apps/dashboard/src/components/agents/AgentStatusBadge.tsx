import type { AgentStatus } from '../../types/agent';
import { Badge, type Tone } from '../common/Badge';

const MAP: Record<AgentStatus, [Tone, string, string]> = {
  ONLINE: ['ok', '●', 'Online'],
  BUSY: ['info', '◐', 'Busy'],
  IDLE: ['neutral', '○', 'Idle'],
  WAITING: ['warn', '◔', 'Waiting'],
  ERROR: ['danger', '▲', 'Error'],
  DISABLED: ['muted', '⊘', 'Disabled'],
  OFFLINE: ['muted', '◌', 'Offline'],
};

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  const [tone, icon, label] = MAP[status];
  return (
    <Badge tone={tone} icon={icon}>
      {label}
    </Badge>
  );
}
