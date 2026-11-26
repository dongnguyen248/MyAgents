import {
  isModelFlashing,
  runningAgents,
  spokeWidth,
  STATION_ORDER,
  stationCounts,
} from '../../lib/mapBoard';
import type { BoardState, RunningAgent, StationCount } from '../../lib/mapBoard';
import {
  activityOf,
  capPulses,
  centreTone,
  formatBadge,
  gaugeFraction,
  stationLevel,
  stationPositions,
  CENTER_X,
  CENTER_Y,
  VIEW_HEIGHT,
  VIEW_WIDTH,
} from '../../lib/mapLayout';
import type { CentreTone, MapPoint, StationLevel } from '../../lib/mapLayout';
import {
  BADGE_OFFSET,
  BADGE_RADIUS,
  CENTRE_RADIUS,
  COUNT_OFFSET_Y,
  ERROR_RING_FROM,
  ERROR_RING_TO,
  HALO_RADIUS,
  LABEL_OFFSET_Y,
  MAX_PARTICLES,
  ORBIT_DOT_RADIUS,
  ORBIT_DURATION,
  ORBIT_OFFSET_STEP,
  ORBIT_RADIUS,
  PULSE_DURATION,
  PULSE_RADIUS,
  RING_RADIUS,
  TILE_ACTIVE_SCALE,
  TILE_RADIUS,
  TILE_SIZE,
  TRAIL_DELAYS,
  TRAIL_RADIUS,
} from '../../lib/mapMotion';
import type { MapCounters, MapStationId } from '../../types/map';

export interface MapPulse {
  key: string;
  station: MapStationId;
  color: string;
  inbound: boolean;
}

const FULL_TURN = 360;
const TOP_ANGLE = -90;
const NO_ORBITS: RunningAgent[] = [];
const TITLE_OFFSET_Y = 14;
const BUDGET_OFFSET_Y = 6;
const CAPTION_OFFSET_Y = 22;
const STATUS_OFFSET_Y = 68;
const UNKNOWN_OFFSET_Y = 34;
const PERCENT_AMBER = 70;
const PERCENT_RED = 90;
const PERCENT_WHOLE = 100;

// Hand-drawn line icons, one path per station, drawn in a 24x24 box
// centred on the hub. Written for this map; no icon library is used.
const ICON_PATHS: Record<string, string> = {
  operator: 'M0 -7 a3.6 3.6 0 1 1 0.01 0 M-6.5 8 a6.5 5.2 0 0 1 13 0',
  model:
    'M-6 -6 h12 v12 h-12 z M-3 -3 h6 v6 h-6 z M-9 -3 h3 M-9 3 h3 M6 -3 h3 M6 3 h3 M-3 -9 v3 M3 -9 v3 M-3 6 v3 M3 6 v3',
  store:
    'M-7 -6 a7 3 0 1 0 14 0 a7 3 0 1 0 -14 0 M-7 -6 v12 a7 3 0 0 0 14 0 v-12 M-7 0 a7 3 0 0 0 14 0',
  files: 'M-5 -9 h7 l4 4 v14 h-11 z M2 -9 v4 h4',
  shell: 'M-9 -7 h18 v14 h-18 z M-5 -2 l4 3 l-4 3 M2 4 h5',
  network: 'M0 -9 a9 9 0 1 1 -0.01 0 M-9 0 h18 M0 -9 a13 13 0 0 1 0 18 M0 -9 a13 13 0 0 0 0 18',
  agents:
    'M-7 -6 a2.6 2.6 0 1 1 0.01 0 M7 -6 a2.6 2.6 0 1 1 0.01 0 M0 7 a2.6 2.6 0 1 1 0.01 0 M-5 -4 l3.5 8 M5 -4 l-3.5 8 M-4.4 -6 h8.8',
  skills: 'M2 -10 l-6 8 h4 l-2 8 l7 -9 h-4.5 z',
  gates:
    'M0 -9 l7 2.5 v5 a7 7 0 0 1 -7 7 a7 7 0 0 1 -7 -7 v-5 z M-2.5 0 a2.5 2.5 0 1 1 5 0 M0 2.5 v3',
};

function StationIcon({ stationId }: { stationId: MapStationId }) {
  return <path d={ICON_PATHS[stationId] ?? ''} className="lm-icon" />;
}

