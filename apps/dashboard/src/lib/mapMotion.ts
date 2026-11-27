// Motion and geometry constants for the Live Map canvas.
//
// Durations and sizes live here so components carry no magic
// numbers and the motion budget is reviewable in one place. All
// motion is CSS/SMIL driven; nothing here schedules React renders.

export const MAX_PARTICLES = 12;
export const PULSE_DURATION = '0.65s';
export const TRAIL_DELAYS = ['-0.07s', '-0.14s'];
export const PULSE_RADIUS = 4;
export const TRAIL_RADIUS = 2.5;

export const TILE_SIZE = 34;
export const TILE_RADIUS = 9;
export const TILE_ACTIVE_SCALE = 1.08;
export const HALO_RADIUS = 26;
export const LABEL_OFFSET_Y = 30;
export const COUNT_OFFSET_Y = 44;
export const BADGE_OFFSET = 15;
export const BADGE_RADIUS = 8;
export const ERROR_RING_FROM = 20;
export const ERROR_RING_TO = 34;

export const CENTRE_RADIUS = 52;
export const RING_RADIUS = 44;
export const ORBIT_RADIUS = 30;
export const ORBIT_DOT_RADIUS = 4;
export const ORBIT_OFFSET_STEP = 60;
export const ORBIT_DURATION = '7s';
