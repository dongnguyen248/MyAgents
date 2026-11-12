// The run page's "Now" card, as pure functions of the workflow
// view's currentActivity: which segments line 1 shows, whether the
// attempt may appear, the last-activity line, and the quiet hint.
// Kept out of the component so node tests can pin every rule
// without a DOM. The backend derives the fields (Stage 1); payloads
// from before it simply omit them, and every rule here degrades to
// the kind-based text the old band showed.
import type { WorkflowCurrentActivity, WorkflowWaiting } from '../types/workflow';

// No value imports from src/utils: the node test runner resolves
// imports literally, so a tested lib module must stay self-contained
// (type-only imports are erased and safe). gapText below therefore
// mirrors utils/format's duration() buckets instead of importing it.

const MS_PER_SECOND = 1000;
const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;
const JUST_NOW_SECONDS = 10;
const QUIET_MINUTES = 5;

/** Quiet gap after which a working step earns the neutral hint. */
export const NOW_QUIET_HINT_MS = QUIET_MINUTES * SECONDS_PER_MINUTE * MS_PER_SECOND;

/** Tooltip for the model segment: the name is a live setting. */
export const MODEL_SEGMENT_TITLE = 'Model currently configured for this agent (read at view time)';

const PHASE_LABELS: Record<string, string> = {
  PRODUCING: 'Working',
  AI_REVIEWING: 'AI reviewing',
  WAITING_FOR_APPROVAL: 'Waiting for approval',
  RETRYING: 'Waiting to retry',
  RUNNING_TESTS: 'Running tests',
  FIXING: 'Fixing code',
  WAITING_ON_CI: 'Waiting on CI',
  WAITING_FOR_MERGE: 'Waiting for merge',
  ESCALATED: 'Escalated — needs operator',
  STALLED: 'Stalled',
  PAUSED: 'Paused by operator',
};

/** Phase implied by the kind alone, for payloads without `phase`. */
const KIND_PHASES: Record<string, string> = {
  AI_REVIEW: 'AI_REVIEWING',
  APPROVAL: 'WAITING_FOR_APPROVAL',
  RETRY_WAIT: 'RETRYING',
  ESCALATED: 'ESCALATED',
  STALLED: 'STALLED',
  PAUSED: 'PAUSED',
};

/** The phases whose attempt counter may show (and that can go quiet). */
const ATTEMPT_PHASES = new Set([
  'PRODUCING',
  'AI_REVIEWING',
  'FIXING',
  'RETRYING',
  'WAITING_ON_CI',
]);

/** Phases whose label leads the line when no agent is acting. */
const LEAD_PHASES = new Set(['WAITING_FOR_APPROVAL', 'RETRYING', 'ESCALATED', 'STALLED', 'PAUSED']);

/** Phases the activity reason belongs to (the waits and stops). */
const REASON_PHASES = new Set(['WAITING_FOR_APPROVAL', 'ESCALATED', 'STALLED', 'PAUSED']);

export function effectivePhase(activity: WorkflowCurrentActivity): string | null {
  return activity.phase ?? KIND_PHASES[activity.kind] ?? null;
}

export function phaseLabel(phase: string | null): string | null {
  return phase ? (PHASE_LABELS[phase] ?? null) : null;
}

export function showsAttempt(activity: WorkflowCurrentActivity): boolean {
  const phase = effectivePhase(activity);
  return (
    phase !== null &&
    ATTEMPT_PHASES.has(phase) &&
    activity.attempt != null &&
    activity.attemptMax != null
  );
}

export interface NowSegment {
  text: string;
  strong?: boolean;
  title?: string;
}

/** The bold lead segment: the agent, else a wait/stop phase, else the step. */
function leadSegment(
  activity: WorkflowCurrentActivity,
  phase: string | null,
  label: string | null,
): { segment: NowSegment | null; phaseLed: boolean } {
  if (activity.agentName) {
    return { segment: { text: activity.agentName, strong: true }, phaseLed: false };
  }
  if (phase && LEAD_PHASES.has(phase) && label) {
    return { segment: { text: label, strong: true }, phaseLed: true };
  }
  if (activity.stepLabel) {
    return { segment: { text: activity.stepLabel, strong: true }, phaseLed: false };
  }
  return { segment: null, phaseLed: false };
}