function StageDefs() {
  return (
    <defs>
      <radialGradient id="lm-vignette" cx="50%" cy="45%" r="75%">
        <stop offset="0%" stopColor="var(--lm-stage-2)" />
        <stop offset="100%" stopColor="var(--lm-stage)" />
      </radialGradient>
      <pattern id="lm-dots" width="26" height="26" patternUnits="userSpaceOnUse">
        <circle cx="1.5" cy="1.5" r="1.5" className="lm-stage-dot" />
      </pattern>
    </defs>
  );
}

function Stage() {
  return (
    <g>
      <StageDefs />
      <rect width={VIEW_WIDTH} height={VIEW_HEIGHT} fill="url(#lm-vignette)" />
      <rect width={VIEW_WIDTH} height={VIEW_HEIGHT} fill="url(#lm-dots)" />
    </g>
  );
}

function StationHalo({ point, level }: { point: MapPoint; level: StationLevel }) {
  if (level === 'idle') {
    return null;
  }
  return (
    <circle
      cx={point.x}
      cy={point.y}
      r={HALO_RADIUS}
      className={level === 'error' ? 'lm-halo lm-halo-error' : 'lm-halo'}
    />
  );
}

function ErrorRing({ point, faults }: { point: MapPoint; faults: number }) {
  if (faults === 0) {
    return null;
  }
  return (
    <circle key={faults} cx={point.x} cy={point.y} r={ERROR_RING_FROM} className="lm-error-ring">
      <animate
        attributeName="r"
        from={ERROR_RING_FROM}
        to={ERROR_RING_TO}
        dur="1.2s"
        fill="freeze"
      />
      <animate attributeName="opacity" from="0.7" to="0" dur="1.2s" fill="freeze" />
    </circle>
  );
}

function FaultBadge({ point, faults }: { point: MapPoint; faults: number }) {
  const text = formatBadge(faults);
  if (text === '') {
    return null;
  }
  return (
    <g>
      <circle
        cx={point.x - BADGE_OFFSET}
        cy={point.y - BADGE_OFFSET}
        r={BADGE_RADIUS}
        className="lm-fault-dot"
      />
      <text x={point.x - BADGE_OFFSET} y={point.y - BADGE_OFFSET} className="lm-fault-count">
        {text}
      </text>
    </g>
  );
}

function RunningBadge({ point, running }: { point: MapPoint; running: number }) {
  if (running <= 1) {
    return null;
  }
  return (
    <text x={point.x + BADGE_OFFSET} y={point.y - BADGE_OFFSET} className="lm-station-badge">
      ×{running}
    </text>
  );
}

function StationTile({
  point,
  stationId,
  level,
  flashing,
}: {
  point: MapPoint;
  stationId: MapStationId;
  level: StationLevel;
  flashing: boolean;
}) {
  const scale = level === 'active' ? TILE_ACTIVE_SCALE : 1;
  const transform = `translate(${point.x} ${point.y}) scale(${scale})`;
  const half = TILE_SIZE / 2;
  return (
    <g transform={transform} className={flashing ? 'lm-flash' : undefined}>
      <rect
        x={-half}
        y={-half}
        width={TILE_SIZE}
        height={TILE_SIZE}
        rx={TILE_RADIUS}
        className={`lm-tile lm-tile-${level}`}
      />
      <StationIcon stationId={stationId} />
    </g>
  );
}

function StationLabels({ point, label, total }: { point: MapPoint; label: string; total: number }) {
  return (
    <g>
      <text x={point.x} y={point.y + LABEL_OFFSET_Y} className="lm-station-label">
        {label}
      </text>
      <text x={point.x} y={point.y + COUNT_OFFSET_Y} className="lm-station-count">
        {total}
      </text>
    </g>
  );
}

function StationSpoke({
  point,
  level,
  total,
}: {
  point: MapPoint;
  level: StationLevel;
  total: number;
}) {
  return (
    <line
      x1={CENTER_X}
      y1={CENTER_Y}
      x2={point.x}
      y2={point.y}
      className={level === 'active' ? 'lm-spoke active' : 'lm-spoke'}
      strokeWidth={spokeWidth(total)}
    />
  );
}

function OrbitDot({ point, color, offset }: { point: MapPoint; color: string; offset: number }) {
  const centre = `${point.x} ${point.y}`;
  return (
    <g className="lm-orbit">
      <animateTransform
        attributeName="transform"
        type="rotate"
        from={`${offset} ${centre}`}
        to={`${offset + FULL_TURN} ${centre}`}
        dur={ORBIT_DURATION}
        repeatCount="indefinite"
      />
      <circle cx={point.x + ORBIT_RADIUS} cy={point.y} r={ORBIT_DOT_RADIUS} fill={color} />
    </g>
  );
}

