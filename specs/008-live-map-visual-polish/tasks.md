# Tasks: Live Map Visual Polish

Markers: `[ ]` pending, `[x]` completed, `[~]` implemented locally
but unpushed, `[!]` awaiting owner decision.

- [x] Step 0 inventory: files, data surface, stop conditions
      checked (MapCanvas used only by LiveMapPage; spec 004 owns
      selection/counters, not visuals; no data change needed).
- [x] Pure layout/motion helpers in `src/lib` (positions, gauge
      fraction, station level, badge format, pulse cap).
- [x] Centre hub: gauge arc with clamp/transition, status tones,
      breathing for warn, "?" for UNKNOWN.
- [x] Satellite hubs: rounded tiles, inline SVG icons, labels,
      counts, idle/active/error levels, red fault badge.
- [x] Spokes and motion: active brightening, comet trails capped
      at 12, error ring pulse, reduced-motion support.
- [x] Accessibility: aria labels, focusable hubs with titles,
      status never colour-only.
- [x] Tests in `tests/mapLayout.test.ts`, added to package.json
      test list; npm test, build, lint before/after, format check.
- [!] Visual confirmation on Windows by owner (sandbox cannot
      render against a real backend).
