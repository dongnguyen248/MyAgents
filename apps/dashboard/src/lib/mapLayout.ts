// Pure layout and presentation-state helpers for the Live Map canvas.
//
// Everything here is deterministic math over values the board already
// carries (station counts, budget percent, run status): no DOM, no
// network, no contract change. The canvas component only draws what
// these functions decide, so the decisions stay unit-testable.

export const VIEW_WIDTH = 640;
export const VIEW_HEIGHT = 560;
export const CENTER_X = 320;
export const CENTER_Y = 280;
export const RADIUS_X = 252;
export const RADIUS_Y = 208;

const TOP_ANGLE_DEG = -90;
const FULL_CIRCLE_DEG = 360;
const HALF_CIRCLE_DEG = 180;
const DEG_TO_RAD = Math.PI / HALF_CIRCLE_DEG;
const PERCENT_WHOLE = 100;
const BADGE_CAP = 99;

export interface MapPoint {
  x: number;
  y: number;
}

/** Station positions on an ellipse: first station at the top, then
 * evenly spaced clockwise. Works for any station count. */
export function stationPositions(count: number): MapPoint[] {
  if (count <= 0) {
    return [];
  }
  const step = FULL_CIRCLE_DEG / count;
  const points: MapPoint[] = [];
  for (let index = 0; index < count; index += 1) {
    const angle = (TOP_ANGLE_DEG + index * step) * DEG_TO_RAD;
    points.push({
      x: CENTER_X + RADIUS_X * Math.cos(angle),
      y: CENTER_Y + RADIUS_Y * Math.sin(angle),
    });
  }
  return points;
}

/** Budget gauge fill as a 0..1 fraction. Null when there is no
 * usable percent (no limit, or NaN): the ring then stays static. */
export function gaugeFraction(percent: number | null): number | null {
  if (percent === null || Number.isNaN(percent)) {
    return null;
  }
  const clamped = Math.min(PERCENT_WHOLE, Math.max(0, percent));
  return clamped / PERCENT_WHOLE;
}

export type StationLevel = 'idle' | 'active' | 'error';

export interface StationActivity {
  total: number;
  running: number;
  faults: number;
}

/** A station count with zeroes filled in, so renderers never
 * branch on a missing count. */
export function activityOf(count: StationActivity | undefined): StationActivity {
  return count ?? { total: 0, running: 0, faults: 0 };
}

/** Visual level of one hub from data the board already has: faults
 * win over activity, activity wins over idle. */
export function stationLevel(
  activity: StationActivity | undefined,
  hasPulse: boolean,
): StationLevel {
  if (activity !== undefined && activity.faults > 0) {
    return 'error';
  }
  if (hasPulse || (activity !== undefined && activity.running > 0)) {
    return 'active';
  }
  return 'idle';
}

/** Badge text for a count: hidden at zero, capped at "99+". */
export function formatBadge(count: number): string {
  if (count <= 0) {
    return '';
  }
  if (count > BADGE_CAP) {
    return `${BADGE_CAP}+`;
  }
  return `${count}`;
}

/** At most `max` travelling particles render at once; the newest
 * pulses win because callers append in arrival order. */
export function capPulses<T>(pulses: T[], max: number): T[] {
  if (max <= 0) {
    return [];
  }
  return pulses.slice(-max);
}

export type CentreTone = 'normal' | 'warn' | 'failed' | 'unknown' | 'done';

/** Centre ring tone from the run status string the page already
 * shows. The string itself is never changed, only the tone. */
export function centreTone(runStatus: string): CentreTone {
  if (runStatus === 'FAILED') {
    return 'failed';
  }
  if (runStatus === 'ESCALATED') {
    return 'warn';
  }
  if (runStatus === 'UNKNOWN') {
    return 'unknown';
  }
  if (runStatus === 'COMPLETED') {
    return 'done';
  }
  return 'normal';
}
