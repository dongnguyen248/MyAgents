# Feature Specification: Live Map Visual Polish

**Feature Branch**: `feat/map-visual-polish`

**Created**: 2026-11-26

**Status**: In progress (presentation-only)

**Input**: Make the Live Map feel alive, in the visual spirit of the
lot-map plugin (reference image supplied by the owner): dark stage,
glowing centre hub, satellite hubs with icons, light travelling
along spokes. Visual reference only — no code, icons, names, fonts,
or assets copied.

## Relation to spec 004

Spec 004 (PR 2a/2b/2c) owns snapshot selection, truthful
`UNKNOWN`/`queued` states, moment-error counting, operator pulses,
and the 2c error-dot/operator/provider UI semantics. This spec
changes none of that: it restyles how the existing board data is
drawn. Where 2c later adds data (e.g. moment-error counts), this
polish already renders faults from the existing counters.

## Scope

- Presentation only: `MapCanvas` rendering, `lm-*` styles, and new
  pure layout/motion helpers in `src/lib`.
- No change to the event/data contract (`types/map.ts`), to
  `useLiveMapData` logic, or to the backend.
- No new dependency: icons are hand-written inline SVG (the
  dashboard has no icon library).
- Motion via CSS/SMIL only; no per-frame React state. Concurrent
  travelling particles capped by a named constant (12).
- `prefers-reduced-motion`: travelling dots and looping pulses
  stop; static halo and status colours remain.
- Status is never colour-only: icons, counts, badges, and text
  always accompany colour. The map and each hub carry aria labels;
  hubs are keyboard-focusable with titles.

## Visual requirements

- Dark blue-black stage (`#0b0f17` → `#0e1420`) with a soft radial
  vignette and a very faint dot grid; colours are CSS variables
  with light/dark values, reusing the dashboard tone tokens
  (`--ok/--warn/--danger/--muted/--accent`).
- Centre hub: outer ring plus budget gauge arc. The arc follows
  the budget percent only when a limit exists (`MapBudget`
  `limitTokens`); without a limit the ring stays static and the
  absolute number shows as today — no invented percent. Arc value
  clamps to 0–100 and transitions smoothly. Status changes the
  ring tone: normal accent, ESCALATED/warn amber with a slow
  breathing, FAILED red, UNKNOWN muted with "?", completed calm
  green without blinking. Status text source unchanged.
- Satellite hubs: rounded dark tiles with a thin stroke, a
  hand-drawn line icon in the middle (Operator person, Model chip,
  Store database, Files file, Shell terminal, Network globe,
  Agents nodes, Skills bolt, Gates shield), label below, count
  under the label. Three levels: idle (dim), active (accent halo,
  slightly larger), error (red halo + red count badge top-left).
  "Active" derives from existing data (running count or a pulse in
  the current pulse set) via a pure function. Badges cap at "99+".
- Spokes: thin muted lines; active spokes brighten with a light
  comet (dot + fading trail) travelling centre→hub, or hub→centre
  when the pulse is inbound. Rejected/error state shows a red ring
  expanding from the hub once plus the red badge — no continuous
  blinking. No decorative hub-to-hub curves (no data for them).
- Layout: pure position function, angle = -90° + i·360°/n on an
  ellipse; station order unchanged; labels do not overlap for the
  current 9 stations; viewBox scales.
- Empty state: all hubs idle, centre shows current status with a
  very gentle breathing (off under reduced motion).

## Out of scope

- Any data/contract/backend change; snapshot selection (2a);
  counter semantics (2b); new stations or renamed statuses.
- Count deltas ("3 ↑1"): the board data does not carry deltas, so
  they are not shown.
