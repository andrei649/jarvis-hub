# WorldView Frontend

Next.js 14 (App Router) + TypeScript + TailwindCSS dashboard. Renders the time-scrubbable
3D globe with **Deck.gl + Mapbox GL** and synchronizes every layer from a single Zustand
**System Master Time** store.

## Status

STEP 5 implemented — the geospatial dashboard:

- **`components/DeckGlobe.tsx`** — Deck.gl `GeoJsonLayer`s over a Mapbox dark basemap, one
  styled layer per domain (military vs civil flights, vessels, satellites + footprints,
  intensity-shaded H3 jamming cells, intel/dark-vessel markers). Loaded `ssr: false`.
- **`components/TimelineScrubber.tsx`** — the master-time slider with play/pause, a LIVE
  toggle, speed control, and a UTC clock readout.
- **`components/LayerPanel.tsx`** — per-layer visibility toggles + the active trail selection.
- **Entity trails** — click an aircraft/vessel/satellite to fetch and draw its trailing-hour
  path (`useEntityTrack` → REST `/track` → a Deck.gl path layer); click empty space to clear.
- **`lib/store/useTimelineStore.ts`** — the Zustand "System Master Time" store every layer
  follows; **`lib/useMasterClock.ts`** advances it (wall-clock in live mode, `dt × speed`
  in historical); **`lib/useWorldViewData.ts`** fans the master clock out to data: debounced
  REST `/history` per visible layer (historical) or the `/live` WebSocket snapshot+deltas (live).

Validated: `tsc --noEmit` clean, `next build` passes (lint + types + prerender), and the
app serves HTTP 200 with the rendered shell.

## Develop

```bash
npm install            # from the worldview/ monorepo root (workspaces)
cp .env.local.example .env.local   # set NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN + NEXT_PUBLIC_API_URL
npm run dev --workspace frontend   # http://localhost:3000
```

The globe needs a Mapbox token for the basemap; layer data needs the backend-api running
(REST `/history` + WebSocket `/live`).

## Layout

Redesigned 2026-06-12 per `docs/design/WORLDVIEW_UX_SPEC.md` (brand tokens, zone system,
mode system, shape encodings, negative-space grammar — see the spec + `WORLDVIEW_UX_HANDOFF.md`
at the repo root `docs/design/`).

```
app/          App Router entry (layout: fontsource imports · page: app bar + zone rails + timeline)
components/   AppBar, ModeFrame, Panel (shared anatomy), MarkGlyph, DeckGlobe, CameraTour,
              LayerPanel (=legend), ReconPanel, StatsHud, Inspector (+ProvenanceSection),
              AlertsPanel, ExportPanel, TimelineScrubber (+ReplayControl), SystemStatus,
              HelpOverlay, ArrivalBanner, DemoLens, GlobeErrorBoundary
lib/          layers.ts, api.ts, types.ts, deckLayers.ts, markStyle.ts, markAtlas.ts,
              negativeSpace.ts, uiMode.ts, inspectorFields.ts, timelineMarkers.ts, arrival.ts,
              shortcuts.ts, tooltip.ts, useMasterClock.ts, useWorldViewData.ts,
              useReconWindows.ts, store/useTimelineStore.ts
```

## Note on dependency pins

The root `package.json` pins `@deck.gl/core` and the `@luma.gl/*` stack to 9.0.x via
`overrides` — deck.gl 9.0's peer ranges otherwise float luma to 9.3.x, whose renamed exports
break the build.
