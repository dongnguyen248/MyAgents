import { isModelFlashing, spokeWidth, STATION_ORDER, stationCounts } from '../../lib/mapBoard';
import type { BoardState, StationCount } from '../../lib/mapBoard';
import type { MapCounters, MapStationId } from '../../types/map';

export interface MapPulse {
  key: string;
  station: MapStationId;
  color: string;
  inbound: boolean;
}

const VIEW_WIDTH = 640;
const VIEW_HEIGHT = 560;
const CENTER_X = 320;
const CENTER_Y = 280;
const RADIUS_X = 252;
const RADIUS_Y = 208;
const STATION_RADIUS = 15;
const HALO_FROM = 17;
const HALO_TO = 24;
const LABEL_OFFSET_Y = 24;
const COUNT_OFFSET_Y = 4;
const BADGE_OFFSET_X = 18;
const BADGE_OFFSET_Y = 10;
const FAULT_OFFSET = 14;
const FAULT_RADIUS = 6;
const FAULT_TEXT_OFFSET_Y = 15;
const CENTRE_RADIUS = 47;
const RING_RADIUS = 40;
const PULSE_RADIUS = 5;
const TITLE_OFFSET_Y = 12;
const BUDGET_OFFSET_Y = 4;
const CAPTION_OFFSET_Y = 20;
const STATUS_OFFSET_Y = 62;
const PERCENT_AMBER = 70;
const PERCENT_RED = 90;
const PERCENT_WHOLE = 100;
const FULL_CIRCLE = 360;
const TOP_ANGLE = -90;
const STATION_STEP = 40;
const CLOCK_RADIUS = 21;
const CLOCK_HOUR_LENGTH = 7;
const CLOCK_MINUTE_LENGTH = 11;

export function stationPoint(station: MapStationId): { x: number; y: number } {
  const index = STATION_ORDER.findIndex((s) => s.id === station);
  const angle = ((TOP_ANGLE + index * STATION_STEP) * Math.PI) / (FULL_CIRCLE / 2);
  return {
    x: CENTER_X + RADIUS_X * Math.cos(angle),
    y: CENTER_Y + RADIUS_Y * Math.sin(angle),
  };
}

function budgetRingColor(percent: number | null): string {
  if (percent === null) {
    return 'var(--border)';
  }
  if (percent >= PERCENT_RED) {
    return 'var(--danger)';
  }
  if (percent >= PERCENT_AMBER) {
    return 'var(--warn)';
  }
  return 'var(--accent)';
}

function StationHalo({ point, running }: { point: { x: number; y: number }; running: number }) {
  if (running === 0) {
    return null;
  }
  return (
    <circle cx={point.x} cy={point.y} r={HALO_FROM} className="lm-station-halo">
      <animate
        attributeName="r"
        values={`${HALO_FROM};${HALO_TO};${HALO_FROM}`}
        dur="1.6s"
        repeatCount="indefinite"
      />
      <animate attributeName="opacity" values="0.5;0.05;0.5" dur="1.6s" repeatCount="indefinite" />
    </circle>
  );
}

function RunningBadge({ point, running }: { point: { x: number; y: number }; running: number }) {
  if (running <= 1) {
    return null;
  }
  return (
    <text x={point.x + BADGE_OFFSET_X} y={point.y - BADGE_OFFSET_Y} className="lm-station-badge">
      ×{running}
    </text>
  );
}

function FaultBadge({ point, faults }: { point: { x: number; y: number }; faults: number }) {
  if (faults === 0) {
    return null;
  }
  return (
    <g>
      <circle
        cx={point.x + FAULT_OFFSET}
        cy={point.y + FAULT_OFFSET}
        r={FAULT_RADIUS}
        className="lm-fault-dot"
      />
      <text x={point.x + FAULT_OFFSET} y={point.y + FAULT_TEXT_OFFSET_Y} className="lm-fault-count">
        {faults}
      </text>
    </g>
  );
}

function StationBadges({
  point,
  count,
}: {
  point: { x: number; y: number };
  count: StationCount | undefined;
}) {
  return (
    <g>
      <RunningBadge point={point} running={count?.running ?? 0} />
      <FaultBadge point={point} faults={count?.faults ?? 0} />
    </g>
  );
}

function StationLabels({
  point,
  label,
  total,
}: {
  point: { x: number; y: number };
  label: string;
  total: number;
}) {
  return (
    <g>
      <text x={point.x} y={point.y - LABEL_OFFSET_Y} className="lm-station-label">
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
  running,
  total,
}: {
  point: { x: number; y: number };
  running: number;
  total: number;
}) {
  return (
    <line
      x1={CENTER_X}
      y1={CENTER_Y}
      x2={point.x}
      y2={point.y}
      className={running > 0 ? 'lm-spoke active' : 'lm-spoke'}
      strokeWidth={spokeWidth(total)}
    />
  );
}