/** The trailing reason and escalation-budget segments, when they apply. */
function tailSegments(
  activity: WorkflowCurrentActivity,
  phase: string | null,
  waiting?: WorkflowWaiting | null,
): NowSegment[] {
  const segments: NowSegment[] = [];
  if (phase && REASON_PHASES.has(phase) && activity.reason) {
    segments.push({ text: activity.reason });
  }
  if (phase === 'ESCALATED' && waiting?.budget) {
    segments.push({ text: `fix budget ${waiting.budget.used}/${waiting.budget.max}` });
  }
  return segments;
}

/** The phase label as a plain segment, when it did not lead the line. */
function phaseSegment(
  activity: WorkflowCurrentActivity,
  label: string | null,
  phaseLed: boolean,
): NowSegment | null {
  if (label && !phaseLed && (activity.agentName || activity.stepLabel)) {
    return { text: label };
  }
  return null;
}

/** Line 1 of the card, as ordered segments (the component joins them). */
export function nowSegments(
  activity: WorkflowCurrentActivity,
  waiting?: WorkflowWaiting | null,
): NowSegment[] {
  const phase = effectivePhase(activity);
  const label = phaseLabel(phase);
  const lead = leadSegment(activity, phase, label);
  const segments: NowSegment[] = lead.segment ? [lead.segment] : [];
  if (activity.model) {
    segments.push({ text: activity.model, title: MODEL_SEGMENT_TITLE });
  }
  const phaseSeg = phaseSegment(activity, label, lead.phaseLed);
  if (phaseSeg) {
    segments.push(phaseSeg);
  }
  if (phase === 'RETRYING' && activity.stepLabel && !activity.agentName) {
    segments.push({ text: activity.stepLabel });
  }
  if (showsAttempt(activity)) {
    segments.push({ text: `attempt ${activity.attempt} of ${activity.attemptMax}` });
  }
  return [...segments, ...tailSegments(activity, phase, waiting)];
}

/** "just now" / "42s ago" / "3 min ago" / "2h ago" / "1d ago". */
export function relativeTime(iso: string, nowMs: number): string {
  const seconds = Math.max(0, Math.floor((nowMs - new Date(iso).getTime()) / MS_PER_SECOND));
  if (seconds < JUST_NOW_SECONDS) {
    return 'just now';
  }
  if (seconds < SECONDS_PER_MINUTE) {
    return `${seconds}s ago`;
  }
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  if (minutes < MINUTES_PER_HOUR) {
    return `${minutes} min ago`;
  }
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  if (hours < HOURS_PER_DAY) {
    return `${hours}h ago`;
  }
  return `${Math.floor(hours / HOURS_PER_DAY)}d ago`;
}

/** Line 2: the newest event's text with its relative time. */
export function lastActivityLine(activity: WorkflowCurrentActivity, nowMs: number): string | null {
  const events = activity.recentEvents;
  if (!events?.length) {
    return null;
  }
  const last = events[events.length - 1];
  return `${last.message} · ${relativeTime(last.at, nowMs)}`;
}

/**
 * The neutral "no activity" hint: working phases only, measured
 * from the last event (or the step's start when there are none),
 * and never when the backend already calls the run STALLED.
 */
export function quietHint(activity: WorkflowCurrentActivity, nowMs: number): string | null {
  const phase = effectivePhase(activity);
  if (!phase || !ATTEMPT_PHASES.has(phase)) {
    return null;
  }
  const basis = activity.lastEventAt ?? activity.since;
  const gapMs = nowMs - new Date(basis).getTime();
  if (gapMs < NOW_QUIET_HINT_MS) {
    return null;
  }
  return `No activity for ${gapText(gapMs)} — long model calls can take a while.`;
}

/** "5m 00s" / "2h 5m" — the app's duration buckets, for the hint. */
function gapText(gapMs: number): string {
  const secondsPerHour = SECONDS_PER_MINUTE * MINUTES_PER_HOUR;
  const seconds = Math.max(0, Math.round(gapMs / MS_PER_SECOND));
  const hours = Math.floor(seconds / secondsPerHour);
  const minutes = Math.floor((seconds % secondsPerHour) / SECONDS_PER_MINUTE);
  if (hours) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m ${String(seconds % SECONDS_PER_MINUTE).padStart(2, '0')}s`;
}
