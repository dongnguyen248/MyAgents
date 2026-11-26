import type { Tone } from '../components/common/Badge.ts';
import type { WorkflowStatus } from '../types/workflow.ts';

/** Mirrors utils/format.titleCase so this module stays import-free
 * for the node test runner. */
function titleCase(value: string): string {
  return value
    .toLowerCase()
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export interface StatusBadge {
  tone: Tone;
  icon: string;
  label: string;
}

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
  UNKNOWN: ['warn', '?'],
};

/** Badge for any status string; unlisted values never throw. */
export function workflowStatusBadge(status: string): StatusBadge {
  const entry = MAP[status as WorkflowStatus] as [Tone, string] | undefined;
  if (entry === undefined) {
    return { tone: 'muted', icon: '?', label: titleCase(status) };
  }
  return { tone: entry[0], icon: entry[1], label: titleCase(status) };
}