function StationCircle({
  point,
  flashing,
}: {
  point: { x: number; y: number };
  flashing: boolean;
}) {
  return (
    <circle
      cx={point.x}
      cy={point.y}
      r={STATION_RADIUS}
      className={flashing ? 'lm-station lm-flash' : 'lm-station'}
    />
  );
}

function ClockHand({
  point,
  length,
  dur,
  className,
}: {
  point: { x: number; y: number };
  length: number;
  dur: string;
  className: string;
}) {
  const centre = `${point.x} ${point.y}`;
  return (
    <line x1={point.x} y1={point.y} x2={point.x} y2={point.y - length} className={className}>
      <animateTransform
        attributeName="transform"
        type="rotate"
        from={`0 ${centre}`}
        to={`360 ${centre}`}
        dur={dur}
        repeatCount="indefinite"
      />
    </line>
  );
}

function StationClock({ point, running }: { point: { x: number; y: number }; running: number }) {
  if (running === 0) {
    return null;
  }
  return (
    <g>
      <circle cx={point.x} cy={point.y} r={CLOCK_RADIUS} className="lm-clock-face" />
      <ClockHand point={point} length={CLOCK_HOUR_LENGTH} dur="12s" className="lm-clock-hour" />
      <ClockHand point={point} length={CLOCK_MINUTE_LENGTH} dur="2s" className="lm-clock-minute" />
    </g>
  );
}

function StationNode({
  stationId,
  label,
  count,
  flashing,
}: {
  stationId: MapStationId;
  label: string;
  count: StationCount | undefined;
  flashing: boolean;
}) {
  const point = stationPoint(stationId);
  const running = count?.running ?? 0;
  return (
    <g>
      <StationSpoke point={point} running={running} total={count?.total ?? 0} />
      <StationHalo point={point} running={running} />
      <StationCircle point={point} flashing={flashing} />
      <StationClock point={point} running={running} />
      <StationLabels point={point} label={label} total={count?.total ?? 0} />
      <StationBadges point={point} count={count} />
    </g>
  );
}

function PulseDot({ pulse }: { pulse: MapPulse }) {
  const point = stationPoint(pulse.station);
  const centre = { x: CENTER_X, y: CENTER_Y };
  const from = pulse.inbound ? point : centre;
  const to = pulse.inbound ? centre : point;
  return (
    <circle r={PULSE_RADIUS} fill={pulse.color} className="lm-pulse">
      <animateMotion dur="0.65s" path={`M ${from.x} ${from.y} L ${to.x} ${to.y}`} fill="freeze" />
    </circle>
  );
}

function CentreTexts({ budgetText, runStatus }: { budgetText: string; runStatus: string }) {
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
      <text x={CENTER_X} y={CENTER_Y + STATUS_OFFSET_Y} className="lm-centre-status">
        {runStatus}
      </text>
    </g>
  );
}

function CentreCircle({ flashing }: { flashing: boolean }) {
  return (
    <circle
      cx={CENTER_X}
      cy={CENTER_Y}
      r={CENTRE_RADIUS}
      className={flashing ? 'lm-centre lm-flash' : 'lm-centre'}
    />
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
  const ringLength = 2 * Math.PI * RING_RADIUS;
  const ringFilled = budgetPercent === null ? 0 : (budgetPercent / PERCENT_WHOLE) * ringLength;
  return (
    <g>
      <CentreCircle flashing={flashing} />
      <circle
        cx={CENTER_X}
        cy={CENTER_Y}
        r={RING_RADIUS}
        className="lm-budget-ring"
        stroke={budgetRingColor(budgetPercent)}
        strokeDasharray={`${ringFilled} ${ringLength}`}
        transform={`rotate(${TOP_ANGLE} ${CENTER_X} ${CENTER_Y})`}
      />
      <CentreTexts budgetText={budgetText} runStatus={runStatus} />
    </g>
  );
}

function StationLayer({
  board,
  counters,
  flashing,
}: {
  board: BoardState;
  counters: MapCounters | null;
  flashing: boolean;
}) {
  const counts = stationCounts(board, counters);
  return (
    <g>
      {STATION_ORDER.map((station) => (
        <StationNode
          key={station.id}
          stationId={station.id}
          label={station.label}
          count={counts[station.id]}
          flashing={flashing && station.id === 'model'}
        />
      ))}
    </g>
  );
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
  const centre = { budgetPercent, budgetText, runStatus, flashing };
  return (
    <svg
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      className="lm-map"
      role="img"
      aria-label="Live agent map"
    >
      <StationLayer board={board} counters={counters} flashing={flashing} />
      {pulses.map((pulse) => (
        <PulseDot key={pulse.key} pulse={pulse} />
      ))}
      <CentreNode {...centre} />
    </svg>
  );
}
