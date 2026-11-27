# Implementation Plan: Live Map Visual Polish

**Spec**: `specs/008-live-map-visual-polish/spec.md`

## Inventory (step 0, verified)

- Rendering: `apps/dashboard/src/components/livemap/MapCanvas.tsx`
  (444 lines, used only by `LiveMapPage.tsx:93`), `MapFeed.tsx`,
  `MapSidePanel.tsx`; data hook `pages/LiveMap/useLiveMapData.ts`
  (untouched); pure board logic `src/lib/mapBoard.ts`; wire types
  `src/types/map.ts`; styles `lm-*` in `src/styles/global.css`.
- Data already available: station counts (`total/running/faults`),
  pulses with direction (`MapPulse.inbound`), budget percent via
  `budgetPercent(used, limit)` (null without a limit), run status
  string, agent orbit dots, model-change flash. No contract change
  is needed for any visual requirement.
- Dependencies: react only — no icon library, so icons are inline
  SVG written for this feature.
- `MapCanvas.tsx` currently has 0 unsuppressed ESLint violations;
  it must stay at 0 (Rule G).

## Approach

1. `src/lib/mapLayout.ts` (pure, tested): station positions for
   any n, gauge fraction (clamp, NaN-safe), station level
   (idle/active/error), badge formatting ("99+"), pulse capping.
2. `src/lib/mapMotion.ts`: motion constants (durations, particle
   cap, halo sizes) — no magic numbers in components.
3. `MapCanvas.tsx`: rounded-tile hubs with inline SVG icons,
   comet trails via SMIL `animateMotion`, error ring pulse,
   centre gauge with CSS transition, status tone classes,
   focusable hubs with `<title>` and aria labels, richer map
   aria-label. Existing orbit dots and clock behaviour preserved
   in spirit (orbit dots kept; station clock replaced by the
   active halo to match the tile design).
4. `global.css`: `--lm-*` tokens for light/dark built on existing
   tone tokens; stage background with vignette + dot grid;
   `@media (prefers-reduced-motion: reduce)` hides travelling
   dots/loops and keeps static halos.
5. `tests/mapLayout.test.ts` added to the explicit test list in
   `package.json`.

## Verification

`npm test`, `npm run build`, ESLint on touched files before/after
(unsuppressed counts must not grow), `format:check`. Backend
untouched, so no pytest. Screenshots: the sandbox cannot run the
dashboard against a real backend, so states are verified by unit
tests + build + code reading; visual confirmation on Windows is
the owner's step (run `npm run dev -- --host 127.0.0.1`).
