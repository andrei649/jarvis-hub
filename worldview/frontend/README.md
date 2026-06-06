# WorldView Frontend

Next.js 14 (App Router) + TypeScript + TailwindCSS dashboard. Renders the time-scrubbable
3D globe with **Deck.gl + Mapbox GL** and synchronizes every layer from a single Zustand
**System Master Time** store.

## Status

STEP 2 scaffold — app shell, Tailwind, the layer registry (`lib/layers.ts`), and the
master-time Zustand store skeleton (`lib/store/useTimelineStore.ts`). The Deck.gl map,
timeline scrubber, and live/historical fetch fan-out are implemented in **STEP 5**.

## Develop

```bash
npm install            # from the worldview/ monorepo root (workspaces)
cp .env.local.example .env.local   # set NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN
npm run dev --workspace frontend   # http://localhost:3000
```

## Layout

```
app/         App Router entry (layout, page, globals.css)
components/   DeckGlobe, TimelineScrubber, LayerPanel, ... (STEP 5)
lib/         layers.ts (the 5 data layers) + store/ (Zustand master clock)
```
