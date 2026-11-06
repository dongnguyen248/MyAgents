import type { ReactNode } from 'react';
import type { CiStatus } from '../../types/task';

export type Tone = 'ok' | 'info' | 'warn' | 'danger' | 'neutral' | 'muted';

/** Status pill. Always pairs a shape glyph with a text label so colour is never the only signal. */
export function Badge({ tone, icon, children }: { tone: Tone; icon: string; children: ReactNode }) {
  return (
    <span className={`badge badge-${tone}`}>
      <span aria-hidden="true">{icon}</span>
      {children}
    </span>
  );
}

const CI: Record<CiStatus, [Tone, string, string]> = {
  PASS: ['ok', '✓', 'Pass'],
  FAIL: ['danger', '✕', 'Fail'],
  RUNNING: ['info', '◐', 'Running'],
  UNKNOWN: ['muted', '–', 'Unknown'],
};

export function CiBadge({ status }: { status?: CiStatus }) {
  if (!status) {return <span className="muted">–</span>;}
  const [tone, icon, label] = CI[status];
  return (
    <Badge tone={tone} icon={icon}>
      CI {label}
    </Badge>
  );
}