function AgentOrbits({ point, agents }: { point: MapPoint; agents: RunningAgent[] }) {
  return (
    <g>
      {agents.map((agent, index) => (
        <OrbitDot
          key={agent.spanId}
          point={point}
          color={agent.color}
          offset={index * ORBIT_OFFSET_STEP}
        />
      ))}
    </g>
  );
}

interface StationNodeProps {
  stationId: MapStationId;
  label: string;
  point: MapPoint;
  count: StationCount | undefined;
  level: StationLevel;
  flashing: boolean;
  orbits: RunningAgent[];
}

function StationNode({
  stationId,
  label,
  point,
  count,
  level,
  flashing,
  orbits,
}: StationNodeProps) {
  const activity = activityOf(count);
  const summary = `${label}: ${activity.total} events, ${activity.running} running, ${activity.faults} faults`;
  return (
    <g tabIndex={0} role="img" aria-label={summary} className="lm-hub">
      <title>{summary}</title>
      <StationSpoke point={point} level={level} total={activity.total} />
      <StationHalo point={point} level={level} />
      <ErrorRing point={point} faults={activity.faults} />
      <StationTile point={point} stationId={stationId} level={level} flashing={flashing} />
      {stationId === 'agents' && <AgentOrbits point={point} agents={orbits} />}
      <StationLabels point={point} label={label} total={activity.total} />
      <StationBadges point={point} running={activity.running} faults={activity.faults} />
    </g>
  );
}

function StationBadges({
  point,
  running,
  faults,
}: {
  point: MapPoint;
  running: number;
  faults: number;
}) {
  return (
    <g>
      <RunningBadge point={point} running={running} />
      <FaultBadge point={point} faults={faults} />
    </g>
  );
}

function CometDot({
  path,
  color,
  radius,
  delay,
  trail,
}: {
  path: string;
  color: string;
  radius: number;
  delay?: string;
  trail?: boolean;
}) {
  return (
    <circle r={radius} fill={color} className={trail ? 'lm-comet lm-trail' : 'lm-comet'}>
      <animateMotion dur={PULSE_DURATION} begin={delay} path={path} fill="freeze" />
    </circle>
  );
}

function PulseDot({ pulse, point }: { pulse: MapPulse; point: MapPoint }) {
  const centre = { x: CENTER_X, y: CENTER_Y };
  const from = pulse.inbound ? point : centre;
  const to = pulse.inbound ? centre : point;
  const path = `M ${from.x} ${from.y} L ${to.x} ${to.y}`;
  return (
    <g>
      {TRAIL_DELAYS.map((delay) => (
        <CometDot
          key={delay}
          path={path}
          color={pulse.color}
          radius={TRAIL_RADIUS}
          delay={delay}
          trail
        />
      ))}
      <CometDot path={path} color={pulse.color} radius={PULSE_RADIUS} />
    </g>
  );
}

function ringStroke(tone: CentreTone, fraction: number | null): string {
  if (tone === 'failed') {
    return 'var(--lm-danger)';
  }
  if (tone === 'warn') {
    return 'var(--lm-warn)';
  }
  if (tone === 'done') {
    return 'var(--lm-ok)';
  }
  if (tone === 'unknown' || fraction === null) {
    return 'var(--lm-muted)';
  }
  const percent = fraction * PERCENT_WHOLE;
  if (percent >= PERCENT_RED) {
    return 'var(--lm-danger)';
  }
  if (percent >= PERCENT_AMBER) {
    return 'var(--lm-warn)';
  }
  return 'var(--lm-accent)';
}

function UnknownMark({ tone }: { tone: CentreTone }) {
  if (tone !== 'unknown') {
    return null;
  }
  return (
    <text x={CENTER_X} y={CENTER_Y + UNKNOWN_OFFSET_Y} className="lm-centre-unknown">
      ?
    </text>
  );
}

function GaugeRing({ tone, fraction }: { tone: CentreTone; fraction: number | null }) {
  const ringLength = 2 * Math.PI * RING_RADIUS;
  const filled = fraction === null ? ringLength : fraction * ringLength;
  return (
    <circle
      cx={CENTER_X}
      cy={CENTER_Y}
      r={RING_RADIUS}
      className="lm-budget-ring"
      stroke={ringStroke(tone, fraction)}
      strokeDasharray={`${filled} ${ringLength}`}
      transform={`rotate(${TOP_ANGLE} ${CENTER_X} ${CENTER_Y})`}
    />
  );
}

function CentreTexts({
  budgetText,
  runStatus,
  tone,
}: {
  budgetText: string;
  runStatus: string;
  tone: CentreTone;
}) {
  return (
    <g>
      <text x={CENTER_X} y={CENTER_Y - TITLE_OFFSET_Y} className="lm-centre-title">
        ASF
      </text>
      <text x={CENTER_X} y={CENTER_Y + BUDGET_OFFSET_Y} className="lm-centre-budget">
        {budgetText}
      </text>
      <text x={CENTER_X} y={CENTER_Y + CAPTION_OFFSET_Y} className="lm-centre-caption">
        Budget
      </text>
      <UnknownMark tone={tone} />
      <text x={CENTER_X} y={CENTER_Y + STATUS_OFFSET_Y} className="lm-centre-status">
        {runStatus}
      </text>
    </g>
  );
}

function CentreNode({
  budgetPercent,
  budgetText,
  runStatus,
  flashing,
}: {
  budgetPercent: number | null;
  budgetText: string;
  runStatus: string;
  flashing: boolean;
}) {
  const fraction = gaugeFraction(budgetPercent);
  const tone = centreTone(runStatus);
  return (
    <g className={flashing ? 'lm-flash' : undefined}>
      <circle
        cx={CENTER_X}
        cy={CENTER_Y}
        r={CENTRE_RADIUS}
        className={`lm-centre lm-centre-${tone}`}
      />
      <GaugeRing tone={tone} fraction={fraction} />
      <CentreTexts budgetText={budgetText} runStatus={runStatus} tone={tone} />
    </g>
  );
}

function StationLayer({
  board,
  counters,
  pulses,
  flashing,
}: {
  board: BoardState;
  counters: MapCounters | null;
  pulses: MapPulse[];
  flashing: boolean;
}) {
  const counts = stationCounts(board, counters);
  const orbits = runningAgents(board);
  const points = stationPositions(STATION_ORDER.length);
  const pulsing = new Set(pulses.map((pulse) => pulse.station));
  const nodeFor = (station: (typeof STATION_ORDER)[number], index: number) => (
    <StationNode
      key={station.id}
      stationId={station.id}
      label={station.label}
      point={points[index]}
      count={counts[station.id]}
      level={stationLevel(counts[station.id], pulsing.has(station.id))}
      flashing={flashing && station.id === 'model'}
      orbits={station.id === 'agents' ? orbits : NO_ORBITS}
    />
  );
  return <g>{STATION_ORDER.map(nodeFor)}</g>;
}

function PulseLayer({
  pulses,
  pointOf,
}: {
  pulses: MapPulse[];
  pointOf: (station: MapStationId) => MapPoint;
}) {
  return (
    <g>
      {pulses.map((pulse) => (
        <PulseDot key={pulse.key} pulse={pulse} point={pointOf(pulse.station)} />
      ))}
    </g>
  );
}

const STATION_POINTS = stationPositions(STATION_ORDER.length);

function stationPointOf(station: MapStationId): MapPoint {
  return STATION_POINTS[STATION_ORDER.findIndex((s) => s.id === station)];
}

interface MapCanvasProps {
  board: BoardState;
  counters: MapCounters | null;
  pulses: MapPulse[];
  budgetPercent: number | null;
  budgetText: string;
  runStatus: string;
}

export function MapCanvas({
  board,
  counters,
  pulses,
  budgetPercent,
  budgetText,
  runStatus,
}: MapCanvasProps) {
  const flashing = isModelFlashing(board);
  const visible = capPulses(pulses, MAX_PARTICLES);
  return (
    <svg
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      className="lm-map"
      role="img"
      aria-label={`Live agent map: run ${runStatus}, budget ${budgetText}`}
    >
      <Stage />
      <StationLayer board={board} counters={counters} pulses={visible} flashing={flashing} />
      <PulseLayer pulses={visible} pointOf={stationPointOf} />
      <CentreNode
        budgetPercent={budgetPercent}
        budgetText={budgetText}
        runStatus={runStatus}
        flashing={flashing}
      />
    </svg>
  );
}
